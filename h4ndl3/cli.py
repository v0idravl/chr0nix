"""Command-line interface for h4ndl3.

Subcommands mirror the analyst's workflow, in order:

- ``worksheet`` — generate the research checklist for an identifier;
- ``add``       — append a validated finding to the JSONL store;
- ``validate``  — re-validate an existing store (e.g. after hand edits);
- ``report``    — render the store to Markdown with the corroboration
                  summary;
- ``manifest``  — hash a directory of outputs into the shared suite
                  manifest format.

Every subcommand accepts ``--now`` to pin the UTC timestamp it stamps
into its output. That single flag is what makes every output byte-for-
byte reproducible — determinism is a review feature, not a convenience.

Exit codes: 0 on success, 1 on any validation, I/O, or usage failure
(argparse's own usage errors exit 2, per convention).
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, findings, identifiers, manifest, report, worksheet
from .common import OutputPathError, ensure_output_allowed, utc_now_iso
from .findings import FindingError
from .identifiers import IdentifierError


def _add_now_argument(parser: argparse.ArgumentParser) -> None:
    """Attach the shared reproducibility flag to a subcommand."""
    parser.add_argument(
        "--now",
        metavar="UTC_ISO8601",
        default=None,
        help=(
            "pin the timestamp stamped into output (e.g. "
            "2026-08-31T12:00:00Z) for byte-reproducible results; "
            "defaults to the current UTC time"
        ),
    )


def _resolve_now(value: str | None) -> str:
    """Validate a ``--now`` override or fall back to the wall clock."""
    if value is None:
        return utc_now_iso()
    return findings.validate_utc_timestamp(value, field="--now")


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="h4ndl3",
        description=(
            "Offline-first identifier research worksheet CLI. h4ndl3 makes "
            "no network calls of any kind: it generates checklists of "
            "lawful public checks, stores analyst-recorded findings with "
            "strict provenance validation, and renders reports that "
            "enforce two corroborations before a claim."
        ),
        epilog=(
            "For lawful, authorized investigative documentation work only. "
            "Public sources, manual checks, documented provenance."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_worksheet = subparsers.add_parser(
        "worksheet",
        help="generate a research worksheet for one identifier",
        description=(
            "Generate a Markdown worksheet mapping the identifier's type "
            "to a checklist of lawful public checks. Type is auto-detected "
            "unless --type is given."
        ),
    )
    p_worksheet.add_argument("identifier", help="username, email, or domain to research")
    p_worksheet.add_argument(
        "--type",
        choices=identifiers.IDENTIFIER_TYPES,
        default=None,
        dest="id_type",
        help="identifier type (default: auto-detect from shape)",
    )
    p_worksheet.add_argument(
        "--store",
        default="findings.jsonl",
        metavar="PATH",
        help="findings store path to embed in the worksheet's add-command "
             "template (default: findings.jsonl)",
    )
    p_worksheet.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="write the worksheet to PATH instead of stdout",
    )
    _add_now_argument(p_worksheet)

    p_add = subparsers.add_parser(
        "add",
        help="append a validated finding to the JSONL store",
        description=(
            "Append one finding to the store. All required fields must be "
            "present and valid or nothing is written. The store file is "
            "created if it does not exist; existing rows are never modified."
        ),
    )
    p_add.add_argument("--store", required=True, metavar="PATH", help="JSONL findings store")
    p_add.add_argument("--claim", required=True, help="the observation, stated plainly")
    p_add.add_argument("--source-url", required=True, help="public http(s) URL where it was seen")
    p_add.add_argument(
        "--retrieved-at",
        required=True,
        metavar="UTC_ISO8601",
        help="when the source was viewed, UTC ISO-8601 (e.g. 2026-08-31T12:00:00Z)",
    )
    p_add.add_argument(
        "--confidence",
        required=True,
        choices=findings.CONFIDENCE_LEVELS,
        help="analyst confidence in the observation",
    )
    p_add.add_argument(
        "--corroborated-by",
        nargs="*",
        default=[],
        metavar="URL",
        help="independent corroborating source URLs (two required before a "
             "claim counts as corroborated)",
    )
    p_add.add_argument("--notes", default=None, help="optional context")
    _add_now_argument(p_add)

    p_validate = subparsers.add_parser(
        "validate",
        help="validate every row of an existing findings store",
        description=(
            "Re-validate a store (e.g. after hand edits). Prints the row "
            "count on success; names the offending line on failure."
        ),
    )
    p_validate.add_argument("--store", required=True, metavar="PATH", help="JSONL findings store")

    p_report = subparsers.add_parser(
        "report",
        help="render the findings store to a Markdown report",
        description=(
            "Render findings to Markdown with a corroboration summary. "
            "Refuses to overwrite the store it reads from."
        ),
    )
    p_report.add_argument("--store", required=True, metavar="PATH", help="JSONL findings store")
    p_report.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="write the report to PATH instead of stdout",
    )
    p_report.add_argument(
        "--title",
        default="Identifier Research Report",
        help="report heading (default: %(default)s)",
    )
    _add_now_argument(p_report)

    p_manifest = subparsers.add_parser(
        "manifest",
        help="hash a directory into a shared-format SHA-256 manifest",
        description=(
            "Recursively hash regular files under --root and write a "
            "manifest (CSV or JSON) in the shared suite format. Refuses "
            "to write the manifest inside the directory it describes."
        ),
    )
    p_manifest.add_argument("--root", required=True, metavar="DIR", help="directory to hash")
    p_manifest.add_argument("--out", required=True, metavar="PATH", help="manifest output path")
    p_manifest.add_argument(
        "--format",
        choices=("csv", "json"),
        default="csv",
        help="manifest format (default: csv)",
    )
    _add_now_argument(p_manifest)

    return parser


def _cmd_worksheet(args: argparse.Namespace) -> int:
    id_type = args.id_type or identifiers.classify(args.identifier)
    content = worksheet.render_worksheet(
        args.identifier,
        id_type,
        generated_at_utc=_resolve_now(args.now),
        store_path=args.store,
    )
    _write_text(content, args.out)
    return 0


def _cmd_add(args: argparse.Namespace) -> int:
    finding = findings.new_finding(
        claim=args.claim,
        source_url=args.source_url,
        retrieved_at_utc=args.retrieved_at,
        confidence=args.confidence,
        corroborated_by=args.corroborated_by,
        notes=args.notes,
        recorded_at_utc=_resolve_now(args.now),
    )
    findings.append_finding(args.store, finding)
    print(f"recorded finding in {args.store}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    rows = findings.load_store(args.store)
    print(f"{args.store}: {len(rows)} finding(s), all valid")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    rows = findings.load_store(args.store)
    if args.out:
        # The report is a derivative of the store; writing it over the
        # store would destroy the record it summarizes.
        ensure_output_allowed(args.out, protected_files=(args.store,))
    content = report.render_report(
        rows,
        generated_at_utc=_resolve_now(args.now),
        title=args.title,
    )
    _write_text(content, args.out)
    return 0


def _cmd_manifest(args: argparse.Namespace) -> int:
    count = manifest.write_manifest(
        args.root,
        args.out,
        fmt=args.format,
        hashed_at_utc=_resolve_now(args.now),
    )
    print(f"wrote {count} entr{'y' if count == 1 else 'ies'} to {args.out}")
    return 0


def _write_text(content: str, out: str | None) -> None:
    """Write rendered text to a file, or stdout when no path is given."""
    if out is None:
        sys.stdout.write(content)
        return
    with open(out, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


_DISPATCH = {
    "worksheet": _cmd_worksheet,
    "add": _cmd_add,
    "validate": _cmd_validate,
    "report": _cmd_report,
    "manifest": _cmd_manifest,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code.

    All anticipated failures (bad identifiers, invalid findings, unsafe
    output paths, missing files) are converted into a clean message on
    stderr and exit code 1 — the analyst should never see a traceback
    for an input mistake.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _DISPATCH[args.command]
    try:
        return handler(args)
    except (IdentifierError, FindingError, OutputPathError, ValueError) as exc:
        print(f"h4ndl3: error: {exc}", file=sys.stderr)
        return 1
    except (OSError, NotADirectoryError) as exc:
        # NotADirectoryError is an OSError; listed explicitly for clarity.
        print(f"h4ndl3: error: {exc}", file=sys.stderr)
        return 1
