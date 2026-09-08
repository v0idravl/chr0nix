"""Entities and associations: subjects, vehicles, and the links between cases.

Three CSVs under ``entities/`` hold what connects cases to the world
and to each other:

- ``subjects.csv`` — known subjects (``subject_id,nickname,descriptor_summary``)
- ``vehicles.csv`` — known vehicles (``vehicle_id,plate,description``)
- ``links.csv`` — append-only associations
  (``case_id,entity_type,entity_id,role,notes``), where ``entity_type``
  is ``subject``, ``vehicle``, or ``case``

``links.csv`` follows the custody.py append-only pattern via
:func:`chr0nix.casework.workspace.append_csv_row`: the set of
associations is a record of what the investigator knew, and records
only ever grow.

Two association kinds are computed from it, both surfaced by the
``links`` command and the generated synopsis:

- **Shared entities** — two cases linked to the same ``subject_id`` or
  ``vehicle_id`` are associated ("shared subject subj-001"). This is
  how repeat-offender and vehicle-reuse patterns emerge without anyone
  declaring them.
- **Direct case→case links** — rows with ``entity_type=case``. These
  are treated symmetrically: a link recorded from either side is an
  association of the pair, because the investigator asserted the
  *relationship*, not a direction.

Linking is one step: naming an unknown subject or vehicle id
auto-registers it in the matching registry (with the role/notes as its
initial descriptor), so the registries grow as a by-product of real
casework rather than as a separate bookkeeping chore. Case links are
stricter — both cases must already exist, and a case cannot be linked
to itself.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from . import CaseworkError, cases
from .workspace import append_csv_row, clean_field, validate_slug

#: entities/subjects.csv columns, in canonical order.
SUBJECT_FIELDS = ("subject_id", "nickname", "descriptor_summary")

#: entities/vehicles.csv columns, in canonical order.
VEHICLE_FIELDS = ("vehicle_id", "plate", "description")

#: entities/links.csv columns, in canonical order.
LINK_FIELDS = ("case_id", "entity_type", "entity_id", "role", "notes")

#: The entity types a link row may name.
ENTITY_TYPES = ("subject", "vehicle", "case")


@dataclass(frozen=True)
class Subject:
    """One row of entities/subjects.csv."""

    subject_id: str
    nickname: str
    descriptor_summary: str


@dataclass(frozen=True)
class Vehicle:
    """One row of entities/vehicles.csv."""

    vehicle_id: str
    plate: str
    description: str


@dataclass(frozen=True)
class Link:
    """One row of entities/links.csv."""

    case_id: str
    entity_type: str
    entity_id: str
    role: str
    notes: str


@dataclass(frozen=True)
class Association:
    """One case associated with another, with every reason it is.

    ``reasons`` is a sorted tuple of human-readable strings such as
    ``"shared subject subj-001"`` or ``"direct link"`` — a pair can be
    associated for several reasons at once, and all of them are shown.
    """

    case_id: str
    title: str
    reasons: tuple[str, ...]


def append_link(
    workspace: Path,
    case_id: str,
    entity_type: str,
    entity_id: str,
    role: str = "",
    notes: str = "",
) -> bool:
    """Append one link row; return True if an entity was auto-registered.

    The case the link hangs off must exist. Subject and vehicle ids
    that are new are auto-registered into their registry file with the
    role (or notes) as the initial descriptor. Case links require the
    target case to exist and forbid self-links.
    """
    cases.load_case(workspace, case_id)
    if entity_type not in ENTITY_TYPES:
        raise CaseworkError(
            f"unknown entity type {entity_type!r}; expected one of: {', '.join(ENTITY_TYPES)}"
        )
    entity_id = validate_slug(entity_id, f"{entity_type} id")
    role = clean_field(role, "role", required=False)
    notes = clean_field(notes, "notes", required=False)

    registered = False
    if entity_type == "subject":
        if entity_id not in {s.subject_id for s in read_subjects(workspace)}:
            descriptor = role or notes or f"auto-registered from {case_id}"
            append_csv_row(
                workspace / "entities" / "subjects.csv",
                SUBJECT_FIELDS,
                [entity_id, entity_id, descriptor],
            )
            registered = True
    elif entity_type == "vehicle":
        if entity_id not in {v.vehicle_id for v in read_vehicles(workspace)}:
            description = role or notes or f"auto-registered from {case_id}"
            append_csv_row(
                workspace / "entities" / "vehicles.csv",
                VEHICLE_FIELDS,
                [entity_id, "", description],
            )
            registered = True
    else:  # entity_type == "case"
        if entity_id == case_id:
            raise CaseworkError("a case cannot be linked to itself")
        cases.load_case(workspace, entity_id)

    append_csv_row(
        workspace / "entities" / "links.csv",
        LINK_FIELDS,
        [case_id, entity_type, entity_id, role, notes],
    )
    return registered


def associations(workspace: Path, case_id: str) -> list[Association]:
    """Every case associated with ``case_id``, sorted, with all reasons.

    Pure computation over links.csv: nothing is stored, so the view can
    never disagree with the record. A hand-deleted target case is
    reported as ``(case file missing)`` rather than crashing the view —
    the link row is still a fact, even if its target is gone.
    """
    cases.load_case(workspace, case_id)
    links = read_links(workspace)

    entities_by_case: dict[str, set[tuple[str, str]]] = {}
    direct: dict[str, set[str]] = {}
    for link in links:
        if link.entity_type in ("subject", "vehicle"):
            entities_by_case.setdefault(link.case_id, set()).add(
                (link.entity_type, link.entity_id)
            )
        else:  # direct case->case links are symmetric associations
            direct.setdefault(link.case_id, set()).add(link.entity_id)
            direct.setdefault(link.entity_id, set()).add(link.case_id)

    mine = entities_by_case.get(case_id, set())
    reasons: dict[str, set[str]] = {}
    for other, theirs in entities_by_case.items():
        if other == case_id:
            continue
        for entity_type, entity_id in sorted(mine & theirs):
            reasons.setdefault(other, set()).add(f"shared {entity_type} {entity_id}")
    for other in direct.get(case_id, set()):
        if other != case_id:
            reasons.setdefault(other, set()).add("direct link")

    found: list[Association] = []
    for other in sorted(reasons):
        try:
            title = cases.load_case(workspace, other).title
        except CaseworkError:
            title = "(case file missing)"
        found.append(Association(other, title, tuple(sorted(reasons[other]))))
    return found


def read_subjects(workspace: Path) -> list[Subject]:
    """Parse entities/subjects.csv defensively; [] if not yet created."""
    rows = _read_registry(workspace / "entities" / "subjects.csv", SUBJECT_FIELDS)
    return [Subject(*row) for row in rows]


def read_vehicles(workspace: Path) -> list[Vehicle]:
    """Parse entities/vehicles.csv defensively; [] if not yet created."""
    rows = _read_registry(workspace / "entities" / "vehicles.csv", VEHICLE_FIELDS)
    return [Vehicle(*row) for row in rows]


def read_links(workspace: Path) -> list[Link]:
    """Parse entities/links.csv defensively; [] if not yet created.

    Unlike the commented config CSVs, the entity files are
    machine-append-only records: no comments, exact header, every row
    field-counted, and each link's entity_type validated.
    """
    rows = _read_registry(workspace / "entities" / "links.csv", LINK_FIELDS)
    links = [Link(*row) for row in rows]
    for link in links:
        if link.entity_type not in ENTITY_TYPES:
            raise CaseworkError(
                f"links.csv names unknown entity type {link.entity_type!r}; "
                f"expected one of: {', '.join(ENTITY_TYPES)}"
            )
    return links


def _read_registry(path: Path, fields: tuple[str, ...]) -> list[list[str]]:
    """Parse one append-only entity CSV; return its data rows (no header)."""
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise CaseworkError(f"entity file {path} is empty") from None
        if tuple(header) != fields:
            raise CaseworkError(
                f"entity file {path} has unexpected header {header!r}; "
                f"expected {list(fields)!r}"
            )
        rows = []
        for line_no, row in enumerate(reader, start=2):
            if len(row) != len(fields):
                raise CaseworkError(
                    f"entity file {path}, line {line_no}: "
                    f"expected {len(fields)} fields, got {len(row)}"
                )
            rows.append(row)
    return rows
