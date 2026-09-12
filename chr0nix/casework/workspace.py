"""Workspace layout, initialization, and shared CSV discipline.

This module owns everything about the workspace *as a directory*: the
canonical layout, the ``init`` that creates it, the guard every command
runs before touching it, the commented-CSV parsing for the two config
files, and the append-only row writer that the evidentiary CSVs
(``events.csv``, ``entities/links.csv``, and the entity registries)
share.

Three safety rules live here, each in one audited place:

1. **Slug-safe identifiers.** Case ids (and entity ids) are lowercase
   letters, digits, and hyphens — e.g. ``case-2026-014``. A case id
   becomes a directory name, so this is the path-traversal defense: no
   slashes, no dots, no absolute paths can ever reach the filesystem
   through an identifier. :func:`case_dir` additionally re-checks
   containment with :func:`chr0nix.core.safety.is_within` as defense in
   depth.
2. **Commented config CSVs.** ``config/categories.csv`` and
   ``config/taxonomy.csv`` are investigator-edited files. Lines whose
   first non-space character is ``#`` are comments and blank lines are
   skipped, so the format is self-documenting. The header must match
   exactly, rows are parsed defensively (line-numbered errors), and
   duplicate ids are rejected — config is input, and input is
   untrusted.
3. **Append-only with a stable header.** :func:`append_csv_row` is
   :func:`chr0nix.core.csvx.append_row` bound to casework's error type:
   an existing non-empty file's header must match exactly before a
   byte is appended (we refuse to append to a file we did not create),
   and the only write performed is append mode.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from chr0nix.core import csvx, fields
from chr0nix.core.safety import is_within

from . import CaseworkError

#: config/categories.csv columns, in canonical order.
CATEGORY_FIELDS = ("id", "label", "description")

#: config/taxonomy.csv columns, in canonical order.
TAXONOMY_FIELDS = ("path", "label", "description")

#: The directories ``init`` creates, in layout order.
LAYOUT_DIRS = ("config", "entities", "cases")

#: Slug-safe identifier shape: lowercase letters, digits, single
#: hyphens between segments (``case-2026-014``, ``subj-001``).
_SLUG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

#: Starter config/categories.csv: the header comment documents the
#: format at the point of use, and the example rows are realistic
#: asset-protection categories that double as a format demonstration.
STARTER_CATEGORIES = """\
# casework case categories — id,label,description
#
# One category per line. Lines whose first non-space character is '#'
# are comments, and blank lines are skipped. Category ids must be
# slug-safe: lowercase letters, digits, and hyphens. A case can only be
# categorized with an id listed here — add your own rows below.
id,label,description
external-theft,External theft,Theft of merchandise or cash by non-employees
internal-theft,Internal theft,Loss caused by employee dishonesty
fraud,Fraud,Refund / price-tag / payment fraud against the store
orchestrated-retail-crime,Orchestrated retail crime,Coordinated multi-person theft for resale
safety,Safety incident,Injury or hazard events on the premises
"""

#: Starter config/taxonomy.csv: full slash-delimited paths, so every
#: row is self-contained and edits diff line-locally.
STARTER_TAXONOMY = """\
# casework behavior taxonomy — path,label,description
#
# One classification per line. 'path' is a FULL slash-delimited path
# from the root of the tree (self-contained, so diffs stay line-local).
# A path is assignable to a case only if it is listed here verbatim —
# an intermediate node must be listed explicitly to be used. Lines
# whose first non-space character is '#' are comments; blank lines are
# skipped.
path,label,description
external-theft,External theft,Root of the external-theft behavior tree
external-theft/method,Method,How the theft was carried out
external-theft/method/concealment,Concealment,Merchandise hidden before passing the last point of sale
external-theft/method/concealment/fitting-room,Fitting room,Concealment inside a fitting room
external-theft/method/concealment/bag,Bag or backpack,Concealment in a personal bag or backpack
external-theft/method/tag-switch,Tag switching,Price tags swapped before purchase
external-theft/method/walkout,Walkout,Merchandise carried out openly without payment
internal-theft,Internal theft,Root of the internal-theft behavior tree
internal-theft/method,Method,How the internal loss occurred
internal-theft/method/sweethearting,Sweethearting,Unscanned merchandise passed to an accomplice at checkout
internal-theft/method/refund-abuse,Refund abuse,Fraudulent refunds processed by an employee
"""


@dataclass(frozen=True)
class Category:
    """One row of config/categories.csv."""

    id: str
    label: str
    description: str


@dataclass(frozen=True)
class TaxonomyEntry:
    """One row of config/taxonomy.csv: a full path plus its label."""

    path: str
    label: str
    description: str


def validate_slug(value: str, what: str) -> str:
    """Validate a slug-safe identifier; return it stripped.

    Case ids become directory names and entity ids are join keys across
    CSVs, so both must be boring: lowercase letters, digits, and
    hyphens. Anything else — slashes, dots, whitespace, control
    characters — is rejected here rather than sanitized, so a typo
    fails loudly instead of silently addressing a different case.
    """
    cleaned = value.strip()
    if not _SLUG_RE.fullmatch(cleaned):
        raise CaseworkError(
            f"{what} must be slug-safe (lowercase letters, digits, hyphens): {value!r}"
        )
    return cleaned


def clean_field(value: str, field_name: str, *, required: bool) -> str:
    """Validate and normalize one free-text field for an append-only CSV.

    The shared no-control-characters rule of
    :func:`chr0nix.core.fields.clean_field`, bound to
    :class:`CaseworkError`: one record is one line, and a newline inside
    a field would let a single record smuggle in forged additional rows.
    """
    return fields.clean_field(value, field_name, required=required, error=CaseworkError)


def case_dir(workspace: Path, case_id: str) -> Path:
    """The directory of ``case_id`` inside ``workspace``, containment-checked.

    The slug rule already makes escape impossible; the ``is_within``
    re-check is belt-and-braces so the "never write outside the
    workspace" invariant holds even if the slug rule is ever loosened.
    """
    case_id = validate_slug(case_id, "case id")
    directory = (workspace / "cases" / case_id).resolve()
    if not is_within(directory, workspace.resolve()):
        raise CaseworkError(f"refusing: case directory {directory} escapes the workspace")
    return directory


def append_csv_row(path: Path, fields: tuple[str, ...], row: list[str]) -> None:
    """Append one row to an append-only CSV, creating it if needed.

    :func:`chr0nix.core.csvx.append_row`'s pattern exactly: an
    existing non-empty file's header must match ``fields`` precisely
    (we refuse to append to a file we did not create), the parent is
    created on first write, and the only write ever performed is adding
    bytes at the end of the file. Callers clean free-text fields with
    :func:`clean_field` before building ``row``.
    """
    csvx.append_row(
        path,
        fields,
        row,
        what="the casework schema",
        error=CaseworkError,
    )


def init_workspace(root: Path) -> list[Path]:
    """Create the workspace layout at ``root``; return the paths written.

    Refuses if ``config/`` already exists: re-initializing an existing
    workspace would suggest its config history is disposable, and it
    never is. The starter config files carry a commented header and a
    few realistic asset-protection rows so the format is
    self-documenting at the point of use. The entity CSVs are created
    header-only — comments are a config-file feature; the append-only
    files keep a machine-checkable first line.
    """
    root = root.resolve()
    if (root / "config").exists():
        raise CaseworkError(f"workspace {root} is already initialized (config/ exists)")
    written: list[Path] = []
    for name in LAYOUT_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    files = {
        root / "config" / "categories.csv": STARTER_CATEGORIES,
        root / "config" / "taxonomy.csv": STARTER_TAXONOMY,
        root / "entities" / "subjects.csv": (
            "subject_id,nickname,descriptor_summary,aliases,date_of_birth,"
            "physical_description,phones,emails,usernames,addresses,employer,notes\n"
        ),
        root / "entities" / "vehicles.csv": (
            "vehicle_id,plate,description,jurisdiction,vin,make,model,year,"
            "color,body_style,registered_owner,notes\n"
        ),
        root / "entities" / "links.csv": "case_id,entity_type,entity_id,role,notes\n",
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def require_workspace(root: Path) -> Path:
    """The initialized workspace at ``root``, or a guidance-rich error."""
    root = root.resolve()
    missing = [name for name in LAYOUT_DIRS if not (root / name).is_dir()]
    if missing:
        raise CaseworkError(
            f"workspace {root} is not initialized (missing: {', '.join(missing)}) — run: init"
        )
    return root


def read_categories(workspace: Path) -> list[Category]:
    """Parse config/categories.csv defensively into frozen rows."""
    rows = _read_commented_csv(
        workspace / "config" / "categories.csv", CATEGORY_FIELDS, "categories"
    )
    categories = [Category(id=row[0], label=row[1], description=row[2]) for row in rows]
    seen: set[str] = set()
    for category in categories:
        validate_slug(category.id, "category id in categories.csv")
        if category.id in seen:
            raise CaseworkError(f"categories.csv defines category {category.id!r} twice")
        seen.add(category.id)
    return categories


def read_taxonomy(workspace: Path) -> list[TaxonomyEntry]:
    """Parse config/taxonomy.csv defensively into frozen rows."""
    rows = _read_commented_csv(
        workspace / "config" / "taxonomy.csv", TAXONOMY_FIELDS, "taxonomy"
    )
    entries = [TaxonomyEntry(path=row[0], label=row[1], description=row[2]) for row in rows]
    seen: set[str] = set()
    for entry in entries:
        segments = entry.path.split("/")
        if any(not _SLUG_RE.fullmatch(segment) for segment in segments):
            raise CaseworkError(
                f"taxonomy path {entry.path!r} in taxonomy.csv is not "
                "slash-delimited slug-safe segments"
            )
        if entry.path in seen:
            raise CaseworkError(f"taxonomy.csv lists path {entry.path!r} twice")
        seen.add(entry.path)
    return entries


def _read_commented_csv(
    path: Path, fields: tuple[str, ...], what: str
) -> list[list[str]]:
    """Parse a commented config CSV; return its data rows (no header).

    Comment stripping happens line-wise *before* CSV parsing — a line
    whose first non-space character is ``#`` never reaches the parser —
    which means quoted fields may not span lines in config files. That
    is a deliberate simplification: config rows are single-line by
    contract, and the header comment in each starter file says so.
    """
    if not path.is_file():
        raise CaseworkError(
            f"{what} config is missing: {path} (run init to create the workspace layout)"
        )
    with path.open("r", newline="", encoding="utf-8") as handle:
        data_lines = [
            (line_no, line)
            for line_no, line in enumerate(handle, start=1)
            if line.strip() and not line.lstrip().startswith("#")
        ]
    if not data_lines:
        raise CaseworkError(f"{what} config {path} has no header row")
    parsed = list(csv.reader(line for _, line in data_lines))
    if parsed[0] != list(fields):
        raise CaseworkError(
            f"{path} has unexpected header {parsed[0]!r}; expected {list(fields)!r}"
        )
    rows: list[list[str]] = []
    for (line_no, _), row in zip(data_lines[1:], parsed[1:]):
        if len(row) != len(fields):
            raise CaseworkError(
                f"{path}, line {line_no}: expected {len(fields)} fields, got {len(row)}"
            )
        rows.append(row)
    return rows
