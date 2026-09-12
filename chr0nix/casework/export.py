"""Case export: one case's record assembled into a sealed, reviewable bundle.

``export_case`` answers "hand me everything about this case, sealed": it
collects the case's own record files, the workspace rows that concern the
case, and a generated ``CASE-REPORT.md`` brief into one directory, then
stamps the directory with a cust0dia-format manifest of itself — a
self-sealing deliverable that any later holder can re-verify byte for
byte with ``chr0nix verify``.

The bundle at ``<out-root>/<case-id>-export-<utc-stamp>/``::

    CASE-REPORT.md          generated brief: header, events, entities,
                            statements, exhibits, custody, attestations,
                            verification instructions
    case.json               the case record, copied byte-exact
    synopsis.txt            freshly rendered (deterministic) synopsis
    events.csv              the case's append-only event log
    statements.csv          the statement record
    statements/             long-form statement bodies (*.txt)
    exhibits-manifest.*     the case's exhibits manifest (cust0dia), renamed
                            so it cannot collide with the bundle's own pair
    custody.csv             the case's custody log
    links.csv               excerpt: every association row naming this case
    entities/               subjects.csv / vehicles.csv, filtered to the
                            profiles linked to this case
    attest.csv              the workspace attestation log, copied whole
                            (rows are workspace-wide; filtering them would
                            silently discard context a reviewer may need)
    <anything else>         other files under cases/<id>/ — timeline
                            outputs, h4ndl3 findings stores and reports,
                            m3talex reports — copied with their structure
    manifest.csv/json       (written last, at the bundle root) the bundle's
                            own self-sealing manifest

Deliberate exclusions, each stated in the report:

- ``exhibits/`` — the evidence bytes themselves are never copied. They
  stay in the workspace under the case's own cust0dia manifest; the
  export carries that manifest and the custody log, and CASE-REPORT.md
  says how to verify the originals. An export is a *review* deliverable,
  not a second authoritative copy of the evidence.
- the two bundle manifest files are not included in their own manifest
  (they are written last, after every hashed byte exists).

Export is read-only on the workspace: nothing under it is written,
moved, or re-stamped. The bundle is an *output*, so the suite's
evidence-tree write refusal applies to it: the export refuses a target
inside the workspace's evidentiary trees (``cases/``, ``inbox/``), and
an existing bundle directory is never overwritten — a sealed bundle is
a record of fact; re-run the export for a new one.
"""

import csv
import shutil
from pathlib import Path

from cust0dia import manifest as cust0dia_manifest

from chr0nix.core import timeutil
from chr0nix.core.safety import is_within

from . import CaseworkError, cases, entities, statements, synopsis
from .workspace import case_dir, require_workspace

#: Case-directory record files copied byte-exact under the same name.
_STANDARD_COPIES = ("case.json", "events.csv", "statements.csv", "custody.csv")

#: The case's exhibits manifest pair, copied byte-exact under a renamed
#: target so it cannot collide with the bundle's own self-sealing pair.
_EXHIBIT_MANIFEST_COPIES = {
    "manifest.csv": "exhibits-manifest.csv",
    "manifest.json": "exhibits-manifest.json",
}


def _stamp(moment) -> str:
    """The bundle directory's UTC stamp: compact, filename-safe."""
    return moment.strftime("%Y%m%dT%H%M%SZ")


