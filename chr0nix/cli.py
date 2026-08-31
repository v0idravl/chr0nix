"""Command-line interface: argparse wiring, safety checks, exit codes.

Two subcommands:

* ``build``  — the full pipeline: register sources, declare timezones,
  normalize, merge, render the timeline (CSV + Markdown), and write the
  SHA-256 input manifest (CSV + JSON).
* ``schema`` — print the input CSV contract, or write an empty template
  header row to start a new source export from.

Safety posture, enforced here because this is the trust boundary:

* Inputs are verified to exist and be regular files before reading.
* Inputs are opened read-only; nothing in this package ever opens an
  input path for writing.
* The output directory must be disjoint from the evidence: it may not
  be an input's directory, may not live inside one, and may not contain
  any input. Violations are refused before a single byte is written.
* Every validation error across every source is raised before any
  output file is created, so a failed run leaves no partial artifacts.

Exit codes: 0 success; 2 usage or validation failure (matching
argparse's own convention); 3 when ``--strict`` is set and any row was
flagged — success, but success a reviewer must look at.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, manifest, normalize, render, schema, timeline
from .errors import Chr0nixError
from .schema import SourceSpec
from .timeutil import utcnow

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_STRICT_FLAGGED = 3

#: Filenames written into the output directory by ``build``.
OUTPUT_FILES = ("timeline.csv", "timeline.md", "manifest.csv", "manifest.json")


def _parse_name_value(pair: str, option: str) -> tuple[str, str]:
    """Split a ``NAME=VALUE`` CLI pair, rejecting malformed input."""
    if "=" not in pair:
        raise Chr0nixError(f"{option} expects NAME=VALUE, got {pair!r}")
    name, value = pair.split("=", 1)
    name, value = name.strip(), value.strip()
    if not name or not value:
        raise Chr0nixError(f"{option} expects NAME=VALUE, got {pair!r}")
    return name, value


def _resolve_sources(source_args: list[str], tz_args: list[str]) -> list[SourceSpec]:
    """Turn ``--source``/``--tz`` arguments into validated SourceSpecs.

    Every declared timezone must attach to a registered source (a stray
    ``--tz`` is a typo worth failing on), source names must be unique and
    safe, and each path must exist and be a regular file.
    """
    timezones: dict[str, str] = {}
    for pair in tz_args:
        name, tz_name = _parse_name_value(pair, "--tz")
        schema.validate_source_name(name)
        timezones[name] = tz_name

    specs: list[SourceSpec] = []
    seen: set[str] = set()
    for pair in source_args:
        name, path_text = _parse_name_value(pair, "--source")
        schema.validate_source_name(name)
        if name in seen:
            raise Chr0nixError(f"duplicate source name {name!r}")
        seen.add(name)
        path = Path(path_text)
        if not path.exists():
            raise Chr0nixError(f"{name}: input path does not exist: {path}")
        if not path.is_file():
            raise Chr0nixError(f"{name}: input path is not a regular file: {path}")
        specs.append(SourceSpec(name=name, path=path, tz_name=timezones.get(name)))

    stray = sorted(set(timezones) - seen)
    if stray:
        raise Chr0nixError(
            f"--tz declared for unregistered source(s): {', '.join(stray)}"
        )
    return specs


def _check_output_location(out_dir: Path, input_paths: list[Path]) -> None:
    """Refuse to write outputs anywhere that could touch the evidence.

    Two failure directions are checked symmetrically: the output
    directory being an input's directory (or nested inside one), and any
    input living inside the output directory. Both would blur the line
    between evidence and work product, so both are rejected outright.
    """
    out = out_dir.resolve()
    for input_path in input_paths:
        resolved = input_path.resolve()
        evidence_dir = resolved.parent
        if out == evidence_dir or out.is_relative_to(evidence_dir):
            raise Chr0nixError(
                f"refusing to write outputs into evidence directory "
                f"{evidence_dir} (source of {resolved.name}); choose a "
                "separate output directory"
            )
        if resolved.is_relative_to(out):
            raise Chr0nixError(
                f"output directory {out} contains input file {resolved}; "
                "outputs and evidence must stay separate"
            )


def _cmd_schema(args: argparse.Namespace) -> int:
    """Print the input schema, or write an empty template CSV."""
    if args.template:
        template_path = Path(args.template)
        if template_path.exists():
            raise Chr0nixError(f"refusing to overwrite existing file: {template_path}")
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(",".join(schema.ALL_COLUMNS) + "\n", encoding="utf-8")
        print(f"chr0nix: wrote schema template to {template_path}")
        return EXIT_OK

    print("chr0nix input CSV schema")
    print("=" * 24)
    print("\nRequired columns:")
    for column in schema.REQUIRED_COLUMNS:
        print(f"  {column}")
    print("\nOptional columns:")
    for column in schema.OPTIONAL_COLUMNS:
        print(f"  {column}")
    print(
        "\nTimestamps must be ISO-8601. Naive values are interpreted in the"
        "\nsource's declared --tz; offset-aware values stand on their recorded"
        "\noffset. A source with naive timestamps and no declared --tz fails."
    )
    return EXIT_OK


def _cmd_build(args: argparse.Namespace) -> int:
    """Run the full normalize → merge → render → manifest pipeline."""
    specs = _resolve_sources(args.source, args.tz)
    out_dir = Path(args.out)
    _check_output_location(out_dir, [spec.path for spec in specs])

    # Phase 1: load and normalize everything. Any Chr0nixError raised
    # here aborts before a single output file exists — no partial runs.
    events = []
    warnings: list[str] = []
    for spec in specs:
        source_events, source_warnings = normalize.load_source(spec)
        events.extend(source_events)
        warnings.extend(source_warnings)
    ordered = timeline.build_timeline(events)
    flagged = [event for event in ordered if event.flags]

    for warning in warnings:
        print(f"chr0nix: warning: {warning}", file=sys.stderr)
    for event in flagged:
        print(
            f"chr0nix: warning: {event.source} row {event.source_row} "
            f"({event.event_id}): {', '.join(event.flags)}",
            file=sys.stderr,
        )

    if args.strict and flagged:
        print(
            f"chr0nix: --strict: {len(flagged)} flagged row(s); "
            "resolve them in the source exports before filing",
            file=sys.stderr,
        )
        return EXIT_STRICT_FLAGGED

    # Phase 2: render and write. Everything below is output-only.
    observed_at = utcnow()
    root, entries = manifest.build_manifest([spec.path for spec in specs], observed_at)
    sources_table = [(spec.name, spec.path, spec.tz_name or "") for spec in specs]

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "timeline.csv": render.render_timeline_csv(ordered),
        "timeline.md": render.render_timeline_markdown(
            ordered, sources_table, observed_at, title=args.title
        ),
        "manifest.csv": manifest.render_manifest_csv(entries),
        "manifest.json": manifest.render_manifest_json(
            entries, root, tool=f"chr0nix {__version__}", generated_at=observed_at
        ),
    }
    for filename, content in outputs.items():
        (out_dir / filename).write_text(content, encoding="utf-8")

    duplicates = timeline.count_duplicate_instants(ordered)
    print(
        f"chr0nix: normalized {len(ordered)} events from {len(specs)} source(s); "
        f"{len(flagged)} flagged, {duplicates} sharing an exact UTC instant"
    )
    for filename in OUTPUT_FILES:
        print(f"  wrote {out_dir / filename}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with subcommands and help text."""
    parser = argparse.ArgumentParser(
        prog="chr0nix",
        description=(
            "Normalize multi-source incident CSV exports into a UTC-ordered, "
            "hash-manifested exhibit timeline."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    build = subparsers.add_parser(
        "build",
        help="Build the unified exhibit timeline from source CSV exports.",
        description=(
            "Register each source CSV with --source NAME=PATH, declare each "
            "source's timezone with --tz NAME=IANA_TZ (required for sources "
            "with naive timestamps), and write timeline.csv, timeline.md, "
            "manifest.csv, and manifest.json to --out."
        ),
    )
    build.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="register a source CSV under a short identifier (repeatable); "
        "example: --source cctv=dvr_export.csv",
    )
    build.add_argument(
        "--tz",
        action="append",
        default=[],
        metavar="NAME=IANA_TZ",
        help="declare a source's timezone (repeatable); example: "
        "--tz cctv=America/Los_Angeles",
    )
    build.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help="output directory (must be separate from all input/evidence "
        "directories)",
    )
    build.add_argument(
        "--title",
        default=None,
        metavar="TEXT",
        help="case title for the Markdown report header",
    )
    build.add_argument(
        "--strict",
        action="store_true",
        help="exit with code 3 if any row is flagged (ambiguous or "
        "nonexistent local time, offset/timezone mismatch)",
    )
    build.set_defaults(func=_cmd_build)

    schema_cmd = subparsers.add_parser(
        "schema",
        help="Print the input CSV schema, or write an empty template.",
    )
    schema_cmd.add_argument(
        "--template",
        metavar="PATH",
        help="write an empty template CSV (header only) to PATH instead of "
        "printing the schema",
    )
    schema_cmd.set_defaults(func=_cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse arguments, dispatch, translate errors to exits."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Chr0nixError as exc:
        print(f"chr0nix: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
