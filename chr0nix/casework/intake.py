"""Evidence intake: the workspace inbox and filing into cases.

The inbox is the suite's answer to "screenshots and exports get dumped
in a folder": ``<workspace>/inbox/`` is a drop zone where anything
lands — phone exports, screenshots, PDFs — and ``file`` moves items
into a case's ``exhibits/`` directory with the full evidence discipline
applied at filing time:

1. the case's exhibits are re-manifested with cust0dia (both CSV and
   JSON), so the new bytes are hashed into the record immediately;
2. one custody row per filed item is appended to the case's
   ``custody.csv`` — ``COLLECTED``, anchored to the item's fresh
   SHA-256 from that manifest;
3. an ``evidence-filed`` event lands in the case's append-only log.

Filing *moves* files (inbox → case exhibits) rather than copying: an
item is either unfiled or filed, never both, so there is exactly one
authoritative copy of every byte. The inbox itself is never manifested
— it is a staging area, not evidence, and only becomes evidence at the
moment of filing, which is also the moment hashing starts.

Two safety rules:

- Names given to ``file`` are resolved and containment-checked against
  the inbox; ``..`` and absolute paths are rejected (the same
  path-traversal discipline as manifest parsing).
- The manifest is written to the *case* directory, never inside
  ``exhibits/`` — cust0dia's own output-outside-evidence rule, kept.
"""

import shutil
from pathlib import Path

from cust0dia import custody, manifest

from . import CaseworkError
from .cases import append_event, load_case
from .workspace import case_dir, clean_field

#: cases/<case-id>/custody.csv lives beside events.csv; both are
#: append-only records of what happened to the case's evidence.
CUSTODY_LOG_NAME = "custody.csv"


def inbox_dir(workspace: Path) -> Path:
    """The workspace inbox, created on first use.

    Older workspaces predate the inbox; creating it lazily keeps them
    valid without a migration step.
    """
    directory = workspace / "inbox"
    directory.mkdir(exist_ok=True)
    return directory


def list_inbox(workspace: Path) -> list[Path]:
    """Every regular file in the inbox, relative paths, sorted.

    Sorted so listings (and therefore any filing order derived from
    them) are deterministic.
    """
    root = inbox_dir(workspace)
    return sorted(
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
    )


def exhibits_dir(workspace: Path, case_id: str) -> Path:
    """The case's exhibits directory, created on first use."""
    directory = case_dir(workspace, case_id) / "exhibits"
    directory.mkdir(exist_ok=True)
    return directory


def _resolve_inbox_item(workspace: Path, name: str) -> Path:
    """Resolve one operator-supplied inbox name, containment-checked.

    The name is untrusted input: it must land inside the inbox and name
    an existing regular file. Anything else — ``..``, absolute paths,
    directories — is rejected rather than sanitized.
    """
    root = inbox_dir(workspace).resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        raise CaseworkError(f"inbox item {name!r} escapes the inbox")
    if not candidate.is_file():
        raise CaseworkError(f"no such inbox item: {name!r}")
    return candidate


def file_evidence(
    workspace: Path,
    case_id: str,
    names: list[str],
    *,
    actor: str,
) -> list[str]:
    """File inbox items into a case; return the filed relative paths.

    An empty ``names`` files everything currently in the inbox. Every
    filed item is moved into ``cases/<id>/exhibits/``, the exhibits are
    re-manifested, a COLLECTED custody row is appended per item, and a
    single ``evidence-filed`` event summarizes the batch in the case
    log.
    """
    load_case(workspace, case_id)  # never file into a case that does not exist
    actor = clean_field(actor, "actor", required=True)
    if not names:
        names = [str(path) for path in list_inbox(workspace)]
        if not names:
            raise CaseworkError("the inbox is empty — nothing to file")

    exhibits = exhibits_dir(workspace, case_id)
    filed: list[str] = []
    for name in names:
        source = _resolve_inbox_item(workspace, name)
        destination = exhibits / Path(name).name
        if destination.exists():
            raise CaseworkError(
                f"refusing to file {name!r}: {destination.name} already exists "
                f"in {case_id}'s exhibits — rename the inbox item first"
            )
        shutil.move(str(source), str(destination))
        filed.append(destination.name)

    # Re-manifest the whole exhibits directory so the record reflects
    # what is on disk now, not a delta from memory.
    entries = manifest.build_manifest(exhibits)
    case_directory = case_dir(workspace, case_id)
    manifest.write_csv(entries, case_directory / "manifest.csv")
    manifest.write_json(entries, exhibits, case_directory / "manifest.json")

    for name in filed:
        exhibit = manifest.lookup_entry(entries, name)
        custody.append_custody_row(
            case_directory / CUSTODY_LOG_NAME,
            actor=actor,
            action="COLLECTED",
            exhibit=exhibit,
            notes="filed from workspace inbox",
        )

    append_event(
        workspace, case_id, actor=actor, event_type="evidence-filed",
        detail=f"filed {len(filed)} item(s) from inbox: {', '.join(filed)}",
    )
    return filed
