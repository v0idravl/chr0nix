"""Case records: case.json lifecycle, the status chain, and event logs.

A case is one directory under ``cases/`` holding three files:

- ``case.json`` — the mutable record: id, title, status, assigned
  categories and taxonomy paths, opened/closed timestamps. Written with
  stdlib ``json``, ``indent=2``, and a fixed key order so consecutive
  versions diff line-locally.
- ``events.csv`` — the append-only event log
  (``timestamp_utc,actor,event_type,detail``), written through
  :func:`chr0nix.casework.workspace.append_csv_row` with exactly the
  custody.py discipline: header validated before append, control
  characters rejected, one event per line.
- ``synopsis.txt`` — generated output, owned by
  :mod:`chr0nix.casework.synopsis`, never written here.

The status chain is ``draft → pending → submitted → referred →
closed``. Transitions may skip forward (a case opened and submitted the
same day need not visit ``pending``) but never move backward, and
``closed`` is terminal: a closed case is a record of fact. Closing a
case stamps ``closed_utc`` once. Every transition is logged to
``events.csv`` as a ``status-changed`` event, so the JSON shows *where*
a case is and the log shows *how it got there*.

Categories and taxonomy paths are validated against the workspace
config at assignment time: a case can never reference a vocabulary term
the config does not define. Attachment is idempotent — re-attaching an
existing term is a no-op, not a duplicate.
"""

import csv
import json
from dataclasses import dataclass, replace
from pathlib import Path

from cust0dia import timeutil

from . import CaseworkError
from .workspace import (
    append_csv_row,
    case_dir,
    clean_field,
    read_categories,
    read_taxonomy,
)

#: The status chain, in forward order. ``closed`` is terminal.
STATUS_ORDER = ("draft", "pending", "submitted", "referred", "closed")

#: cases/<case-id>/events.csv columns, in canonical order.
EVENT_FIELDS = ("timestamp_utc", "actor", "event_type", "detail")


@dataclass(frozen=True)
class Case:
    """The case.json record of one case.

    Frozen because a loaded case is a snapshot of fact; every change is
    a new value written back to disk in full, never an in-place
    mutation of a record another reader may hold.
    """

    id: str
    title: str
    status: str
    categories: tuple[str, ...]
    taxonomy_paths: tuple[str, ...]
    opened_utc: str
    closed_utc: str | None

    def as_dict(self) -> dict:
        """JSON-object form, in stable key order for diff-friendly writes."""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "categories": list(self.categories),
            "taxonomy_paths": list(self.taxonomy_paths),
            "opened_utc": self.opened_utc,
            "closed_utc": self.closed_utc,
        }


@dataclass(frozen=True)
class Event:
    """One row of a case's events.csv."""

    timestamp_utc: str
    actor: str
    event_type: str
    detail: str


def create_case(workspace: Path, case_id: str, title: str, actor: str) -> Case:
    """Create a case in status ``draft`` and log its ``case-opened`` event."""
    directory = case_dir(workspace, case_id)
    if directory.exists():
        raise CaseworkError(f"case {case_id!r} already exists in this workspace")
    title = clean_field(title, "title", required=True)
    case = Case(
        id=case_id,
        title=title,
        status="draft",
        categories=(),
        taxonomy_paths=(),
        opened_utc=timeutil.utc_now(),
        closed_utc=None,
    )
    directory.mkdir(parents=True)
    save_case(workspace, case)
    append_event(
        workspace, case.id, actor=actor, event_type="case-opened",
        detail=f"case opened: {title}",
    )
    return case


