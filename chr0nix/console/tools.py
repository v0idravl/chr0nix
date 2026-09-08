"""Tool registry: the console's plugin surface.

A *tool* is one investigative utility exposed through the console. All
five suite tools are registered here: cust0dia (manifest / verify /
custody), timeline (multi-source UTC timelines), h4ndl3 (identifier
research worksheets and corroborated findings), m3talex (image
metadata extraction), and casework (case workspaces: cases, entities,
and associations).

The registry is deliberately **static**: a tuple written out in source,
not a discovery mechanism. There is no scanning of directories for
plugins and no importing modules by name at runtime — in a tool that
may be scrutinized in court, the set of code that can execute must be
exactly the set of code a reviewer can read. Adding a tool is an
explicit, reviewable commit.

Command handlers are pure ``(SessionContext, args) -> str`` functions:
they mutate session state and the case files through the core modules,
and return the text the UI should display. They never print and never
import curses, which keeps the entire decision layer unit-testable.
Handlers call each module's core functions in-process — the console
never shells out to a module CLI, so every safety rule the CLI enforces
(evidence/output separation, strict schema validation) is inherited
from the same code, not reimplemented.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cust0dia import custody, manifest, verify
from cust0dia.paths import is_within
from h4ndl3 import findings as h4ndl3_findings
from h4ndl3 import identifiers as h4ndl3_identifiers
from h4ndl3 import report as h4ndl3_report
from h4ndl3 import worksheet as h4ndl3_worksheet
from h4ndl3.common import ensure_output_allowed, utc_now_iso
from m3talex.analyze import analyze_image, iter_images
from m3talex.errors import M3talexError
from m3talex.integrity import manifest_entry
from m3talex.integrity import utc_now_iso as m3talex_utc_now_iso
from m3talex.report import write_batch_outputs, write_json_report
from m3talex.safety import ensure_output_dir, validate_input_dir, validate_input_file

from .. import __version__ as suite_version
from ..casework import cases as casework_cases
from ..casework import entities as casework_entities
from ..casework import synopsis as casework_synopsis
from ..casework import workspace as casework_workspace
from ..errors import SuiteError
from ..timeline import cli as timeline_cli
from ..timeline import manifest as timeline_manifest
from ..timeline import normalize as timeline_normalize
from ..timeline import render as timeline_render
from ..timeline import schema as timeline_schema
from ..timeline import timeline as timeline_core
from ..timeline.timeutil import utcnow as timeline_utcnow
from .session import SessionContext

#: A console command handler: takes the session and the arguments that
#: followed the command name, returns display text.
Handler = Callable[[SessionContext, list[str]], str]


@dataclass(frozen=True)
class Command:
    """One command a tool adds to the console.

    ``name`` may contain a space (e.g. ``"show exhibits"``); the
    dispatcher matches the longest known prefix of the input line, so
    tool commands can hang off core command words.
    """

    name: str
    usage: str
    summary: str
    handler: Handler


@dataclass(frozen=True)
class Tool:
    """One investigative utility exposed through the console."""

    name: str
    summary: str
    run: Callable[[SessionContext], str]
    commands: tuple[Command, ...]


# ---------------------------------------------------------------------------
# cust0dia — the foundational tool: manifests, verification, custody.
# ---------------------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    """Uniform guard for missing session prerequisites."""
    if condition:
        raise SuiteError(message)


def _run_cust0dia(session: SessionContext) -> str:
    """Two-phase primary action: collect first, verify thereafter.

    The phase is chosen by whether the session's manifest exists on
    disk. Before collection there is nothing to verify against, so
    ``run`` builds the manifest; once a manifest exists, ``run``
    re-hashes the evidence tree against it. That mirrors how an
    investigator actually works — hash at collection, verify before
    reporting — and makes the second commonest action zero-typing.

    To re-manifest a legitimately changed tree (a new collection), the
    investigator says so explicitly with ``unset manifest``.
    """
    if session.manifest_path is not None and session.manifest_path.is_file():
        return _verify_phase(session)
    return _manifest_phase(session)


def _manifest_phase(session: SessionContext) -> str:
    _require(session.evidence_dir is None, "evidence is not set (use: set evidence <dir>)")
    _require(session.output_dir is None, "output is not set (use: set output <dir>)")
    entries = manifest.build_manifest(session.evidence_dir)
    session.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = session.output_dir / "manifest.csv"
    json_path = session.output_dir / "manifest.json"
    manifest.write_csv(entries, csv_path)
    manifest.write_json(entries, session.evidence_dir, json_path)
    return "\n".join(
        [
            f"hashed {len(entries)} file(s) under {session.evidence_dir}",
            f"wrote {csv_path}",
            f"wrote {json_path}",
            "manifest recorded — the next `run` will verify against it",
        ]
    )


def _verify_phase(session: SessionContext) -> str:
    _require(session.evidence_dir is None, "evidence is not set (use: set evidence <dir>)")
    _, entries = manifest.read_manifest(session.manifest_path)
    results = verify.verify_tree(session.evidence_dir, entries)
    lines = []
    for result in results:
        line = f"{result.status:<8}{result.relative_path}"
        if result.detail:
            line += f"  ({result.detail})"
        lines.append(line)
    counts = verify.summarize(results)
    summary = ", ".join(f"{counts[status]} {status}" for status in verify.STATUS_ORDER)
    verdict = "PASSED" if verify.passed(results) else "FAILED"
    lines.append(f"verification {verdict}: {summary}")
    return "\n".join(lines)


def _load_entries(session: SessionContext):
    """Read the session manifest or raise a guidance-rich error."""
    _require(session.manifest_path is None, "manifest is not set (use: set manifest <file>)")
    if not session.manifest_path.is_file():
        raise SuiteError(
            f"manifest {session.manifest_path} does not exist yet — run once to create it"
        )
    return manifest.read_manifest(session.manifest_path)


def _cmd_show_exhibits(session: SessionContext, args: list[str]) -> str:
    """List the manifest's exhibits so one can be picked for logging."""
    _, entries = _load_entries(session)
    if not entries:
        return "manifest contains no exhibits"
    lines = [f"{'exhibit':<48}{'size':>10}  sha256"]
    for entry in entries:
        lines.append(f"{entry.relative_path:<48}{entry.size_bytes:>10}  {entry.sha256[:12]}…")
    return "\n".join(lines)