def export_case(
    workspace: Path,
    case_id: str,
    out_root: Path | None = None,
    *,
    actor: str = "",
) -> Path:
    """Assemble the sealed export bundle for ``case_id``; return its path.

    ``out_root`` defaults to ``<workspace>/exports``. The bundle
    directory is created fresh — an existing one is refused rather than
    overwritten. ``actor`` (optional; the export is a read-only copy
    operation) is recorded in the report header when given.
    """
    workspace = require_workspace(workspace)
    case = cases.load_case(workspace, case_id)
    source_dir = case_dir(workspace, case.id)
    if out_root is None:
        out_root = workspace / "exports"
    out_root = Path(out_root).expanduser().resolve()

    exported_at = timeutil.utcnow()
    bundle = out_root / f"{case.id}-export-{_stamp(exported_at)}"
    _check_bundle_location(workspace, bundle)

    bundle.mkdir(parents=True)
    copied = _copy_case_files(source_dir, bundle)
    (bundle / "synopsis.txt").write_text(
        synopsis.render_synopsis(workspace, case), encoding="utf-8"
    )
    copied.append("synopsis.txt")
    linked = _linked_entities(workspace, case.id)
    copied += _write_entity_extracts(bundle, linked)
    copied += _copy_attestations(workspace, bundle)

    report = _render_report(
        workspace, case, actor=actor,
        exported_at=timeutil.format_utc(exported_at, timespec="seconds"),
        linked=linked, copied=copied,
    )
    (bundle / "CASE-REPORT.md").write_text(report, encoding="utf-8")

    # Self-seal, last: hash the finished bundle (CASE-REPORT.md included)
    # and write the manifest pair at the bundle root. The manifest files
    # cannot list themselves, so they are the only unmanifested files —
    # `cust0dia verify` knows this convention and exempts exactly that pair.
    entries = cust0dia_manifest.build_manifest(bundle)
    cust0dia_manifest.write_csv(entries, bundle / "manifest.csv")
    cust0dia_manifest.write_json(entries, bundle, bundle / "manifest.json")
    return bundle


def _check_bundle_location(workspace: Path, bundle: Path) -> None:
    """Refuse an export target that would contaminate evidence or clobber.

    The bundle is tool output, so the suite's cardinal rule applies: it
    must not land inside an evidentiary tree (any case directory or the
    inbox), and an existing bundle is never overwritten — exports are
    records, not scratch space.
    """
    resolved = bundle.resolve()
    for tree in (workspace / "cases", workspace / "inbox"):
        if is_within(resolved, tree.resolve()):
            raise CaseworkError(
                f"refusing to write the export bundle inside the evidentiary "
                f"tree {tree} — choose an --out outside the workspace's "
                "cases/ and inbox/"
            )
    if resolved.exists():
        raise CaseworkError(
            f"export bundle already exists: {resolved} — exports are never "
            "overwritten; remove it or choose another --out"
        )


def _copy_case_files(source_dir: Path, bundle: Path) -> list[str]:
    """Copy the case's record files; return the bundle-relative paths.

    Byte-exact copies of the standard record files, the (renamed)
    exhibits manifest pair, and the statement bodies — plus anything
    else under the case directory (timeline outputs, h4ndl3 stores and
    reports, m3talex reports), preserving relative structure.
    ``exhibits/`` is excluded: the evidence bytes are not part of the
    review bundle.
    """
    renamed = dict(_EXHIBIT_MANIFEST_COPIES)
    copied: list[str] = []
    for name in sorted(set(_STANDARD_COPIES) | set(renamed)):
        source = source_dir / name
        if source.is_file():
            target_name = renamed.get(name, name)
            shutil.copyfile(source, bundle / target_name)
            copied.append(target_name)
    bodies = source_dir / "statements"
    if bodies.is_dir():
        for body in sorted(bodies.glob("*.txt")):
            target = bundle / "statements" / body.name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(body, target)
            copied.append(f"statements/{body.name}")
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir)
        if relative.parts[0] in ("exhibits", "statements"):
            continue
        if len(relative.parts) == 1 and (
            relative.name in _STANDARD_COPIES
            or relative.name in renamed
            or relative.name == "synopsis.txt"
        ):
            continue
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.append(relative.as_posix())
    return copied


