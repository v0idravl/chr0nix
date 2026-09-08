"""Command-line interface.

Three subcommands mirror the evidence-handling workflow:

- ``manifest`` — hash an exhibit directory at collection time, writing
  ``manifest.csv`` and ``manifest.json`` to a *separate* output
  directory.
- ``verify``   — re-hash the directory against a saved manifest and
  report OK / CHANGED / MISSING / EXTRA per file.
- ``custody``  — append one event to an append-only custody log,
  anchored to an exhibit hash from a manifest.

Exit codes are part of the contract, since the tool is meant to be
scripted into collection workflows:

- ``0`` — success (for ``verify``: every file intact).
- ``1`` — verification failed (any CHANGED / MISSING / EXTRA).
- ``2`` — operational error (bad paths, unsafe output location,
  malformed manifest, unknown exhibit).

``main`` returns the code rather than exiting so tests can drive the
CLI in-process; only ``__main__`` calls ``sys.exit``.
"""

import argparse
import sys
from pathlib import Path

from . import Cust0diaError, __version__, custody, manifest, verify
from .paths import is_within


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with all three subcommands."""
    parser = argparse.ArgumentParser(
        prog="cust0dia",
        description=(
            "Recursive SHA-256 exhibit manifests and append-only chain-of-custody "
            "logs. Read-only on evidence; fully offline; deterministic output."
        ),
        epilog="For lawful, authorized investigative documentation work only.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    manifest_parser = subparsers.add_parser(
        "manifest",
        help="hash an exhibit directory into manifest.csv and manifest.json",
        description="Walk an exhibit directory recursively, SHA-256 every file, "
        "and write a sorted manifest (CSV and JSON) to the output directory.",
    )
    manifest_parser.add_argument("evidence_dir", type=Path, help="directory of exhibits to hash (read-only)")
    manifest_parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        required=True,
        help="where to write manifest.csv and manifest.json "
        "(must NOT be inside the evidence directory)",
    )
    manifest_parser.set_defaults(func=_cmd_manifest)

    verify_parser = subparsers.add_parser(
        "verify",
        help="re-hash a directory against a manifest and report OK/CHANGED/MISSING/EXTRA",
        description="Re-hash every file listed in a manifest against the current "
        "contents of an exhibit directory and report per-file integrity status.",
    )
    verify_parser.add_argument("manifest", type=Path, help="manifest.csv or manifest.json to verify against")
    verify_parser.add_argument("evidence_dir", type=Path, help="directory of exhibits to re-hash (read-only)")
    verify_parser.set_defaults(func=_cmd_verify)

    custody_parser = subparsers.add_parser(
        "custody",
        help="append a chain-of-custody event to an append-only log",
        description="Append one row (timestamp, actor, action, exhibit, hash, notes) "
        "to a custody log. The exhibit must exist in the given manifest.",
    )
    custody_parser.add_argument("manifest", type=Path, help="manifest.csv or manifest.json the exhibit is listed in")
    custody_parser.add_argument("log", type=Path, help="custody log CSV to append to (created if missing)")
    custody_parser.add_argument("--exhibit", required=True, help="exhibit path, relative to the evidence root")
    custody_parser.add_argument("--actor", required=True, help="person performing the action, e.g. 'A. Rivera'")
    custody_parser.add_argument(
        "--action",
        required=True,
        help="custody action, e.g. COLLECTED, TRANSFERRED, ANALYZED, RETURNED",
    )
    custody_parser.add_argument("--notes", default="", help="optional free-text notes (single line)")
    custody_parser.set_defaults(func=_cmd_custody)

    return parser


def _require_directory(path: Path, what: str) -> Path:
    """Resolve ``path`` and confirm it is an existing directory."""
    if not path.exists():
        raise Cust0diaError(f"{what} does not exist: {path}")
    if not path.is_dir():
        raise Cust0diaError(f"{what} is not a directory: {path}")
    return path.resolve()


def _require_file(path: Path, what: str) -> Path:
    """Resolve ``path`` and confirm it is an existing regular file."""
    if not path.exists():
        raise Cust0diaError(f"{what} does not exist: {path}")
    if not path.is_file():
        raise Cust0diaError(f"{what} is not a regular file: {path}")
    return path.resolve()


def _cmd_manifest(args: argparse.Namespace) -> int:
    """Build and write both manifest serializations."""
    evidence_root = _require_directory(args.evidence_dir, "evidence directory")
    output_dir = args.output_dir.resolve()

    # The cardinal safety rule: never write tool output into the
    # evidence tree. Outputs beside evidence contaminate the very thing
    # being preserved, and a later manifest run would hash the tool's
    # own files into the record.
    if is_within(output_dir, evidence_root):
        raise Cust0diaError(
            f"refusing to write into the evidence directory: {output_dir} "
            f"is inside {evidence_root}"
        )

    entries = manifest.build_manifest(evidence_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "manifest.csv"
    json_path = output_dir / "manifest.json"
    manifest.write_csv(entries, csv_path)
    manifest.write_json(entries, evidence_root, json_path)

    print(f"hashed {len(entries)} file(s) under {evidence_root}")
    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    """Re-hash the tree and print a per-file integrity report."""
    manifest_path = _require_file(args.manifest, "manifest")
    evidence_root = _require_directory(args.evidence_dir, "evidence directory")

    _, entries = manifest.read_manifest(manifest_path)
    results = verify.verify_tree(evidence_root, entries)

    for result in results:
        line = f"{result.status:<8}{result.relative_path}"
        if result.detail:
            line += f"  ({result.detail})"
        print(line)

    counts = verify.summarize(results)
    summary = ", ".join(f"{counts[status]} {status}" for status in verify.STATUS_ORDER)
    if verify.passed(results):
        print(f"verification PASSED: {summary}")
        return 0
    print(f"verification FAILED: {summary}")
    return 1


def _cmd_custody(args: argparse.Namespace) -> int:
    """Append one custody event anchored to a manifested exhibit."""
    manifest_path = _require_file(args.manifest, "manifest")
    log_path = args.log.resolve()
    if log_path == manifest_path:
        raise Cust0diaError("the custody log and the manifest must be different files")

    recorded_root, entries = manifest.read_manifest(manifest_path)

    # If the manifest records its evidence root (JSON format), extend
    # the read-only guarantee: the custody log must not live inside the
    # evidence tree either.
    if recorded_root:
        evidence_root = Path(recorded_root).resolve()
        if is_within(log_path, evidence_root):
            raise Cust0diaError(
                f"refusing to write into the evidence directory: {log_path} "
                f"is inside {evidence_root}"
            )

    exhibit = manifest.lookup_entry(entries, args.exhibit)
    custody.append_custody_row(
        log_path,
        actor=args.actor,
        action=args.action,
        exhibit=exhibit,
        notes=args.notes,
    )
    print(f"logged {args.action.strip()} on {exhibit.relative_path} ({exhibit.sha256[:12]}…) -> {log_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch; return the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Cust0diaError as exc:
        # Expected, user-fixable failures get a clean one-line message;
        # tracebacks are reserved for genuine bugs.
        print(f"cust0dia: error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"cust0dia: error: {exc}", file=sys.stderr)
        return 2