def _cmd_show_log(session: SessionContext, args: list[str]) -> str:
    """Print the custody log verbatim — it is a record, not a view."""
    _require(session.custody_log is None, "log is not set (use: set log <file>)")
    if not session.custody_log.is_file():
        return f"no custody log yet at {session.custody_log}"
    return session.custody_log.read_text(encoding="utf-8").rstrip("\n")


def _cmd_log(session: SessionContext, args: list[str]) -> str:
    """Append a custody event against a manifested exhibit.

    Reuses :func:`cust0dia.manifest.lookup_entry` and
    :func:`cust0dia.custody.append_custody_row`, so every integrity
    rule the CLI enforces — manifest anchoring, header validation,
    control-character rejection — applies here unchanged.
    """
    if len(args) < 2:
        raise SuiteError("usage: log <exhibit> <ACTION> [notes...]")
    exhibit_path, action = args[0], args[1]
    notes = " ".join(args[2:])
    _require(session.actor is None, "actor is not set (use: set actor <name>)")
    _require(session.custody_log is None, "log is not set (use: set log <file>)")
    recorded_root, entries = _load_entries(session)

    # Same extension of the read-only guarantee the CLI makes: when the
    # manifest knows its evidence root, the log must not live inside it.
    if recorded_root:
        evidence_root = Path(recorded_root).resolve()
        if is_within(session.custody_log, evidence_root):
            raise SuiteError(
                f"refusing to write into the evidence directory: {session.custody_log} "
                f"is inside {evidence_root}"
            )

    exhibit = manifest.lookup_entry(entries, exhibit_path)
    custody.append_custody_row(
        session.custody_log,
        actor=session.actor,
        action=action,
        exhibit=exhibit,
        notes=notes,
    )
    return (
        f"logged {action.strip()} on {exhibit.relative_path} "
        f"({exhibit.sha256[:12]}…) -> {session.custody_log}"
    )


CUST0DIA_TOOL = Tool(
    name="cust0dia",
    summary="SHA-256 exhibit manifests, verification, chain of custody",
    run=_run_cust0dia,
    commands=(
        Command(
            name="show exhibits",
            usage="show exhibits",
            summary="list the exhibits in the active manifest",
            handler=_cmd_show_exhibits,
        ),
        Command(
            name="show log",
            usage="show log",
            summary="print the custody log",
            handler=_cmd_show_log,
        ),
        Command(
            name="log",
            usage="log <exhibit> <ACTION> [notes...]",
            summary="append a custody event (actor comes from `set actor`)",
            handler=_cmd_log,
        ),
    ),
)

# ---------------------------------------------------------------------------
# Shared guards for the output-writing tools below.
# ---------------------------------------------------------------------------


def _refuse_evidence_write(session: SessionContext, path: Path) -> None:
    """Refuse any output path that lands inside the session evidence tree.

    The suite's cardinal rule — never write into an evidence directory —
    is enforced per module as well (each core has its own refusal), but
    the console checks against the *session's* evidence directory too:
    a module scanning one directory must still not write into the tree
    the investigator declared as the case's evidence.
    """
    resolved = Path(path).expanduser().resolve()
    if session.evidence_dir is not None and is_within(resolved, session.evidence_dir):
        raise SuiteError(
            f"refusing to write into the evidence directory: {resolved} "
            f"is inside {session.evidence_dir}"
        )