def _linked_entities(workspace: Path, case_id: str) -> dict:
    """The subjects, vehicles, and case-links tied to ``case_id``.

    Returns ``{"subjects", "vehicles", "case_links", "links",
    "missing"}`` — registry rows (or a placeholder naming the id when a
    linked entity is no longer registered) plus the raw link rows, which
    the report and the CSV extracts both consume.
    """
    links = [
        link
        for link in entities.read_links(workspace)
        if link.case_id == case_id
        or (link.entity_type == "case" and link.entity_id == case_id)
    ]
    subjects = {s.subject_id: s for s in entities.read_subjects(workspace)}
    vehicles = {v.vehicle_id: v for v in entities.read_vehicles(workspace)}
    missing: list[str] = []

    def pick(registry: dict, entity_type: str) -> list:
        found = []
        for link in links:
            if link.entity_type != entity_type:
                continue
            row = registry.get(link.entity_id)
            if row is None:
                missing.append(f"{entity_type} {link.entity_id}")
            else:
                found.append(row)
        return found

    return {
        "subjects": pick(subjects, "subject"),
        "vehicles": pick(vehicles, "vehicle"),
        "case_links": [link for link in links if link.entity_type == "case"],
        "links": links,
        "missing": missing,
    }


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[list[str]]) -> None:
    """Write one filtered extract CSV with the registry's exact header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


def _write_entity_extracts(bundle: Path, linked: dict) -> list[str]:
    """Write links.csv and the filtered entity registry extracts."""
    written: list[str] = []
    if linked["links"]:
        _write_csv(
            bundle / "links.csv",
            entities.LINK_FIELDS,
            [
                [link.case_id, link.entity_type, link.entity_id, link.role, link.notes]
                for link in linked["links"]
            ],
        )
        written.append("links.csv")
    if linked["subjects"]:
        _write_csv(
            bundle / "entities" / "subjects.csv",
            entities.SUBJECT_FIELDS,
            [
                [entities.subject_values(s)[field] for field in entities.SUBJECT_FIELDS]
                for s in linked["subjects"]
            ],
        )
        written.append("entities/subjects.csv")
    if linked["vehicles"]:
        _write_csv(
            bundle / "entities" / "vehicles.csv",
            entities.VEHICLE_FIELDS,
            [
                [entities.vehicle_values(v)[field] for field in entities.VEHICLE_FIELDS]
                for v in linked["vehicles"]
            ],
        )
        written.append("entities/vehicles.csv")
    return written


def _copy_attestations(workspace: Path, bundle: Path) -> list[str]:
    """Copy the workspace attestation log whole, when it exists.

    Whole rather than filtered to this case: attestation rows are
    workspace-wide context, and silently dropping the rest would present
    a trimmed picture of the operator's judgment calls. The report says
    so explicitly.
    """
    source = workspace / "attest.csv"
    if not source.is_file():
        return []
    shutil.copyfile(source, bundle / "attest.csv")
    return ["attest.csv"]


def _read_csv_rows(path: Path) -> list[list[str]]:
    """All rows (header included) of a CSV, or [] when absent."""
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return [row for row in csv.reader(handle) if row]


def _render_report(
    workspace: Path,
    case: cases.Case,
    *,
    actor: str,
    exported_at: str,
    linked: dict,
    copied: list[str],
) -> str:
    """Render CASE-REPORT.md: the review brief at the bundle root."""
    events = cases.read_events(workspace, case.id)
    case_statements = statements.list_statements(workspace, case.id)
    associations = entities.associations(workspace, case.id)
    actors = sorted({event.actor for event in events})

    lines = [
        f"# CASE-REPORT — {case.title}",
        "",
        f"- **Case:** {case.id}",
        f"- **Status:** {case.status}",
        f"- **Opened (UTC):** {case.opened_utc}",
        f"- **Closed (UTC):** {case.closed_utc or '(open)'}",
        f"- **Categories:** {', '.join(sorted(case.categories)) or '(none)'}",
        f"- **Taxonomy:** {', '.join(sorted(case.taxonomy_paths)) or '(none)'}",
        f"- **Actors:** {', '.join(actors) or '(none recorded)'}",
        f"- **Exported (UTC):** {exported_at}",
        f"- **Exported by:** {actor or '(not recorded)'}",
        "",
        "## Event timeline",
        "",
    ]
    if events:
        for event in events:
            lines.append(
                f"- `{event.timestamp_utc}` — **{event.event_type}** "
                f"({event.actor}): {event.detail}"
            )
    else:
        lines.append("No events recorded.")
    lines += ["", "## Entities", ""]
    if not linked["subjects"] and not linked["vehicles"] and not linked["case_links"]:
        lines.append("No entities linked to this case.")
    for subject in linked["subjects"]:
        lines += ["```", entities.render_subject_card(subject), "```", ""]
    for vehicle in linked["vehicles"]:
        lines += ["```", entities.render_vehicle_card(vehicle), "```", ""]
    if linked["case_links"]:
        lines.append("Directly linked cases: " + ", ".join(
            sorted(
                link.entity_id if link.case_id == case.id else link.case_id
                for link in linked["case_links"]
            )
        ))
        lines.append("")
    if linked["missing"]:
        lines.append(
            "Linked but no longer in the registry: " + ", ".join(linked["missing"])
        )
        lines.append("")
    if associations:
        lines += ["### Associated cases", ""]
        for association in associations:
            lines.append(
                f"- **{association.case_id}** ({association.title}) — "
                f"{'; '.join(association.reasons)}"
            )
        lines.append("")
    lines += ["## Statements", ""]
    if case_statements:
        lines += [
            "| statement | status | interviewee | role | body |",
            "| --- | --- | --- | --- | --- |",
        ]
        for statement in case_statements:
            body = statements.body_path(workspace, case.id, statement.statement_id)
            body_cell = (
                f"statements/{statement.statement_id}.txt" if body.is_file() else "—"
            )
            lines.append(
                f"| {statement.statement_id} | {statement.status} | "
                f"{statement.interviewee} | {statement.role} | {body_cell} |"
            )
    else:
        lines.append("No statements recorded.")
    lines += ["", "## Exhibits", ""]
    lines += _exhibit_section(workspace, case.id)
    lines += ["", "## Custody log", ""]
    custody_rows = _read_csv_rows(case_dir(workspace, case.id) / "custody.csv")
    if len(custody_rows) > 1:
        for row in custody_rows[1:]:
            timestamp, who, action, exhibit_path, exhibit_hash, notes = row
            lines.append(
                f"- `{timestamp}` — **{action}** {exhibit_path} "
                f"(sha256 {exhibit_hash[:12]}…, {who})"
                + (f": {notes}" if notes else "")
            )
    else:
        lines.append("No custody events recorded for this case.")
    lines += ["", "## Attestations", ""]
    attest_rows = _read_csv_rows(workspace / "attest.csv")
    if len(attest_rows) > 1:
        lines.append(
            "The complete workspace attestation log is included verbatim "
            "as `attest.csv` (rows are workspace-wide, not filtered to "
            "this case):"
        )
        lines.append("")
        for row in attest_rows[1:]:
            timestamp, who, action, reason = row
            lines.append(f"- `{timestamp}` — {who}: {action} — _{reason}_")
    else:
        lines.append("No attestations recorded in this workspace.")
    lines += ["", "## Bundle contents", ""]
    lines.append(
        "Every payload file in this bundle (the bundle's own "
        "`manifest.csv` / `manifest.json` describe all of them, and are "
        "themselves written last, after every hashed byte existed):"
    )
    lines.append("")
    for name in ["CASE-REPORT.md", *copied]:
        lines.append(f"- `{name}`")
    lines += [
        "",
        "The case's evidence bytes under `exhibits/` are deliberately "
        "**not** copied into this bundle; they remain in the workspace, "
        "covered by the case's own exhibits manifest (included here as "
        "`exhibits-manifest.csv` / `exhibits-manifest.json` when present) "
        "and custody log.",
        "",
        "## How to verify",
        "",
        "This bundle is self-sealing. From inside the bundle directory:",
        "",
        "    chr0nix verify manifest.json .",
        "",
        "A clean run prints `verification PASSED`; any CHANGED, MISSING, "
        "or unexpected EXTRA file fails with exit code 1. (The two "
        "manifest files describe the bundle and are not listed in "
        "themselves; `verify` exempts exactly that pair.)",
        "",
        "To verify the case's original evidence bytes, run against the "
        "workspace the case lives in:",
        "",
        f"    chr0nix verify <workspace>/cases/{case.id}/manifest.json "
        f"<workspace>/cases/{case.id}/exhibits",
        "",
    ]
    return "\n".join(lines)


def _exhibit_section(workspace: Path, case_id: str) -> list[str]:
    """The exhibits table, read from the case's cust0dia manifest."""
    directory = case_dir(workspace, case_id)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        manifest_path = directory / "manifest.csv"
    if not manifest_path.is_file():
        return ["No exhibits filed for this case (no exhibits manifest)."]
    _, entries = cust0dia_manifest.read_manifest(manifest_path)
    if not entries:
        return ["The exhibits manifest lists no files."]
    lines = [
        f"{len(entries)} exhibit(s) per `{manifest_path.name}` "
        "(included as `exhibits-manifest.*` in this bundle):",
        "",
        "| exhibit | size (bytes) | sha256 |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {entry.relative_path} | {entry.size_bytes} | `{entry.sha256[:12]}…` |"
        for entry in entries
    ]
    return lines
