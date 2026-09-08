"""Synopsis generation: one deterministic plain-text brief per case.

``cases/<case-id>/synopsis.txt`` is a *generated* file — the header
comment says so in its first line ("GENERATED — do not hand-edit"). It
is rebuilt on demand from the case record (case.json), the event log
(events.csv), the workspace config (category and taxonomy labels), and
the association graph (entities/links.csv). Nothing in it is source
data, so regenerating can never lose information, and hand edits are
pointless by construction: the next ``synopsis`` command overwrites
them.

The layout follows standard investigative field order:

1. **Header** — case id, title, status, opened/closed timestamps.
2. **Categories** — with their config labels.
3. **Taxonomy classifications** — full path rendered, with labels.
4. **Linked cases** — each with its association reason(s)
   (``shared subject subj-001`` / ``direct link``).
5. **Event timeline** — count, first/last timestamps, and the five
   most recent events.
6. **Synopsis** — one auto-generated plain-language paragraph composed
   from all of the above.

Determinism is a requirement, not a nicety: categories, taxonomy
paths, associations, and reasons are all emitted sorted, and events in
append order, so two generations of the same case state are
byte-identical and the file diffs cleanly in review. Labels are
resolved against the *current* config; a term whose config row was
since deleted is rendered with a "(not in config/...)" note rather
than failing — the synopsis is a view, and a view should degrade, not
crash.
"""

from pathlib import Path

from . import cases, entities
from .workspace import case_dir, read_categories, read_taxonomy

#: First line of every generated synopsis: the do-not-edit warning.
GENERATED_HEADER = "# GENERATED — do not hand-edit"

#: How many trailing events the timeline section shows.
RECENT_EVENT_COUNT = 5


def regenerate_synopsis(workspace: Path, case_id: str) -> Path:
    """Rebuild cases/<case-id>/synopsis.txt from current state; return its path."""
    case = cases.load_case(workspace, case_id)
    path = case_dir(workspace, case.id) / "synopsis.txt"
    path.write_text(render_synopsis(workspace, case), encoding="utf-8")
    return path


def render_synopsis(workspace: Path, case: cases.Case) -> str:
    """Render the synopsis text for ``case`` deterministically."""
    categories = {category.id: category for category in read_categories(workspace)}
    taxonomy = {entry.path: entry for entry in read_taxonomy(workspace)}
    events = cases.read_events(workspace, case.id)
    linked = entities.associations(workspace, case.id)

    lines = [
        GENERATED_HEADER,
        f"# regenerate with: synopsis {case.id}",
        "",
        f"Case:       {case.id}",
        f"Title:      {case.title}",
        f"Status:     {case.status}",
        f"Opened UTC: {case.opened_utc}",
        f"Closed UTC: {case.closed_utc or '(open)'}",
        "",
        "Categories:",
    ]
    if case.categories:
        for category_id in sorted(case.categories):
            category = categories.get(category_id)
            label = category.label if category else "(not in config/categories.csv)"
            lines.append(f"  {category_id} — {label}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("Taxonomy classifications:")
    if case.taxonomy_paths:
        for path in sorted(case.taxonomy_paths):
            entry = taxonomy.get(path)
            label = entry.label if entry else "(not in config/taxonomy.csv)"
            lines.append(f"  {path} — {label}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("Linked cases:")
    if linked:
        for association in linked:
            lines.append(
                f"  {association.case_id} ({association.title}) — "
                f"{'; '.join(association.reasons)}"
            )
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("Event timeline:")
    if events:
        lines.append(
            f"  {len(events)} event(s); first {events[0].timestamp_utc}, "
            f"last {events[-1].timestamp_utc}"
        )
        lines.append(f"  recent events (last {RECENT_EVENT_COUNT}):")
        for event in events[-RECENT_EVENT_COUNT:]:
            lines.append(
                f"    {event.timestamp_utc}  {event.actor}  "
                f"{event.event_type}  {event.detail}"
            )
    else:
        lines.append("  no events recorded")
    lines.append("")
    lines.append("Synopsis:")
    lines.append("  " + _plain_language_summary(case, categories, taxonomy, linked, events))
    return "\n".join(lines) + "\n"


def _plain_language_summary(
    case: cases.Case,
    categories: dict,
    taxonomy: dict,
    linked: list[entities.Association],
    events: list[cases.Event],
) -> str:
    """One paragraph of plain language composed from the case's own fields.

    Deterministic by construction: every list it renders is sorted (or,
    for events, in append order), and it mentions only what the record
    actually contains.
    """
    opening = f'Case {case.id} ("{case.title}") is {case.status}, opened {case.opened_utc}'
    if case.closed_utc:
        opening += f" and closed {case.closed_utc}"
    sentences = [opening + "."]

    if case.categories:
        labels = [
            categories[cid].label if cid in categories else cid
            for cid in sorted(case.categories)
        ]
        sentences.append(f"It is categorized as {_join(labels)}.")
    else:
        sentences.append("No categories are assigned.")

    if case.taxonomy_paths:
        rendered = [
            f"{path} ({taxonomy[path].label})" if path in taxonomy else path
            for path in sorted(case.taxonomy_paths)
        ]
        sentences.append(f"It is classified under {_join(rendered)}.")

    if linked:
        rendered = [
            f"{association.case_id} ({'; '.join(association.reasons)})"
            for association in linked
        ]
        sentences.append(f"It is associated with {_join(rendered)}.")
    else:
        sentences.append("It has no associated cases.")

    if events:
        sentences.append(
            f"{len(events)} event(s) are recorded, from {events[0].timestamp_utc} "
            f"to {events[-1].timestamp_utc}."
        )
    else:
        sentences.append("No events are recorded.")
    return " ".join(sentences)


def _join(items: list[str]) -> str:
    """English-list join: "a", "a and b", "a, b, and c"."""
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f", and {items[-1]}"