def _session_output(session: SessionContext) -> Path:
    """The session output directory, or a guidance-rich error."""
    _require(session.output_dir is None, "output is not set (use: set output <dir>)")
    return session.output_dir


# ---------------------------------------------------------------------------
# timeline — multi-source CSV exports merged into one UTC exhibit timeline.
# ---------------------------------------------------------------------------


def _timeline_specs(sources_dir: Path, tz_pairs: list[str]):
    """Register every ``*.csv`` under ``sources_dir`` as a timeline source.

    The source name is the file stem; timezones come from trailing
    ``NAME=IANA_TZ`` arguments. Resolution reuses the CLI's own
    :func:`chr0nix.timeline.cli._resolve_sources`, so name validation,
    existence checks, and stray-timezone rejection are identical.
    """
    if not sources_dir.is_dir():
        raise SuiteError(f"sources directory does not exist: {sources_dir}")
    source_args = [
        f"{path.stem}={path}" for path in sorted(sources_dir.rglob("*.csv"))
    ]
    if not source_args:
        raise SuiteError(f"no source CSV files found under {sources_dir}")
    return timeline_cli._resolve_sources(source_args, tz_pairs)


def _timeline_build(session: SessionContext, sources_dir: Path, out_dir: Path, tz_pairs: list[str]) -> str:
    """The normalize → merge → render → manifest pipeline, in-process.

    Mirrors ``python -m chr0nix.timeline build`` step for step: the same
    output-location refusal runs before a single byte is written, all
    validation errors abort before any output file exists, and the same
    four files (timeline.csv, timeline.md, manifest.csv, manifest.json)
    land in the output directory.
    """
    specs = _timeline_specs(sources_dir, tz_pairs)
    timeline_cli._check_output_location(out_dir, [spec.path for spec in specs])
    _refuse_evidence_write(session, out_dir)

    events = []
    warnings: list[str] = []
    for spec in specs:
        source_events, source_warnings = timeline_normalize.load_source(spec)
        events.extend(source_events)
        warnings.extend(source_warnings)
    ordered = timeline_core.build_timeline(events)
    flagged = [event for event in ordered if event.flags]

    observed_at = timeline_utcnow()
    root, entries = timeline_manifest.build_manifest(
        [spec.path for spec in specs], observed_at
    )
    sources_table = [(spec.name, spec.path, spec.tz_name or "") for spec in specs]

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "timeline.csv": timeline_render.render_timeline_csv(ordered),
        "timeline.md": timeline_render.render_timeline_markdown(
            ordered, sources_table, observed_at
        ),
        "manifest.csv": timeline_manifest.render_manifest_csv(entries),
        "manifest.json": timeline_manifest.render_manifest_json(
            entries, root, tool=f"chr0nix {suite_version} (console)",
            generated_at=observed_at,
        ),
    }
    for filename, content in outputs.items():
        (out_dir / filename).write_text(content, encoding="utf-8")

    lines = [f"warning: {warning}" for warning in warnings]
    lines += [
        f"warning: {event.source} row {event.source_row} "
        f"({event.event_id}): {', '.join(event.flags)}"
        for event in flagged
    ]
    duplicates = timeline_core.count_duplicate_instants(ordered)
    lines.append(
        f"normalized {len(ordered)} events from {len(specs)} source(s); "
        f"{len(flagged)} flagged, {duplicates} sharing an exact UTC instant"
    )
    lines += [f"wrote {out_dir / filename}" for filename in timeline_cli.OUTPUT_FILES]
    return "\n".join(lines)


def _run_timeline(session: SessionContext) -> str:
    """Build the timeline from the session evidence tree into the output."""
    _require(session.evidence_dir is None, "evidence is not set (use: set evidence <dir>)")
    return _timeline_build(session, session.evidence_dir, _session_output(session), [])


def _cmd_timeline_build(session: SessionContext, args: list[str]) -> str:
    if not args:
        raise SuiteError("usage: build <sources-dir> [output-dir] [NAME=IANA_TZ ...]")
    sources_dir = Path(args[0]).expanduser()
    if not sources_dir.is_dir():
        raise SuiteError(f"sources directory does not exist: {sources_dir}")
    rest = args[1:]
    # The output directory is the first trailing argument that is not a
    # NAME=IANA_TZ pair; when omitted it falls back to the session output.
    out_dir: Path | None = None
    if rest and "=" not in rest[0]:
        out_dir = Path(rest.pop(0)).expanduser()
    if out_dir is None:
        out_dir = _session_output(session)
    return _timeline_build(session, sources_dir, out_dir, rest)


