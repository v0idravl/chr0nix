"""Command-line interface: ``extract`` (single image) and ``batch`` (directory).

Both subcommands share the same safety contract, enforced before any bytes
are written:

* inputs must exist and be the expected type;
* the output directory must not be the evidence directory or inside it;
* inputs are opened read-only — there is no write path to an input file.

Exit codes: ``0`` success, ``1`` expected failure (bad input, refused
output path, unparseable image), ``2`` argparse usage errors. All
diagnostics go to stderr; stdout carries only results and locations.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import TOOL_NAME, __version__
from .analyze import analyze_image, iter_images
from .errors import M3talexError
from .integrity import manifest_entry, utc_now_iso
from .report import write_batch_outputs, write_json_report
from .safety import ensure_output_dir, validate_input_dir, validate_input_file

DEFAULT_OUTDIR = "m3talex-output"


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with both subcommands."""
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=(
            "Extract image metadata (JPEG EXIF, PNG text chunks), flag "
            "anomalies as documented observations, and hash every input "
            "into its report. Read-only on inputs; fully offline."
        ),
        epilog="For lawful, authorized investigative documentation work only.",
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    extract = subparsers.add_parser(
        "extract",
        help="analyze one image and write a JSON report",
        description="Parse one JPEG/PNG, evaluate anomaly heuristics, "
        "and write a per-image JSON report.",
    )
    extract.add_argument("image", help="path to a JPEG or PNG image")
    extract.add_argument(
        "-o", "--outdir", default=DEFAULT_OUTDIR,
        help=f"output directory (default: {DEFAULT_OUTDIR}); must not be "
        "inside the input image's directory",
    )
    extract.set_defaults(handler=_cmd_extract)

    batch = subparsers.add_parser(
        "batch",
        help="analyze a directory of images and write a batch report",
        description="Recursively analyze every JPEG/PNG in a directory. "
        "Writes one JSON report per image, a Markdown summary, and "
        "cust0dia-format CSV/JSON manifests.",
    )
    batch.add_argument("directory", help="directory of images to analyze (searched recursively)")
    batch.add_argument(
        "-o", "--outdir", default=DEFAULT_OUTDIR,
        help=f"output directory (default: {DEFAULT_OUTDIR}); must not be "
        "inside the analyzed directory",
    )
    batch.set_defaults(handler=_cmd_batch)
    return parser


def _cmd_extract(args: argparse.Namespace) -> int:
    """Handle ``extract``: one image in, one JSON report out."""
    image = validate_input_file(args.image)
    # The evidence directory for a single file is its parent: writing the
    # report next to the exhibit is exactly what we refuse to do.
    outdir = ensure_output_dir(args.outdir, image.parent)
    record = analyze_image(image)
    report_path = write_json_report(record, outdir)
    _print_summary(record, report_path)
    return 0


def _cmd_batch(args: argparse.Namespace) -> int:
    """Handle ``batch``: a directory in, the full artifact set out."""
    root = validate_input_dir(args.directory)
    outdir = ensure_output_dir(args.outdir, root)
    images = iter_images(root)
    if not images:
        raise M3talexError(f"no JPEG/PNG images found under {root}")

    hashed_at = utc_now_iso()  # one honest timestamp shared by the whole batch
    records: list[dict] = []
    manifest_entries: list[dict] = []
    failures = 0
    for image in images:
        # Hash every discovered image into the manifest, even one that
        # turns out to be unparseable — its bytes still exist as evidence.
        manifest_entries.append(manifest_entry(image, root, hashed_at))
        try:
            records.append(analyze_image(image, root))
        except M3talexError as exc:
            # One corrupt file must not sink the batch; it is reported and
            # the run continues with the remaining images.
            failures += 1
            print(f"warning: skipped {image.relative_to(root)}: {exc}", file=sys.stderr)

    written = write_batch_outputs(records, manifest_entries, outdir, root)
    total_findings = sum(len(record["findings"]) for record in records)
    print(f"analyzed {len(records)} image(s), {total_findings} finding(s)"
          + (f", {failures} file(s) skipped" if failures else ""))
    print(f"batch report: {written['markdown']}")
    print(f"manifests:    {written['manifest_csv']}, {written['manifest_json']}")
    print(f"JSON reports: {outdir}")
    return 0


def _print_summary(record: dict, report_path: Path) -> None:
    """Print a compact human summary for single-image extraction."""
    file_info = record["file"]
    print(f"{file_info['path']} ({file_info['format']}, {file_info['size_bytes']} bytes)")
    print(f"sha256: {file_info['sha256']}")
    if record["findings"]:
        for finding in record["findings"]:
            print(f"  [{finding['confidence']:>6}] {finding['id']}: {finding['observation']}")
    else:
        print("  no anomalies flagged")
    for note in record["notes"]:
        print(f"  note: {note}")
    print(f"report: {report_path}")


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse arguments, dispatch, translate errors to exit codes."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except M3talexError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: filesystem failure: {exc}", file=sys.stderr)
        return 1
