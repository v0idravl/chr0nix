"""Tool registry: the console's plugin surface.

A *tool* is one investigative utility exposed through the console.
cust0dia itself (manifest / verify / custody) is the first entry;
future suite utilities are added by defining their handlers here-shaped
modules and appending one line to :data:`REGISTRY`.

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
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cust0dia import custody, manifest, verify
from cust0dia.paths import is_within

from ..errors import SuiteError
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

#: The tools the console can run, in display order. This tuple is the
#: entire plugin mechanism — see the module docstring for why it is a
#: static list and not a discovery system.
REGISTRY: tuple[Tool, ...] = (CUST0DIA_TOOL,)


def lookup_tool(name: str) -> Tool:
    """Return the registered tool called ``name`` or raise."""
    for tool in REGISTRY:
        if tool.name == name:
            return tool
    known = ", ".join(tool.name for tool in REGISTRY)
    raise SuiteError(f"unknown tool {name!r}; registered tools: {known}")