def _cmd_timeline_schema(session: SessionContext, args: list[str]) -> str:
    """Print the input CSV contract, as the CLI's ``schema`` does."""
    if args:
        raise SuiteError("usage: schema")
    lines = ["chr0nix input CSV schema", "=" * 24, "", "Required columns:"]
    lines += [f"  {column}" for column in timeline_schema.REQUIRED_COLUMNS]
    lines.append("")
    lines.append("Optional columns:")
    lines += [f"  {column}" for column in timeline_schema.OPTIONAL_COLUMNS]
    lines.append(
        "\nTimestamps must be ISO-8601. Naive values are interpreted in the"
        "\nsource's declared NAME=IANA_TZ; offset-aware values stand on their"
        "\nrecorded offset. A source with naive timestamps and no declared"
        "\ntimezone fails."
    )
    return "\n".join(lines)


TIMELINE_TOOL = Tool(
    name="timeline",
    summary="merge source CSV exports into one UTC exhibit timeline",
    run=_run_timeline,
    commands=(
        Command(
            name="build",
            usage="build <sources-dir> [output-dir] [NAME=IANA_TZ ...]",
            summary="build the timeline from a directory of source CSVs "
            "(output-dir defaults to `set output`)",
            handler=_cmd_timeline_build,
        ),
        Command(
            name="schema",
            usage="schema",
            summary="print the input CSV schema",
            handler=_cmd_timeline_schema,
        ),
    ),
)

# ---------------------------------------------------------------------------
# h4ndl3 — identifier research worksheets and a corroborated findings store.
# ---------------------------------------------------------------------------


def _h4ndl3_store(session: SessionContext, args: list[str], usage: str) -> str:
    """The store path argument, defaulting to ``<output>/findings.jsonl``.

    The conventional case layout keeps one store per output directory;
    an explicit path always wins, and anything that will be written is
    checked against the session evidence tree by the caller.
    """
    if len(args) > 1:
        raise SuiteError(f"usage: {usage}")
    if args:
        return args[0]
    return str(_session_output(session) / "findings.jsonl")


def _h4ndl3_existing_store(session: SessionContext, args: list[str], usage: str) -> str:
    """A store that must already exist (validate/report read it).

    Checked here so a typo'd path is a clean one-line console error
    rather than a ``FileNotFoundError`` escaping the core.
    """
    store = _h4ndl3_store(session, args, usage)
    if not Path(store).is_file():
        raise SuiteError(
            f"findings store does not exist: {store} "
            "(record one first with: add <store> <claim> ...)"
        )
    return store


def _run_h4ndl3(session: SessionContext) -> str:
    """Validate the case store and refresh its rendered report."""
    return _cmd_h4ndl3_report(session, [])