def load_case(workspace: Path, case_id: str) -> Case:
    """Read and defensively validate cases/<case-id>/case.json.

    case.json is hand-editable in principle, so it is parsed as
    untrusted input: every required key, type, and status value is
    checked before the record is used.
    """
    path = case_dir(workspace, case_id) / "case.json"
    if not path.is_file():
        raise CaseworkError(f"unknown case {case_id!r} (no cases/{case_id}/case.json)")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseworkError(f"case file {path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise CaseworkError(f"case file {path} must be a JSON object")
    for key in ("id", "title", "status", "categories", "taxonomy_paths", "opened_utc"):
        if key not in document:
            raise CaseworkError(f"case file {path} is missing key {key!r}")
    status = document["status"]
    if status not in STATUS_ORDER:
        raise CaseworkError(
            f"case file {path} has unknown status {status!r}; "
            f"expected one of: {', '.join(STATUS_ORDER)}"
        )
    for key in ("categories", "taxonomy_paths"):
        value = document[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CaseworkError(f"case file {path}: {key!r} must be a list of strings")
    closed_utc = document.get("closed_utc")
    if closed_utc is not None and not isinstance(closed_utc, str):
        raise CaseworkError(f"case file {path}: 'closed_utc' must be a string or null")
    return Case(
        id=str(document["id"]),
        title=str(document["title"]),
        status=status,
        categories=tuple(document["categories"]),
        taxonomy_paths=tuple(document["taxonomy_paths"]),
        opened_utc=str(document["opened_utc"]),
        closed_utc=closed_utc,
    )


def save_case(workspace: Path, case: Case) -> None:
    """Write case.json: indent=2, stable key order, trailing newline."""
    path = case_dir(workspace, case.id) / "case.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(case.as_dict(), handle, indent=2)
        handle.write("\n")


def list_cases(workspace: Path) -> list[Case]:
    """Every case in the workspace, sorted by id for stable listings."""
    cases_root = workspace / "cases"
    return [
        load_case(workspace, path.name)
        for path in sorted(cases_root.iterdir())
        if path.is_dir()
    ]


def transition_status(
    workspace: Path, case_id: str, new_status: str, actor: str
) -> Case:
    """Move a case forward along the status chain; log the transition.

    Backward and lateral moves are rejected, ``closed`` is terminal,
    and reaching ``closed`` stamps ``closed_utc``. The transition is
    appended to events.csv *after* the JSON is saved, so the log never
    claims a state the record does not show.
    """
    case = load_case(workspace, case_id)
    if new_status not in STATUS_ORDER:
        raise CaseworkError(
            f"unknown status {new_status!r}; expected one of: {', '.join(STATUS_ORDER)}"
        )
    if case.status == "closed":
        raise CaseworkError(
            f"case {case.id} is closed — no further status transitions are allowed"
        )
    if STATUS_ORDER.index(new_status) <= STATUS_ORDER.index(case.status):
        raise CaseworkError(
            f"invalid status transition {case.status} -> {new_status}: "
            f"the chain only moves forward ({' → '.join(STATUS_ORDER)})"
        )
    updated = replace(
        case,
        status=new_status,
        closed_utc=timeutil.utc_now() if new_status == "closed" else None,
    )
    save_case(workspace, updated)
    append_event(
        workspace, case.id, actor=actor, event_type="status-changed",
        detail=f"{case.status} -> {new_status}",
    )
    return updated


def attach_category(workspace: Path, case_id: str, category_id: str) -> tuple[Case, bool]:
    """Attach a config-defined category to a case; return ``(case, changed)``.

    Idempotent: attaching an already-attached category returns the case
    unchanged with ``changed=False``. Categories are stored sorted so
    case.json diffs stay line-local.
    """
    known = {category.id: category for category in read_categories(workspace)}
    if category_id not in known:
        defined = ", ".join(sorted(known)) or "(none defined)"
        raise CaseworkError(
            f"unknown category {category_id!r}; defined categories: {defined} "
            "(add rows to config/categories.csv)"
        )
    case = load_case(workspace, case_id)
    if category_id in case.categories:
        return case, False
    updated = replace(case, categories=tuple(sorted(case.categories + (category_id,))))
    save_case(workspace, updated)
    return updated, True


def attach_taxonomy(workspace: Path, case_id: str, path: str) -> tuple[Case, bool]:
    """Attach a config-defined taxonomy path; return ``(case, changed)``.

    Strict membership: the path must appear in taxonomy.csv *verbatim*.
    Being a prefix-parent of a listed path does not make a node
    assignable — intermediate nodes must be listed explicitly to be
    used. Idempotent, like :func:`attach_category`.
    """
    known = {entry.path: entry for entry in read_taxonomy(workspace)}
    if path not in known:
        defined = ", ".join(sorted(known)) or "(none defined)"
        raise CaseworkError(
            f"unknown taxonomy path {path!r}; defined paths: {defined} "
            "(add rows to config/taxonomy.csv)"
        )
    case = load_case(workspace, case_id)
    if path in case.taxonomy_paths:
        return case, False
    updated = replace(
        case, taxonomy_paths=tuple(sorted(case.taxonomy_paths + (path,)))
    )
    save_case(workspace, updated)
    return updated, True


def append_event(
    workspace: Path, case_id: str, *, actor: str, event_type: str, detail: str
) -> None:
    """Append one event to cases/<case-id>/events.csv.

    The case must exist (events are never logged against nothing), and
    every free-text field goes through the custody.py control-character
    rule before the row is appended.
    """
    load_case(workspace, case_id)
    row = [
        timeutil.utc_now(),
        clean_field(actor, "actor", required=True),
        clean_field(event_type, "event_type", required=True),
        clean_field(detail, "detail", required=True),
    ]
    append_csv_row(case_dir(workspace, case_id) / "events.csv", EVENT_FIELDS, row)


def read_events(workspace: Path, case_id: str) -> list[Event]:
    """Read a case's events.csv defensively, in recorded (append) order."""
    path = case_dir(workspace, case_id) / "events.csv"
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise CaseworkError(f"event log {path} is empty") from None
        if tuple(header) != EVENT_FIELDS:
            raise CaseworkError(
                f"event log {path} has unexpected header {header!r}; "
                f"expected {list(EVENT_FIELDS)!r}"
            )
        events = []
        for line_no, row in enumerate(reader, start=2):
            if len(row) != len(EVENT_FIELDS):
                raise CaseworkError(
                    f"event log {path}, line {line_no}: "
                    f"expected {len(EVENT_FIELDS)} fields, got {len(row)}"
                )
            events.append(Event(*row))
    return events
