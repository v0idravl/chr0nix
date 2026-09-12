"""Entities and associations: subjects, vehicles, and the links between cases.

Three CSVs under ``entities/`` hold what connects cases to the world
and to each other:

- ``subjects.csv`` — subject profiles (see :data:`SUBJECT_FIELDS`)
- ``vehicles.csv`` — vehicle ("transportation") profiles
  (see :data:`VEHICLE_FIELDS`)
- ``links.csv`` — append-only associations
  (``case_id,entity_type,entity_id,role,notes``), where ``entity_type``
  is ``subject``, ``vehicle``, or ``case``

``links.csv`` follows the custody.py append-only pattern via
:func:`chr0nix.casework.workspace.append_csv_row`: the set of
associations is a record of what the investigator knew, and records
only ever grow. The two registries are profiles, not logs: a profile is
the current best picture of a subject or vehicle, so ``subject edit`` /
``subject set`` *replace* that entity's row (see :func:`update_subject`
and :func:`update_vehicle`). The evidentiary record of an entity's
involvement in a case is the link row and the case event log, both
append-only; the registry row is the working profile those records
point at.

Registry schema versioning. The Phase 3 registries had three columns
(``SUBJECT_FIELDS_V1`` / ``VEHICLE_FIELDS_V1``); the rich profiles added
in Phase 4 extend both headers with further columns. Readers accept
either header and pad short rows; the first write to a legacy file
upgrades it in place (header rewritten, existing rows preserved and
padded), so an old workspace keeps working without a manual migration
step.

Multi-value fields (aliases, phones, emails, usernames, addresses) hold
a ``;``-separated list inside one CSV field — one entity is still one
line, and entries may not themselves contain the separator.

Two association kinds are computed from links.csv, both surfaced by the
``links`` command and the generated synopsis:

- **Shared entities** — two cases linked to the same ``subject_id`` or
  ``vehicle_id`` are associated ("shared subject subj-001"). This is
  how repeat-offender and vehicle-reuse patterns emerge without anyone
  declaring them. (A subject's vehicles are the same mechanism: link
  both to the case and the association graph connects them.)
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
from dataclasses import dataclass, replace
from pathlib import Path

from . import CaseworkError, cases
from .workspace import append_csv_row, clean_field, validate_slug

#: The Phase 3 (three-column) registry headers, still accepted on read
#: and upgraded on first write.
SUBJECT_FIELDS_V1 = ("subject_id", "nickname", "descriptor_summary")
VEHICLE_FIELDS_V1 = ("vehicle_id", "plate", "description")

#: entities/subjects.csv columns, in canonical order. The V1 columns
#: come first, so a V1 row is a strict prefix of a current row.
SUBJECT_FIELDS = SUBJECT_FIELDS_V1 + (
    "aliases",
    "date_of_birth",
    "physical_description",
    "phones",
    "emails",
    "usernames",
    "addresses",
    "employer",
    "notes",
)

#: entities/vehicles.csv columns, in canonical order (V1 prefix first).
VEHICLE_FIELDS = VEHICLE_FIELDS_V1 + (
    "jurisdiction",
    "vin",
    "make",
    "model",
    "year",
    "color",
    "body_style",
    "registered_owner",
    "notes",
)

#: entities/links.csv columns, in canonical order.
LINK_FIELDS = ("case_id", "entity_type", "entity_id", "role", "notes")

#: The entity types a link row may name.
ENTITY_TYPES = ("subject", "vehicle", "case")

#: In-field list separator for multi-value registry columns. Semicolon
#: rather than comma so the raw CSV stays one-visual-field-per-column.
MULTI_SEPARATOR = ";"


@dataclass(frozen=True)
class ProfileField:
    """One editable profile field: registry column plus UX metadata.

    The console's guided form walks these in order (``label`` is the
    prompt, ``hint`` the format guidance shown beside it); the casework
    CLI uses the same list to validate ``entity set`` field names.
    ``multi`` fields accept comma-separated input and store it
    ``;``-joined; ``long`` fields offer an ``$EDITOR`` handoff in the
    console form instead of inline typing.
    """

    name: str
    label: str
    hint: str = ""
    multi: bool = False
    long: bool = False


#: The subject profile form, in prompt order. ``subject_id`` is not a
#: profile field: it is the registry key, asked for (or given) first.
SUBJECT_PROFILE_FIELDS: tuple[ProfileField, ...] = (
    ProfileField("nickname", "Name / primary nickname", "defaults to the id if left blank"),
    ProfileField("aliases", "Aliases & nicknames", "comma-separated", multi=True),
    ProfileField("date_of_birth", "Date of birth", "YYYY-MM-DD, or partial (YYYY-MM) if that is all you know"),
    ProfileField("physical_description", "Physical description", "build, height, hair, distinguishing marks"),
    ProfileField("phones", "Phone numbers", "comma-separated; international format (+1...) preferred", multi=True),
    ProfileField("emails", "Email addresses", "comma-separated", multi=True),
    ProfileField("usernames", "Usernames / handles", "comma-separated; platform prefix optional (ig:jdoe)", multi=True),
    ProfileField("addresses", "Known addresses", "comma-separated", multi=True),
    ProfileField("employer", "Employer / workplace"),
    ProfileField("descriptor_summary", "One-line descriptor", "the short summary shown in listings"),
    ProfileField("notes", "Notes", "free text", long=True),
)

#: The vehicle ("transportation profile") form, in prompt order.
VEHICLE_PROFILE_FIELDS: tuple[ProfileField, ...] = (
    ProfileField("plate", "License plate", "e.g. ABC 123"),
    ProfileField("jurisdiction", "Plate jurisdiction", "state / province / country of registration"),
    ProfileField("vin", "VIN", "17-character vehicle identification number"),
    ProfileField("make", "Make", "e.g. Honda"),
    ProfileField("model", "Model", "e.g. Civic"),
    ProfileField("year", "Model year", "e.g. 2019"),
    ProfileField("color", "Color"),
    ProfileField("body_style", "Body style", "sedan, SUV, van, pickup, motorcycle, ..."),
    ProfileField("registered_owner", "Registered owner", "as recorded; link the matching subject to the case"),
    ProfileField("description", "One-line description", "the short summary shown in listings"),
    ProfileField("notes", "Notes", "free text", long=True),
)

#: Field-name lookup, for `subject set` / `entity set` validation.
SUBJECT_PROFILE_FIELD_NAMES = tuple(field.name for field in SUBJECT_PROFILE_FIELDS)
VEHICLE_PROFILE_FIELD_NAMES = tuple(field.name for field in VEHICLE_PROFILE_FIELDS)


@dataclass(frozen=True)
class Subject:
    """One row of entities/subjects.csv.

    Multi-value columns are tuples here and ``;``-joined in the file.
    The three V1 fields stay positional so old call sites and old files
    keep working; everything added in Phase 4 is keyword-with-default.
    """

    subject_id: str
    nickname: str
    descriptor_summary: str
    aliases: tuple[str, ...] = ()
    date_of_birth: str = ""
    physical_description: str = ""
    phones: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    usernames: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()
    employer: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Vehicle:
    """One row of entities/vehicles.csv — a transportation profile."""

    vehicle_id: str
    plate: str
    description: str
    jurisdiction: str = ""
    vin: str = ""
    make: str = ""
    model: str = ""
    year: str = ""
    color: str = ""
    body_style: str = ""
    registered_owner: str = ""
    notes: str = ""


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


def _join_multi(values: tuple[str, ...]) -> str:
    """The on-disk form of a multi-value field: ``;``-joined."""
    return MULTI_SEPARATOR.join(values)


def _split_multi(value: str) -> tuple[str, ...]:
    """The in-memory form of a multi-value column: a tuple of entries."""
    return tuple(item.strip() for item in value.split(MULTI_SEPARATOR) if item.strip())


def _clean_multi(values, field_name: str) -> tuple[str, ...]:
    """Validate multi-value entries; drop blanks, reject the separator.

    Accepts either an iterable of entries or the stored ``;``-joined
    string (so a profile's current values round-trip through a form or
    an ``update_*`` call unchanged).
    """
    if isinstance(values, str):
        values = _split_multi(values)
    items = []
    for value in values:
        cleaned = clean_field(str(value), field_name, required=False)
        if not cleaned:
            continue
        if MULTI_SEPARATOR in cleaned:
            raise CaseworkError(
                f"{field_name} entries must not contain {MULTI_SEPARATOR!r} "
                "(it is the list separator in the registry file)"
            )
        items.append(cleaned)
    return tuple(items)


def _clean_scalar(value: str, field_name: str) -> str:
    return clean_field(value, field_name, required=False)


def _build_subject(subject_id: str, values: dict) -> Subject:
    """Construct a validated Subject from a field-name -> value mapping."""
    return Subject(
        subject_id=subject_id,
        nickname=_clean_scalar(values.get("nickname", ""), "nickname"),
        descriptor_summary=_clean_scalar(
            values.get("descriptor_summary", ""), "descriptor_summary"
        ),
        aliases=_clean_multi(values.get("aliases", ()), "aliases"),
        date_of_birth=_clean_scalar(values.get("date_of_birth", ""), "date_of_birth"),
        physical_description=_clean_scalar(
            values.get("physical_description", ""), "physical_description"
        ),
        phones=_clean_multi(values.get("phones", ()), "phones"),
        emails=_clean_multi(values.get("emails", ()), "emails"),
        usernames=_clean_multi(values.get("usernames", ()), "usernames"),
        addresses=_clean_multi(values.get("addresses", ()), "addresses"),
        employer=_clean_scalar(values.get("employer", ""), "employer"),
        notes=_clean_scalar(values.get("notes", ""), "notes"),
    )


def _build_vehicle(vehicle_id: str, values: dict) -> Vehicle:
    """Construct a validated Vehicle from a field-name -> value mapping."""
    return Vehicle(
        vehicle_id=vehicle_id,
        plate=_clean_scalar(values.get("plate", ""), "plate"),
        description=_clean_scalar(values.get("description", ""), "description"),
        jurisdiction=_clean_scalar(values.get("jurisdiction", ""), "jurisdiction"),
        vin=_clean_scalar(values.get("vin", ""), "vin"),
        make=_clean_scalar(values.get("make", ""), "make"),
        model=_clean_scalar(values.get("model", ""), "model"),
        year=_clean_scalar(values.get("year", ""), "year"),
        color=_clean_scalar(values.get("color", ""), "color"),
        body_style=_clean_scalar(values.get("body_style", ""), "body_style"),
        registered_owner=_clean_scalar(
            values.get("registered_owner", ""), "registered_owner"
        ),
        notes=_clean_scalar(values.get("notes", ""), "notes"),
    )


def _subject_row(subject: Subject) -> list[str]:
    """One subjects.csv row, in SUBJECT_FIELDS order."""
    return [
        subject.subject_id,
        subject.nickname,
        subject.descriptor_summary,
        _join_multi(subject.aliases),
        subject.date_of_birth,
        subject.physical_description,
        _join_multi(subject.phones),
        _join_multi(subject.emails),
        _join_multi(subject.usernames),
        _join_multi(subject.addresses),
        subject.employer,
        subject.notes,
    ]


def _vehicle_row(vehicle: Vehicle) -> list[str]:
    """One vehicles.csv row, in VEHICLE_FIELDS order."""
    return [
        vehicle.vehicle_id,
        vehicle.plate,
        vehicle.description,
        vehicle.jurisdiction,
        vehicle.vin,
        vehicle.make,
        vehicle.model,
        vehicle.year,
        vehicle.color,
        vehicle.body_style,
        vehicle.registered_owner,
        vehicle.notes,
    ]


def subject_values(subject: Subject) -> dict[str, str]:
    """Field name -> stored-string mapping for a subject (form prefill)."""
    row = _subject_row(subject)
    return dict(zip(SUBJECT_FIELDS, row))


def vehicle_values(vehicle: Vehicle) -> dict[str, str]:
    """Field name -> stored-string mapping for a vehicle (form prefill)."""
    row = _vehicle_row(vehicle)
    return dict(zip(VEHICLE_FIELDS, row))


def register_subject(
    workspace: Path, subject_id: str, *, nickname: str = "", descriptor_summary: str = "",
    aliases=(), date_of_birth: str = "", physical_description: str = "",
    phones=(), emails=(), usernames=(), addresses=(), employer: str = "",
    notes: str = "",
) -> Subject:
    """Register one subject in entities/subjects.csv; return the row.

    Explicit counterpart to :func:`append_link`'s auto-registration:
    fails loudly on a duplicate id rather than silently keeping the old
    row. A blank nickname defaults to the id itself, matching what
    auto-registration records. All profile fields are optional — a
    registry row is a working profile, filled in as the case learns.
    """
    subject_id = validate_slug(subject_id, "subject id")
    path = workspace / "entities" / "subjects.csv"
    _migrate_registry(path, SUBJECT_FIELDS, (SUBJECT_FIELDS_V1,))
    if subject_id in {s.subject_id for s in read_subjects(workspace)}:
        raise CaseworkError(f"subject {subject_id!r} is already registered")
    subject = _build_subject(subject_id, {
        "nickname": nickname or subject_id,
        "descriptor_summary": descriptor_summary,
        "aliases": aliases,
        "date_of_birth": date_of_birth,
        "physical_description": physical_description,
        "phones": phones,
        "emails": emails,
        "usernames": usernames,
        "addresses": addresses,
        "employer": employer,
        "notes": notes,
    })
    append_csv_row(path, SUBJECT_FIELDS, _subject_row(subject))
    return subject


def register_vehicle(
    workspace: Path, vehicle_id: str, *, plate: str = "", description: str = "",
    jurisdiction: str = "", vin: str = "", make: str = "", model: str = "",
    year: str = "", color: str = "", body_style: str = "",
    registered_owner: str = "", notes: str = "",
) -> Vehicle:
    """Register one vehicle in entities/vehicles.csv; return the row.

    Same contract as :func:`register_subject`: duplicate ids are
    rejected rather than merged.
    """
    vehicle_id = validate_slug(vehicle_id, "vehicle id")
    path = workspace / "entities" / "vehicles.csv"
    _migrate_registry(path, VEHICLE_FIELDS, (VEHICLE_FIELDS_V1,))
    if vehicle_id in {v.vehicle_id for v in read_vehicles(workspace)}:
        raise CaseworkError(f"vehicle {vehicle_id!r} is already registered")
    vehicle = _build_vehicle(vehicle_id, {
        "plate": plate,
        "description": description,
        "jurisdiction": jurisdiction,
        "vin": vin,
        "make": make,
        "model": model,
        "year": year,
        "color": color,
        "body_style": body_style,
        "registered_owner": registered_owner,
        "notes": notes,
    })
    append_csv_row(path, VEHICLE_FIELDS, _vehicle_row(vehicle))
    return vehicle


def get_subject(workspace: Path, subject_id: str) -> Subject:
    """The registered subject ``subject_id``, or a clean error."""
    subject_id = validate_slug(subject_id, "subject id")
    for subject in read_subjects(workspace):
        if subject.subject_id == subject_id:
            return subject
    raise CaseworkError(
        f"unknown subject {subject_id!r} (register it first with: subject add)"
    )


def get_vehicle(workspace: Path, vehicle_id: str) -> Vehicle:
    """The registered vehicle ``vehicle_id``, or a clean error."""
    vehicle_id = validate_slug(vehicle_id, "vehicle id")
    for vehicle in read_vehicles(workspace):
        if vehicle.vehicle_id == vehicle_id:
            return vehicle
    raise CaseworkError(
        f"unknown vehicle {vehicle_id!r} (register it first with: vehicle add)"
    )


def update_subject(workspace: Path, subject_id: str, **changes) -> Subject:
    """Replace one subject's registry row with updated fields.

    The registry is a working profile, not an evidentiary log: editing
    rewrites the row in place (the file is rewritten wholesale, every
    other row byte-identical). Unknown ids and unknown field names fail
    loudly; multi-value fields take iterables, scalar fields strings.
    """
    current = get_subject(workspace, subject_id)
    unknown = sorted(set(changes) - set(SUBJECT_PROFILE_FIELD_NAMES))
    if unknown:
        raise CaseworkError(
            f"unknown subject field(s): {', '.join(unknown)}; "
            f"profile fields: {', '.join(SUBJECT_PROFILE_FIELD_NAMES)}"
        )
    updated = _build_subject(
        current.subject_id, {**subject_values(current), **changes}
    )
    _rewrite_registry(
        workspace / "entities" / "subjects.csv",
        SUBJECT_FIELDS,
        [_subject_row(updated if s.subject_id == current.subject_id else s)
         for s in read_subjects(workspace)],
    )
    return updated


def update_vehicle(workspace: Path, vehicle_id: str, **changes) -> Vehicle:
    """Replace one vehicle's registry row with updated fields.

    Same contract as :func:`update_subject`.
    """
    current = get_vehicle(workspace, vehicle_id)
    unknown = sorted(set(changes) - set(VEHICLE_PROFILE_FIELD_NAMES))
    if unknown:
        raise CaseworkError(
            f"unknown vehicle field(s): {', '.join(unknown)}; "
            f"profile fields: {', '.join(VEHICLE_PROFILE_FIELD_NAMES)}"
        )
    updated = _build_vehicle(
        current.vehicle_id, {**vehicle_values(current), **changes}
    )
    _rewrite_registry(
        workspace / "entities" / "vehicles.csv",
        VEHICLE_FIELDS,
        [_vehicle_row(updated if v.vehicle_id == current.vehicle_id else v)
         for v in read_vehicles(workspace)],
    )
    return updated


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
        path = workspace / "entities" / "subjects.csv"
        _migrate_registry(path, SUBJECT_FIELDS, (SUBJECT_FIELDS_V1,))
        if entity_id not in {s.subject_id for s in read_subjects(workspace)}:
            descriptor = role or notes or f"auto-registered from {case_id}"
            append_csv_row(
                path,
                SUBJECT_FIELDS,
                [entity_id, entity_id, descriptor]
                + [""] * (len(SUBJECT_FIELDS) - len(SUBJECT_FIELDS_V1)),
            )
            registered = True
    elif entity_type == "vehicle":
        path = workspace / "entities" / "vehicles.csv"
        _migrate_registry(path, VEHICLE_FIELDS, (VEHICLE_FIELDS_V1,))
        if entity_id not in {v.vehicle_id for v in read_vehicles(workspace)}:
            description = role or notes or f"auto-registered from {case_id}"
            append_csv_row(
                path,
                VEHICLE_FIELDS,
                [entity_id, "", description]
                + [""] * (len(VEHICLE_FIELDS) - len(VEHICLE_FIELDS_V1)),
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
    """Parse entities/subjects.csv defensively; [] if not yet created.

    Both the V1 (three-column) and current headers are accepted; V1
    rows are padded with empty profile fields.
    """
    rows = _read_registry(
        workspace / "entities" / "subjects.csv", SUBJECT_FIELDS, (SUBJECT_FIELDS_V1,)
    )
    return [
        Subject(
            subject_id=row[0],
            nickname=row[1],
            descriptor_summary=row[2],
            aliases=_split_multi(row[3]),
            date_of_birth=row[4],
            physical_description=row[5],
            phones=_split_multi(row[6]),
            emails=_split_multi(row[7]),
            usernames=_split_multi(row[8]),
            addresses=_split_multi(row[9]),
            employer=row[10],
            notes=row[11],
        )
        for row in rows
    ]


def read_vehicles(workspace: Path) -> list[Vehicle]:
    """Parse entities/vehicles.csv defensively; [] if not yet created.

    Accepts the V1 header like :func:`read_subjects`.
    """
    rows = _read_registry(
        workspace / "entities" / "vehicles.csv", VEHICLE_FIELDS, (VEHICLE_FIELDS_V1,)
    )
    return [
        Vehicle(
            vehicle_id=row[0],
            plate=row[1],
            description=row[2],
            jurisdiction=row[3],
            vin=row[4],
            make=row[5],
            model=row[6],
            year=row[7],
            color=row[8],
            body_style=row[9],
            registered_owner=row[10],
            notes=row[11],
        )
        for row in rows
    ]


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


def render_subject_card(subject: Subject) -> str:
    """The aligned profile card shown by ``subject show``."""
    values = subject_values(subject)
    return _render_card(
        f"subject profile — {subject.subject_id}", SUBJECT_PROFILE_FIELDS, values
    )


def render_vehicle_card(vehicle: Vehicle) -> str:
    """The aligned profile card shown by ``vehicle show``."""
    values = vehicle_values(vehicle)
    return _render_card(
        f"transportation profile (vehicle) — {vehicle.vehicle_id}",
        VEHICLE_PROFILE_FIELDS,
        values,
    )


def _render_card(title: str, fields: tuple[ProfileField, ...], values: dict[str, str]) -> str:
    width = max(len(field.label) for field in fields)
    lines = [title, "=" * len(title)]
    for field in fields:
        stored = values.get(field.name, "")
        display = stored.replace(MULTI_SEPARATOR, ", ") if field.multi else stored
        lines.append(f"  {field.label:<{width}}  {display or '(not recorded)'}")
    return "\n".join(lines)


def _migrate_registry(
    path: Path, fields: tuple[str, ...], legacy: tuple[tuple[str, ...], ...]
) -> None:
    """Upgrade a legacy-header registry file to the current header.

    A one-time, in-place upgrade performed on the first write to an old
    workspace file: the header is rewritten and every existing row is
    preserved, padded with empty values for the new columns. No-op when
    the file is missing or already current.
    """
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows or tuple(rows[0]) not in legacy:
        return
    width = len(rows[0])
    padded = [row + [""] * (len(fields) - width) for row in rows[1:]]
    _rewrite_registry(path, fields, padded)


def _rewrite_registry(path: Path, fields: tuple[str, ...], rows: list[list[str]]) -> None:
    """Write a whole registry file (header + rows) atomically-ish.

    Used by profile edits and the legacy-header upgrade — the two
    places where a registry legitimately changes existing content. The
    write goes through a sibling temp file so an interrupted write never
    leaves a half-written registry.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)
    temp.replace(path)


def _read_registry(
    path: Path,
    fields: tuple[str, ...],
    legacy: tuple[tuple[str, ...], ...] = (),
) -> list[list[str]]:
    """Parse one append-only entity CSV; return its data rows (no header).

    Rows are padded to the current field count when the file carries a
    known legacy header; anything else fails loudly, as before.
    """
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise CaseworkError(f"entity file {path} is empty") from None
        known = (fields,) + tuple(legacy)
        if tuple(header) not in known:
            raise CaseworkError(
                f"entity file {path} has unexpected header {header!r}; "
                f"expected {list(fields)!r}"
            )
        width = len(header)
        rows = []
        for line_no, row in enumerate(reader, start=2):
            if len(row) != width:
                raise CaseworkError(
                    f"entity file {path}, line {line_no}: "
                    f"expected {width} fields, got {len(row)}"
                )
            rows.append(row + [""] * (len(fields) - width))
    return rows