def _cmd_h4ndl3_worksheet(session: SessionContext, args: list[str]) -> str:
    """Write a research worksheet into the session output directory.

    Requires ``set output`` rather than falling back to a guessed
    location: a worksheet is case work product, and where case files land
    should always be a decision the investigator made, not a default
    they did not notice. The identifier is validated with h4ndl3's own
    strict rules (default type ``username``), never sanitized silently.
    """
    if not 1 <= len(args) <= 2:
        raise SuiteError("usage: worksheet <identifier> [username|email|domain]")
    identifier = args[0]
    id_type = args[1] if len(args) == 2 else "username"
    normalized = h4ndl3_identifiers.validate(identifier, id_type)
    out_dir = _session_output(session)
    _refuse_evidence_write(session, out_dir)
    store_path = out_dir / "findings.jsonl"
    content = h4ndl3_worksheet.render_worksheet(
        normalized,
        id_type,
        generated_at_utc=utc_now_iso(),
        store_path=str(store_path),
    )
    safe_name = "".join(
        char if char.isalnum() or char in "._-" else "_" for char in normalized
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"worksheet-{id_type}-{safe_name}.md"
    path.write_text(content, encoding="utf-8")
    return f"wrote {id_type} worksheet for {normalized!r} -> {path}"


def _cmd_h4ndl3_add(session: SessionContext, args: list[str]) -> str:
    """Append one finding to a store, through h4ndl3's strict validation.

    Every provenance field is required up front, exactly as the CLI's
    ``add`` requires its flags: :func:`h4ndl3.findings.new_finding`
    validates the record (URL schemes, UTC-only timestamps, confidence
    levels, no self-corroboration) and
    :func:`h4ndl3.findings.append_finding` re-validates on write, so a
    malformed finding fails before a byte is appended.
    """
    if len(args) < 5:
        raise SuiteError(
            "usage: add <store> <claim> <source-url> <retrieved-at> "
            "<low|medium|high> [corroborating-urls...]"
        )
    store, claim, source_url, retrieved_at, confidence = args[:5]
    corroborated_by = args[5:]
    _refuse_evidence_write(session, Path(store))
    # The conventional store lives in the session output directory;
    # create that directory (ours, never evidence) so the first finding
    # of a case lands without a manual mkdir. Explicit stores elsewhere
    # keep h4ndl3's own missing-parent refusal.
    if session.output_dir is not None:
        session.output_dir.mkdir(parents=True, exist_ok=True)
    finding = h4ndl3_findings.new_finding(
        claim=claim,
        source_url=source_url,
        retrieved_at_utc=retrieved_at,
        confidence=confidence,
        corroborated_by=corroborated_by,
    )
    h4ndl3_findings.append_finding(store, finding)
    return f"recorded finding in {store}"


def _cmd_h4ndl3_validate(session: SessionContext, args: list[str]) -> str:
    store = _h4ndl3_existing_store(session, args, "validate [store]")
    rows = h4ndl3_findings.load_store(store)
    return f"{store}: {len(rows)} finding(s), all valid"


def _cmd_h4ndl3_report(session: SessionContext, args: list[str]) -> str:
    """Render the store's report; save it when ``set output`` is set.

    With a session output directory the report is written there (never
    over the store it summarizes — the CLI's own output guard is reused);
    without one, the report is printed to the console instead.
    """
    store = _h4ndl3_existing_store(session, args, "report [store]")
    rows = h4ndl3_findings.load_store(store)
    content = h4ndl3_report.render_report(rows, generated_at_utc=utc_now_iso())
    if session.output_dir is None:
        return content.rstrip("\n")
    out_path = session.output_dir / "report.md"
    ensure_output_allowed(str(out_path), protected_files=(store,))
    _refuse_evidence_write(session, out_path)
    session.output_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return f"rendered {len(rows)} finding(s) -> {out_path}"


H4NDL3_TOOL = Tool(
    name="h4ndl3",
    summary="identifier research worksheets and corroborated findings",
    run=_run_h4ndl3,
    commands=(
        Command(
            name="worksheet",
            usage="worksheet <identifier> [username|email|domain]",
            summary="write a research worksheet into the output directory "
            "(default type: username; requires `set output`)",
            handler=_cmd_h4ndl3_worksheet,
        ),
        Command(
            name="add",
            usage="add <store> <claim> <source-url> <retrieved-at> "
            "<low|medium|high> [corroborating-urls...]",
            summary="append a validated finding to a store (quote the claim)",
            handler=_cmd_h4ndl3_add,
        ),
        Command(
            name="validate",
            usage="validate [store]",
            summary="re-validate a findings store "
            "(default: <output>/findings.jsonl)",
            handler=_cmd_h4ndl3_validate,
        ),
        Command(
            name="report",
            usage="report [store]",
            summary="render the findings report — saved as <output>/report.md "
            "when output is set, printed otherwise",
            handler=_cmd_h4ndl3_report,
        ),
    ),
)

# ---------------------------------------------------------------------------
# m3talex — image metadata extraction and anomaly flagging.
# ---------------------------------------------------------------------------


def _m3talex_outdir(session: SessionContext, args: list[str]) -> str:
    """The scan output directory: the explicit argument, else the session's."""
    if len(args) > 1:
        raise SuiteError("usage: scan <image-or-directory> [output-dir]")
    if args:
        _refuse_evidence_write(session, Path(args[0]))
        return args[0]
    out_dir = _session_output(session)
    _refuse_evidence_write(session, out_dir)
    return str(out_dir)


def _m3talex_extract(image_arg: str, outdir_arg: str) -> str:
    """One image in, one JSON report out — the CLI's ``extract``."""
    image = validate_input_file(image_arg)
    # For a single file the evidence directory is its parent: the report
    # must not land next to the exhibit, and ensure_output_dir refuses it.
    outdir = ensure_output_dir(outdir_arg, image.parent)
    record = analyze_image(image)
    report_path = write_json_report(record, outdir)
    file_info = record["file"]
    lines = [
        f"{file_info['path']} ({file_info['format']}, {file_info['size_bytes']} bytes)",
        f"sha256: {file_info['sha256']}",
    ]
    if record["findings"]:
        lines += [
            f"  [{finding['confidence']:>6}] {finding['id']}: {finding['observation']}"
            for finding in record["findings"]
        ]
    else:
        lines.append("  no anomalies flagged")
    lines += [f"  note: {note}" for note in record["notes"]]
    lines.append(f"report: {report_path}")
    return "\n".join(lines)


def _m3talex_batch(dir_arg: str, outdir_arg: str) -> str:
    """A directory in, the full artifact set out — the CLI's ``batch``.

    Every discovered image is hashed into the manifest even when it
    proves unparseable, and one corrupt file warns rather than sinking
    the batch — the same policy as the CLI, with the warnings returned
    in the display text instead of going to stderr.
    """
    root = validate_input_dir(dir_arg)
    outdir = ensure_output_dir(outdir_arg, root)
    images = iter_images(root)
    if not images:
        raise M3talexError(f"no JPEG/PNG images found under {root}")

    hashed_at = m3talex_utc_now_iso()  # one honest timestamp for the batch
    records: list[dict] = []
    manifest_entries: list[dict] = []
    skipped: list[str] = []
    for image in images:
        manifest_entries.append(manifest_entry(image, root, hashed_at))
        try:
            records.append(analyze_image(image, root))
        except M3talexError as exc:
            skipped.append(f"warning: skipped {image.relative_to(root)}: {exc}")

    written = write_batch_outputs(records, manifest_entries, outdir, root)
    total_findings = sum(len(record["findings"]) for record in records)
    lines = skipped
    lines.append(
        f"analyzed {len(records)} image(s), {total_findings} finding(s)"
        + (f", {len(skipped)} file(s) skipped" if skipped else "")
    )
    lines.append(f"batch report: {written['markdown']}")
    lines.append(f"manifests:    {written['manifest_csv']}, {written['manifest_json']}")
    lines.append(f"JSON reports: {outdir}")
    return "\n".join(lines)


def _run_m3talex(session: SessionContext) -> str:
    """Batch-scan the session evidence tree into the session output."""
    _require(session.evidence_dir is None, "evidence is not set (use: set evidence <dir>)")
    return _m3talex_batch(str(session.evidence_dir), _m3talex_outdir(session, []))


def _cmd_m3talex_scan(session: SessionContext, args: list[str]) -> str:
    """Scan one image or a whole directory, as the CLI distinguishes them."""
    if not args:
        raise SuiteError("usage: scan <image-or-directory> [output-dir]")
    target, rest = args[0], args[1:]
    outdir_arg = _m3talex_outdir(session, rest)
    if Path(target).expanduser().is_dir():
        return _m3talex_batch(target, outdir_arg)
    return _m3talex_extract(target, outdir_arg)


M3TALEX_TOOL = Tool(
    name="m3talex",
    summary="extract and flag image metadata (JPEG EXIF, PNG chunks)",
    run=_run_m3talex,
    commands=(
        Command(
            name="scan",
            usage="scan <image-or-directory> [output-dir]",
            summary="one image -> a JSON report; a directory -> the full "
            "batch artifact set (output-dir defaults to `set output`)",
            handler=_cmd_m3talex_scan,
        ),
    ),
)

# ---------------------------------------------------------------------------
# casework — case workspaces: cases, entities, and the associations
# between them.
# ---------------------------------------------------------------------------


def _session_workspace(session: SessionContext) -> Path:
    """The session workspace, confirmed initialized, or a guidance error."""
    _require(session.workspace is None, "workspace is not set (use: set workspace <dir>)")
    return casework_workspace.require_workspace(session.workspace)


def _casework_actor(session: SessionContext) -> str:
    """The session actor, required for anything that appends an event."""
    _require(session.actor is None, "actor is not set (use: set actor <name>)")
    return session.actor


def _casework_case_id(session: SessionContext, args: list[str], usage: str) -> str:
    """The case-id argument, falling back to the session's active case.

    Only the commands that declare ``[case-id]`` optional go through
    here; commands with a required ``<case-id>`` validate their own
    arguments, so a stray word can never be silently reinterpreted as
    "the active case".
    """
    if len(args) > 1:
        raise SuiteError(f"usage: {usage}")
    if args:
        return args[0]
    if session.active_case is None:
        raise SuiteError(
            "no case given and no active case "
            "(use: open <case-id>, or pass a case-id)"
        )
    return session.active_case


def _cmd_casework_init(session: SessionContext, args: list[str]) -> str:
    if args:
        raise SuiteError("usage: init")
    _require(session.workspace is None, "workspace is not set (use: set workspace <dir>)")
    written = casework_workspace.init_workspace(session.workspace)
    lines = [f"initialized casework workspace at {session.workspace}"]
    lines += [f"wrote {path}" for path in written]
    return "\n".join(lines)


def _cmd_casework_new(session: SessionContext, args: list[str]) -> str:
    if len(args) < 2:
        raise SuiteError("usage: new <case-id> <title...>")
    workspace = _session_workspace(session)
    case = casework_cases.create_case(
        workspace, args[0], " ".join(args[1:]), _casework_actor(session)
    )
    session.active_case = case.id
    return f"created case {case.id} (draft) — active case -> {case.id}"


def _casework_cases_listing(session: SessionContext) -> str:
    """The case table shared by the ``cases`` command and ``run``."""
    workspace = _session_workspace(session)
    all_cases = casework_cases.list_cases(workspace)
    if not all_cases:
        return "no cases yet (use: new <case-id> <title...>)"
    links = casework_entities.read_links(workspace)
    lines = [f"{'case':<20}{'status':<11}{'cats':>5}{'links':>6}  title"]
    for case in all_cases:
        count = sum(
            1
            for link in links
            if link.case_id == case.id
            or (link.entity_type == "case" and link.entity_id == case.id)
        )
        lines.append(
            f"{case.id:<20}{case.status:<11}{len(case.categories):>5}"
            f"{count:>6}  {case.title}"
        )
    return "\n".join(lines)


def _cmd_casework_cases(session: SessionContext, args: list[str]) -> str:
    if args:
        raise SuiteError("usage: cases")
    return _casework_cases_listing(session)


def _cmd_casework_open(session: SessionContext, args: list[str]) -> str:
    if len(args) != 1:
        raise SuiteError("usage: open <case-id>")
    workspace = _session_workspace(session)
    case = casework_cases.load_case(workspace, args[0])
    session.active_case = case.id
    return f"active case -> {case.id} ({case.status}: {case.title})"


def _cmd_casework_status(session: SessionContext, args: list[str]) -> str:
    if len(args) != 2:
        raise SuiteError("usage: status <case-id> <new-status>")
    workspace = _session_workspace(session)
    case = casework_cases.transition_status(
        workspace, args[0], args[1], _casework_actor(session)
    )
    suffix = f" (closed {case.closed_utc})" if case.closed_utc else ""
    return f"{case.id}: status -> {case.status}{suffix}"


def _cmd_casework_categorize(session: SessionContext, args: list[str]) -> str:
    if len(args) != 2:
        raise SuiteError("usage: categorize <case-id> <category-id>")
    workspace = _session_workspace(session)
    case, changed = casework_cases.attach_category(workspace, args[0], args[1])
    verb = "categorized" if changed else "already categorized"
    return f"{case.id}: {verb} as {args[1]}"


def _cmd_casework_classify(session: SessionContext, args: list[str]) -> str:
    if len(args) != 2:
        raise SuiteError("usage: classify <case-id> <taxonomy-path>")
    workspace = _session_workspace(session)
    case, changed = casework_cases.attach_taxonomy(workspace, args[0], args[1])
    verb = "classified" if changed else "already classified"
    return f"{case.id}: {verb} under {args[1]}"


def _cmd_casework_link(session: SessionContext, args: list[str]) -> str:
    if len(args) < 3:
        raise SuiteError(
            "usage: link <case-id> subject|vehicle|case <entity-id> [role...]"
        )
    workspace = _session_workspace(session)
    case_id, entity_type, entity_id = args[:3]
    role = " ".join(args[3:])
    registered = casework_entities.append_link(
        workspace, case_id, entity_type, entity_id, role
    )
    message = f"linked {case_id} -> {entity_type} {entity_id}"
    if registered:
        message += f" (auto-registered {entity_type} {entity_id})"
    return message


def _cmd_casework_links(session: SessionContext, args: list[str]) -> str:
    workspace = _session_workspace(session)
    case_id = _casework_case_id(session, args, "links [case-id]")
    found = casework_entities.associations(workspace, case_id)
    if not found:
        return f"{case_id}: no associated cases"
    lines = [f"associations for {case_id}:"]
    lines += [
        f"  {association.case_id:<20}{'; '.join(association.reasons)}"
        for association in found
    ]
    return "\n".join(lines)


def _cmd_casework_event(session: SessionContext, args: list[str]) -> str:
    if len(args) < 3:
        raise SuiteError("usage: event <case-id> <event-type> <detail...>")
    workspace = _session_workspace(session)
    casework_cases.append_event(
        workspace, args[0], actor=_casework_actor(session),
        event_type=args[1], detail=" ".join(args[2:]),
    )
    return f"event logged on {args[0]} ({args[1]})"


def _cmd_casework_synopsis(session: SessionContext, args: list[str]) -> str:
    workspace = _session_workspace(session)
    case_id = _casework_case_id(session, args, "synopsis [case-id]")
    path = casework_synopsis.regenerate_synopsis(workspace, case_id)
    content = path.read_text(encoding="utf-8").rstrip("\n")
    return f"wrote {path}\n{content}"


def _cmd_casework_show(session: SessionContext, args: list[str]) -> str:
    workspace = _session_workspace(session)
    case_id = _casework_case_id(session, args, "show case [case-id]")
    case = casework_cases.load_case(workspace, case_id)
    synopsis_path = casework_workspace.case_dir(workspace, case.id) / "synopsis.txt"
    synopsis = str(synopsis_path) if synopsis_path.is_file() else "(not generated yet)"
    lines = [
        f"id:             {case.id}",
        f"title:          {case.title}",
        f"status:         {case.status}",
        f"categories:     {', '.join(case.categories) or '(none)'}",
        f"taxonomy_paths: {', '.join(case.taxonomy_paths) or '(none)'}",
        f"opened_utc:     {case.opened_utc}",
        f"closed_utc:     {case.closed_utc or '(open)'}",
        f"synopsis:       {synopsis}",
    ]
    return "\n".join(lines)


def _run_casework(session: SessionContext) -> str:
    """The case table plus a status-count summary of the whole workspace."""
    listing = _casework_cases_listing(session)
    workspace = _session_workspace(session)
    all_cases = casework_cases.list_cases(workspace)
    counts = {status: 0 for status in casework_cases.STATUS_ORDER}
    for case in all_cases:
        counts[case.status] += 1
    breakdown = ", ".join(
        f"{counts[status]} {status}"
        for status in casework_cases.STATUS_ORDER
        if counts[status]
    )
    summary = f"workspace: {len(all_cases)} case(s)"
    if breakdown:
        summary += f" — {breakdown}"
    return f"{listing}\n{summary}"


CASEWORK_TOOL = Tool(
    name="casework",
    summary="case workspaces: cases, entities, and associations",
    run=_run_casework,
    commands=(
        Command(
            name="init",
            usage="init",
            summary="create the workspace layout at the session workspace "
            "(with starter config)",
            handler=_cmd_casework_init,
        ),
        Command(
            name="new",
            usage="new <case-id> <title...>",
            summary="create a case (status draft) and make it the active case",
            handler=_cmd_casework_new,
        ),
        Command(
            name="cases",
            usage="cases",
            summary="list all cases: id, status, category/link counts, title",
            handler=_cmd_casework_cases,
        ),
        Command(
            name="open",
            usage="open <case-id>",
            summary="make a case the active case (default for links, "
            "synopsis, show case)",
            handler=_cmd_casework_open,
        ),
        Command(
            name="status",
            usage="status <case-id> <new-status>",
            summary="advance a case's status (draft -> pending -> submitted "
            "-> referred -> closed)",
            handler=_cmd_casework_status,
        ),
        Command(
            name="categorize",
            usage="categorize <case-id> <category-id>",
            summary="attach a category defined in config/categories.csv",
            handler=_cmd_casework_categorize,
        ),
        Command(
            name="classify",
            usage="classify <case-id> <taxonomy-path>",
            summary="attach a taxonomy path defined in config/taxonomy.csv",
            handler=_cmd_casework_classify,
        ),
        Command(
            name="link",
            usage="link <case-id> subject|vehicle|case <entity-id> [role...]",
            summary="associate an entity with a case (unknown subjects and "
            "vehicles are auto-registered)",
            handler=_cmd_casework_link,
        ),
        Command(
            name="links",
            usage="links [case-id]",
            summary="show cases associated with a case, with the reason "
            "(shared entity / direct link)",
            handler=_cmd_casework_links,
        ),
        Command(
            name="event",
            usage="event <case-id> <event-type> <detail...>",
            summary="append an event to the case's append-only log "
            "(actor comes from `set actor`)",
            handler=_cmd_casework_event,
        ),
        Command(
            name="synopsis",
            usage="synopsis [case-id]",
            summary="regenerate and print the case's synopsis.txt",
            handler=_cmd_casework_synopsis,
        ),
        # Named "show case" rather than "show" so the core `show tools`
        # / `show options` keep working while casework is active — the
        # same longest-prefix pattern as cust0dia's "show exhibits".
        Command(
            name="show case",
            usage="show case [case-id]",
            summary="show a case's case.json fields and synopsis path",
            handler=_cmd_casework_show,
        ),
    ),
)

#: The tools the console can run, in display order. This tuple is the
#: entire plugin mechanism — see the module docstring for why it is a
#: static list and not a discovery system.
REGISTRY: tuple[Tool, ...] = (
    CUST0DIA_TOOL,
    TIMELINE_TOOL,
    H4NDL3_TOOL,
    M3TALEX_TOOL,
    CASEWORK_TOOL,
)


def lookup_tool(name: str) -> Tool:
    """Return the registered tool called ``name`` or raise."""
    for tool in REGISTRY:
        if tool.name == name:
            return tool
    known = ", ".join(tool.name for tool in REGISTRY)
    raise SuiteError(f"unknown tool {name!r}; registered tools: {known}")
