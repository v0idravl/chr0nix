"""Command-line interface for casework: the console's case tool, scriptable.

Every capability the console's ``use casework`` exposes is reachable here
non-interactively — on a dumb terminal, on Windows, and from shell
scripts — over the exact same casework core functions. Where the console
holds context in a session (``set workspace`` / ``set actor`` / the
active case), this CLI takes it explicitly:

- the workspace comes from ``--workspace PATH`` or the
  ``CHR0NIX_WORKSPACE`` environment variable;
- the actor — required for anything that appends to an evidentiary log —
  comes from ``--actor NAME`` or ``CHR0NIX_ACTOR``;
- there is no "active case": every case-acting command takes the case id
  as an argument, so a scripted run never acts on an implicit default.

The console's YELLOW-tier gate maps to ``--ack``: the actions that
challenge in the console (status transitions to ``submitted`` /
``referred``, linking a subject, marking a statement signed) refuse to
run without ``--ack "<reason>"``, and the reason is appended to the
workspace's append-only ``attest.csv`` exactly as a console ``ack``
would record it.

Exit codes follow the suite convention: ``0`` success, ``2`` operational
error (uninitialized workspace, unknown case, invalid transition,
missing actor, refused append). ``main`` returns the code rather than
exiting so tests can drive the CLI in-process; only ``__main__`` calls
``sys.exit``.
"""

import argparse
import os
import sys
from pathlib import Path

from .. import tiers
from ..core import editor as core_editor
from ..errors import SuiteError, user_facing_errors
from . import cases, entities, export, intake, statements, synopsis, workspace as workspace_mod

#: Environment variables consulted when the matching option is absent.
WORKSPACE_ENV = "CHR0NIX_WORKSPACE"
ACTOR_ENV = "CHR0NIX_ACTOR"

#: Statuses that attest the case's accuracy to third parties — YELLOW in
#: the console, ``--ack``-gated here (see chr0nix/tiers.py).
_EXTERNAL_STATUSES = ("submitted", "referred")


def _common(*, suppress_defaults: bool) -> argparse.ArgumentParser:
    """The options every casework subcommand shares.

    Attached to the top-level parser *and* every subcommand, so
    ``--workspace`` / ``--actor`` may come before or after the
    subcommand. The subcommand copies use ``default=SUPPRESS`` so an
    unused subcommand-level flag never overwrites the value the top
    level already parsed (or its environment-variable default).
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--workspace",
        type=Path,
        default=argparse.SUPPRESS if suppress_defaults else os.environ.get(WORKSPACE_ENV),
        help=f"casework workspace directory (default: ${WORKSPACE_ENV})",
        metavar="PATH",
    )
    common.add_argument(
        "--actor",
        default=argparse.SUPPRESS if suppress_defaults else os.environ.get(ACTOR_ENV),
        help="who is acting, recorded in the event/custody logs "
        f"(default: ${ACTOR_ENV}); required by log-appending commands",
        metavar="NAME",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with every casework subcommand."""
    parser = argparse.ArgumentParser(
        prog="chr0nix case",
        description=(
            "Casework: case workspaces, cases, entities, evidence intake, "
            "statements, and synopses — the console's casework tool as a "
            "scriptable CLI. The workspace comes from --workspace or the "
            f"{WORKSPACE_ENV} environment variable; actions that append to a "
            f"log need --actor (or {ACTOR_ENV})."
        ),
        epilog="For lawful, authorized investigative documentation work only.",
        parents=[_common(suppress_defaults=False)],
    )
    common = _common(suppress_defaults=True)
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    init_parser = subparsers.add_parser(
        "init",
        parents=[common],
        help="create the workspace layout (config, entities, cases) with starter config",
        description="Initialize a casework workspace: config/ (commented, "
        "editable category and taxonomy vocabularies), entities/ (subject, "
        "vehicle, and link registries), and cases/. The directory is created "
        "if needed; an already-initialized workspace is refused.",
    )
    init_parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        help="workspace directory (default: --workspace)",
    )
    init_parser.set_defaults(func=_cmd_init)

    new_parser = subparsers.add_parser(
        "new",
        parents=[common],
        help="create a case (status draft)",
        description="Create a case in status draft and log its case-opened "
        "event. The case id must be slug-safe (lowercase letters, digits, "
        "hyphens): it becomes a directory name.",
    )
    new_parser.add_argument("case_id", help="slug-safe case id, e.g. case-2026-014")
    new_parser.add_argument("title", nargs="+", help="the case title (words are joined)")
    new_parser.set_defaults(func=_cmd_new)

    list_parser = subparsers.add_parser(
        "list",
        parents=[common],
        help="list all cases: id, status, category/link counts, title",
        description="Print the workspace case table plus a status-count "
        "summary — the same view as the console's `cases` and `run`.",
    )
    list_parser.set_defaults(func=_cmd_list)

    show_parser = subparsers.add_parser(
        "show",
        parents=[common],
        help="show a case's case.json fields and synopsis path",
        description="Print one case's record: id, title, status, categories, "
        "taxonomy paths, opened/closed timestamps, and synopsis path.",
    )
    show_parser.add_argument("case_id")
    show_parser.set_defaults(func=_cmd_show)

    status_parser = subparsers.add_parser(
        "status",
        parents=[common],
        help="advance a case along draft -> pending -> submitted -> referred -> closed",
        description="Move a case forward along the status chain (forward-only; "
        "closed is terminal). Transitions to submitted or referred attest the "
        "case's accuracy to third parties and require --ack.",
    )
    status_parser.add_argument("case_id")
    status_parser.add_argument(
        "new_status", choices=cases.STATUS_ORDER, metavar="new-status"
    )
    status_parser.add_argument(
        "--ack",
        metavar="REASON",
        help="attestation reason — required for submitted/referred; "
        "recorded in the workspace attest.csv",
    )
    status_parser.set_defaults(func=_cmd_status)

    categorize_parser = subparsers.add_parser(
        "categorize",
        parents=[common],
        help="attach a category defined in config/categories.csv",
        description="Attach a config-defined category to a case (idempotent).",
    )
    categorize_parser.add_argument("case_id")
    categorize_parser.add_argument("category_id")
    categorize_parser.set_defaults(func=_cmd_categorize)

    classify_parser = subparsers.add_parser(
        "classify",
        parents=[common],
        help="attach a taxonomy path defined in config/taxonomy.csv",
        description="Attach a config-defined taxonomy path to a case "
        "(verbatim membership; idempotent).",
    )
    classify_parser.add_argument("case_id")
    classify_parser.add_argument("taxonomy_path", metavar="taxonomy-path")
    classify_parser.set_defaults(func=_cmd_classify)

    entity_parser = subparsers.add_parser(
        "entity",
        parents=[common],
        help="manage the entity registries (subjects, vehicles)",
        description="Add to and list the shared entity registries under "
        "entities/: subjects.csv and vehicles.csv. (Case associations are "
        "`link` / `associations`.)",
    )
    entity_sub = entity_parser.add_subparsers(dest="entity_command", required=True, metavar="ACTION")

    entity_add = entity_sub.add_parser(
        "add",
        help="register a subject or vehicle (duplicate ids are rejected)",
        description="Register one entity. Linking an unknown subject/vehicle "
        "id also auto-registers it; this command is the explicit form for "
        "recording one ahead of any link. All profile fields are optional; "
        "multi-value fields (aliases, phones, emails, usernames, addresses) "
        "take comma-separated values.",
    )
    entity_add.add_argument("entity_type", choices=("subject", "vehicle"))
    entity_add.add_argument("entity_id", help="slug-safe entity id, e.g. subj-001")
    entity_add.add_argument("--nickname", default="", help="subject nickname (defaults to the id)")
    entity_add.add_argument("--descriptor", default="", help="subject descriptor summary")
    entity_add.add_argument("--aliases", default="", help="comma-separated aliases / nicknames")
    entity_add.add_argument("--date-of-birth", default="", help="YYYY-MM-DD (or partial)")
    entity_add.add_argument("--physical-description", default="", help="build, height, hair, marks")
    entity_add.add_argument("--phones", default="", help="comma-separated phone numbers")
    entity_add.add_argument("--emails", default="", help="comma-separated email addresses")
    entity_add.add_argument("--usernames", default="", help="comma-separated usernames / handles")
    entity_add.add_argument("--addresses", default="", help="comma-separated known addresses")
    entity_add.add_argument("--employer", default="", help="subject employer / workplace")
    entity_add.add_argument("--plate", default="", help="vehicle plate")
    entity_add.add_argument("--description", default="", help="vehicle description")
    entity_add.add_argument("--jurisdiction", default="", help="plate jurisdiction (state/province/country)")
    entity_add.add_argument("--vin", default="", help="vehicle identification number")
    entity_add.add_argument("--make", default="", help="vehicle make")
    entity_add.add_argument("--model", default="", help="vehicle model")
    entity_add.add_argument("--year", default="", help="vehicle model year")
    entity_add.add_argument("--color", default="", help="vehicle color")
    entity_add.add_argument("--body-style", default="", help="sedan, SUV, van, pickup, motorcycle, ...")
    entity_add.add_argument("--registered-owner", default="", help="registered owner as recorded")
    entity_add.add_argument("--notes", default="", help="free-text profile notes")
    entity_add.set_defaults(func=_cmd_entity_add)

    entity_set = entity_sub.add_parser(
        "set",
        help="update an entity's profile fields (field=value pairs)",
        description="Update one or more profile fields of a registered "
        "subject or vehicle — the CLI equivalent of the console's guided "
        "`subject edit` form. Field names are the registry columns; "
        "multi-value fields take comma-separated values.",
    )
    entity_set.add_argument("entity_type", choices=("subject", "vehicle"))
    entity_set.add_argument("entity_id")
    entity_set.add_argument(
        "pairs", nargs="+", metavar="field=value",
        help="profile updates (quote values with spaces); an empty value clears the field",
    )
    entity_set.set_defaults(func=_cmd_entity_set)

    entity_show = entity_sub.add_parser(
        "show",
        help="print an entity's profile card and linked cases",
        description="Print one subject or vehicle profile — the same aligned "
        "card the console's `subject show` / `vehicle show` renders — plus "
        "the cases the entity is linked to.",
    )
    entity_show.add_argument("entity_type", choices=("subject", "vehicle"))
    entity_show.add_argument("entity_id")
    entity_show.set_defaults(func=_cmd_entity_show)

    entity_list = entity_sub.add_parser(
        "list",
        help="list a registry: subjects | vehicles | links",
        description="Print one entity registry. `links` is the append-only "
        "association record (entities/links.csv), printed verbatim as rows.",
    )
    entity_list.add_argument("registry", choices=("subjects", "vehicles", "links"))
    entity_list.set_defaults(func=_cmd_entity_list)

    link_parser = subparsers.add_parser(
        "link",
        parents=[common],
        help="associate a subject/vehicle/case with a case",
        description="Append one association to entities/links.csv. Unknown "
        "subject/vehicle ids are auto-registered; case links require the "
        "target case to exist. Linking a subject asserts a person's "
        "involvement and requires --ack.",
    )
    link_parser.add_argument("case_id")
    link_parser.add_argument("entity_type", choices=entities.ENTITY_TYPES)
    link_parser.add_argument("entity_id")
    link_parser.add_argument("role", nargs="*", help="role/notes (words are joined)")
    link_parser.add_argument(
        "--ack",
        metavar="REASON",
        help="attestation reason — required when linking a subject; "
        "recorded in the workspace attest.csv",
    )
    link_parser.set_defaults(func=_cmd_link)

    associations_parser = subparsers.add_parser(
        "associations",
        parents=[common],
        help="show cases associated with a case, with reasons",
        description="Compute one case's associations from links.csv: shared "
        "subjects/vehicles and direct case-to-case links, each with the "
        "reason shown.",
    )
    associations_parser.add_argument("case_id")
    associations_parser.set_defaults(func=_cmd_associations)

    event_parser = subparsers.add_parser(
        "event",
        parents=[common],
        help="append an event to a case's append-only log",
        description="Append one row (timestamp, actor, event-type, detail) to "
        "cases/<id>/events.csv.",
    )
    event_parser.add_argument("case_id")
    event_parser.add_argument("event_type")
    event_parser.add_argument("detail", nargs="+", help="event detail (words are joined)")
    event_parser.set_defaults(func=_cmd_event)

    inbox_parser = subparsers.add_parser(
        "inbox",
        parents=[common],
        help="list unfiled items in the workspace evidence inbox",
        description="List what has been dropped into <workspace>/inbox/ but "
        "not yet filed into a case.",
    )
    inbox_parser.set_defaults(func=_cmd_inbox)

    file_parser = subparsers.add_parser(
        "file",
        parents=[common],
        help="file inbox items into a case's exhibits (no names = all)",
        description="Move inbox items into cases/<id>/exhibits/, re-manifest "
        "the exhibits with cust0dia (CSV + JSON), and append one "
        "hash-anchored COLLECTED custody row per item.",
    )
    file_parser.add_argument("case_id")
    file_parser.add_argument("names", nargs="*", help="inbox item names (default: everything)")
    file_parser.set_defaults(func=_cmd_file)

    statement_parser = subparsers.add_parser(
        "statement",
        parents=[common],
        help="record, sign, and list interview statements",
        description="Statements live in cases/<id>/statements.csv, append-only: "
        "a status change is a new row under the same statement id, never an "
        "edit. Signing requires --ack — claiming a signed statement exists is "
        "a legally significant attestation.",
    )
    statement_sub = statement_parser.add_subparsers(
        dest="statement_command", required=True, metavar="ACTION"
    )

    statement_record = statement_sub.add_parser(
        "record", help="record an interview statement (status: recorded)",
        description="Record an interview statement. The CSV row carries who, "
        "role, status, and one-line notes; the long-form body lives in "
        "cases/<id>/statements/<statement-id>.txt. Without --body or "
        "--body-file, an interactive terminal opens $VISUAL/$EDITOR "
        "(fallback: nvim, then vi) to compose it; scripted runs (no TTY) "
        "record without a body.",
    )
    statement_record.add_argument("case_id")
    statement_record.add_argument("statement_id", help="slug-safe, unique per case")
    statement_record.add_argument("interviewee")
    statement_record.add_argument("role")
    statement_record.add_argument("notes", nargs="*", help="(words are joined)")
    statement_record.add_argument(
        "--body", metavar="TEXT", default=None,
        help="the full statement body (stored as statements/<id>.txt)",
    )
    statement_record.add_argument(
        "--body-file", metavar="PATH", type=Path, default=None,
        help="read the statement body from a file (scripting escape hatch)",
    )
    statement_record.set_defaults(func=_cmd_statement_record)

    statement_sign = statement_sub.add_parser(
        "sign", help="mark a recorded statement signed (requires --ack)"
    )
    statement_sign.add_argument("case_id")
    statement_sign.add_argument("statement_id")
    statement_sign.add_argument(
        "--ack",
        metavar="REASON",
        help="attestation reason — required; recorded in the workspace attest.csv",
    )
    statement_sign.set_defaults(func=_cmd_statement_sign)

    statement_list = statement_sub.add_parser(
        "list", help="list a case's statements with current status"
    )
    statement_list.add_argument("case_id")
    statement_list.set_defaults(func=_cmd_statement_list)

    synopsis_parser = subparsers.add_parser(
        "synopsis",
        parents=[common],
        help="regenerate and print a case's synopsis.txt",
        description="Rebuild cases/<id>/synopsis.txt deterministically from "
        "the case record, event log, config vocabularies, and association "
        "graph, then print it.",
    )
    synopsis_parser.add_argument("case_id")
    synopsis_parser.set_defaults(func=_cmd_synopsis)

    export_parser = subparsers.add_parser(
        "export",
        parents=[common],
        help="assemble a case's sealed export bundle (self-manifested)",
        description="Assemble the case's record — case.json, events, "
        "statements (with bodies), linked entity profiles, the links.csv "
        "excerpt, the exhibits manifest and custody log, any timeline / "
        "h4ndl3 / m3talex outputs under the case directory, and the "
        "workspace attestation log — into <out>/<case-id>-export-<utc-stamp>/ "
        "with a generated CASE-REPORT.md, then self-seal the bundle with a "
        "cust0dia manifest of itself. Read-only on the workspace; the "
        "evidence bytes under exhibits/ are referenced, never copied.",
    )
    export_parser.add_argument("case_id")
    export_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="DIR",
        help="output root for the bundle (default: <workspace>/exports)",
    )
    export_parser.set_defaults(func=_cmd_export)

    return parser


def _workspace(args: argparse.Namespace) -> Path:
    """The initialized workspace from --workspace / the environment."""
    value = getattr(args, "workspace", None)  # SUPPRESS when unused
    if value is None:
        raise SuiteError(
            f"no workspace given (pass --workspace PATH or set {WORKSPACE_ENV})"
        )
    path = Path(value).expanduser()
    if not path.is_dir():
        raise SuiteError(f"workspace directory does not exist: {path}")
    return workspace_mod.require_workspace(path)


def _actor(args: argparse.Namespace) -> str:
    """The acting person, required by every log-appending command."""
    value = getattr(args, "actor", None)  # SUPPRESS when unused
    if not value:
        raise SuiteError(
            f"actor is required for this command (pass --actor NAME or set "
            f"{ACTOR_ENV}) — it is recorded in the case's logs"
        )
    return workspace_mod.clean_field(value, "actor", required=True)


def _ack(args: argparse.Namespace, workspace: Path, actor: str, action: str, rationale: str) -> None:
    """The YELLOW-tier gate, non-interactively.

    The console answers a YELLOW action with a challenge and runs it only
    after ``ack <reason>``; here the equivalent is refusing to run without
    ``--ack REASON``. The attestation lands in the workspace's append-only
    attest.csv, exactly as the console records it.
    """
    if args.ack is None:
        raise SuiteError(
            f"YELLOW — {rationale}. Re-run with --ack \"<reason>\"; the reason "
            "is recorded with a timestamp in the workspace attestation log."
        )
    tiers.append_attestation(workspace, actor=actor, action=action, reason=args.ack)


def _cmd_init(args: argparse.Namespace) -> int:
    directory = args.directory or getattr(args, "workspace", None)
    if directory is None:
        raise SuiteError(
            f"usage: chr0nix case init <directory> (or --workspace PATH / ${WORKSPACE_ENV})"
        )
    path = Path(directory).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    written = workspace_mod.init_workspace(path)
    print(f"initialized casework workspace at {path.resolve()}")
    for written_path in written:
        print(f"wrote {written_path}")
    print("next: chr0nix case new <case-id> <title...>")
    return 0


def _cmd_new(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    case = cases.create_case(workspace, args.case_id, " ".join(args.title), _actor(args))
    print(f"created case {case.id} (draft)")
    print(
        f"next: classify {case.id} <taxonomy-path> · categorize {case.id} <category-id> · "
        f"drop evidence in {workspace / 'inbox'} and `file {case.id}`"
    )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    print(cases.render_case_table(workspace))
    print(cases.render_status_summary(workspace))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    case = cases.load_case(workspace, args.case_id)
    synopsis_path = workspace_mod.case_dir(workspace, case.id) / "synopsis.txt"
    synopsis_text = str(synopsis_path) if synopsis_path.is_file() else "(not generated yet)"
    lines = [
        f"id:             {case.id}",
        f"title:          {case.title}",
        f"status:         {case.status}",
        f"categories:     {', '.join(case.categories) or '(none)'}",
        f"taxonomy_paths: {', '.join(case.taxonomy_paths) or '(none)'}",
        f"opened_utc:     {case.opened_utc}",
        f"closed_utc:     {case.closed_utc or '(open)'}",
        f"synopsis:       {synopsis_text}",
    ]
    print("\n".join(lines))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    actor = _actor(args)
    if args.new_status in _EXTERNAL_STATUSES:
        _ack(
            args, workspace, actor,
            action=f"case status {args.case_id} {args.new_status}",
            rationale="marking a case submitted or referred attests its "
            "accuracy to third parties",
        )
    case = cases.transition_status(workspace, args.case_id, args.new_status, actor)
    suffix = f" (closed {case.closed_utc})" if case.closed_utc else ""
    print(f"{case.id}: status -> {case.status}{suffix}")
    return 0


def _cmd_categorize(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    case, changed = cases.attach_category(workspace, args.case_id, args.category_id)
    verb = "categorized" if changed else "already categorized"
    print(f"{case.id}: {verb} as {args.category_id}")
    return 0


def _cmd_classify(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    case, changed = cases.attach_taxonomy(workspace, args.case_id, args.taxonomy_path)
    verb = "classified" if changed else "already classified"
    print(f"{case.id}: {verb} under {args.taxonomy_path}")
    return 0


def _multi(value: str) -> list[str]:
    """A comma-separated CLI option value as a multi-field entry list."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _cmd_entity_add(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    if args.entity_type == "subject":
        subject = entities.register_subject(
            workspace, args.entity_id,
            nickname=args.nickname, descriptor_summary=args.descriptor,
            aliases=_multi(args.aliases), date_of_birth=args.date_of_birth,
            physical_description=args.physical_description,
            phones=_multi(args.phones), emails=_multi(args.emails),
            usernames=_multi(args.usernames), addresses=_multi(args.addresses),
            employer=args.employer, notes=args.notes,
        )
        print(f"registered subject {subject.subject_id} ({subject.nickname})")
        print(entities.render_subject_card(subject))
    else:
        vehicle = entities.register_vehicle(
            workspace, args.entity_id,
            plate=args.plate, description=args.description,
            jurisdiction=args.jurisdiction, vin=args.vin, make=args.make,
            model=args.model, year=args.year, color=args.color,
            body_style=args.body_style, registered_owner=args.registered_owner,
            notes=args.notes,
        )
        detail = f" ({vehicle.plate})" if vehicle.plate else ""
        print(f"registered vehicle {vehicle.vehicle_id}{detail}")
        print(entities.render_vehicle_card(vehicle))
    return 0


def _cmd_entity_set(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    if args.entity_type == "subject":
        field_names = entities.SUBJECT_PROFILE_FIELD_NAMES
        multi_fields = {
            f.name for f in entities.SUBJECT_PROFILE_FIELDS if f.multi
        }
        update = entities.update_subject
        card = entities.render_subject_card
    else:
        field_names = entities.VEHICLE_PROFILE_FIELD_NAMES
        multi_fields = {
            f.name for f in entities.VEHICLE_PROFILE_FIELDS if f.multi
        }
        update = entities.update_vehicle
        card = entities.render_vehicle_card
    changes: dict[str, object] = {}
    for token in args.pairs:
        field, separator, value = token.partition("=")
        if not separator:
            raise SuiteError(
                f"expected field=value, got {token!r} "
                f"(profile fields: {', '.join(field_names)})"
            )
        if field not in field_names:
            raise SuiteError(
                f"unknown {args.entity_type} field {field!r}; "
                f"profile fields: {', '.join(field_names)}"
            )
        changes[field] = _multi(value) if field in multi_fields else value
    entity = update(workspace, args.entity_id, **changes)
    print(f"updated {args.entity_type} {args.entity_id}")
    print(card(entity))
    return 0


def _cmd_entity_show(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    if args.entity_type == "subject":
        entity = entities.get_subject(workspace, args.entity_id)
        print(entities.render_subject_card(entity))
    else:
        entity = entities.get_vehicle(workspace, args.entity_id)
        print(entities.render_vehicle_card(entity))
    linked = sorted(
        link.case_id
        for link in entities.read_links(workspace)
        if link.entity_type == args.entity_type and link.entity_id == args.entity_id
    )
    print(f"  linked cases: {', '.join(linked) if linked else '(none)'}")
    return 0


def _cmd_entity_list(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    if args.registry == "subjects":
        subjects = entities.read_subjects(workspace)
        if not subjects:
            print("no subjects registered")
            return 0
        lines = [f"{'subject_id':<20}{'nickname':<24}descriptor_summary"]
        lines += [
            f"{s.subject_id:<20}{s.nickname:<24}{s.descriptor_summary}" for s in subjects
        ]
    elif args.registry == "vehicles":
        vehicles = entities.read_vehicles(workspace)
        if not vehicles:
            print("no vehicles registered")
            return 0
        lines = [f"{'vehicle_id':<20}{'plate':<16}description"]
        lines += [f"{v.vehicle_id:<20}{v.plate:<16}{v.description}" for v in vehicles]
    else:
        links = entities.read_links(workspace)
        if not links:
            print("no links recorded")
            return 0
        lines = [f"{'case_id':<20}{'entity_type':<13}{'entity_id':<20}{'role':<16}notes"]
        lines += [
            f"{link.case_id:<20}{link.entity_type:<13}{link.entity_id:<20}"
            f"{link.role:<16}{link.notes}"
            for link in links
        ]
    print("\n".join(lines))
    return 0


def _cmd_link(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    role = " ".join(args.role)
    if args.entity_type == "subject":
        _ack(
            args, workspace, _actor(args),
            action=f"case link {args.case_id} subject {args.entity_id}",
            rationale="associating a person (a subject) across cases — lawful "
            "only for authorized casework",
        )
    registered = entities.append_link(
        workspace, args.case_id, args.entity_type, args.entity_id, role
    )
    message = f"linked {args.case_id} -> {args.entity_type} {args.entity_id}"
    if registered:
        message += f" (auto-registered {args.entity_type} {args.entity_id})"
    print(message)
    return 0


def _cmd_associations(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    found = entities.associations(workspace, args.case_id)
    if not found:
        print(f"{args.case_id}: no associated cases")
        return 0
    print(f"associations for {args.case_id}:")
    for association in found:
        print(f"  {association.case_id:<20}{'; '.join(association.reasons)}")
    return 0


def _cmd_event(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    cases.append_event(
        workspace, args.case_id, actor=_actor(args),
        event_type=args.event_type, detail=" ".join(args.detail),
    )
    print(f"event logged on {args.case_id} ({args.event_type})")
    return 0


def _cmd_inbox(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    items = intake.list_inbox(workspace)
    if not items:
        print(f"inbox is empty (drop files into {workspace / 'inbox'})")
        return 0
    print(f"{len(items)} unfiled item(s) in {workspace / 'inbox'}:")
    for item in items:
        print(f"  {item}")
    return 0


def _cmd_file(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    filed = intake.file_evidence(
        workspace, args.case_id, args.names, actor=_actor(args)
    )
    print(f"filed {len(filed)} item(s) into {args.case_id}'s exhibits:")
    for name in filed:
        print(f"  {name}")
    print("manifest + custody log updated (COLLECTED, hash-anchored)")
    print(f"next: synopsis {args.case_id}")
    return 0


def _statement_body(args: argparse.Namespace) -> str:
    """The statement body: --body, --body-file, the editor, or nothing.

    The editor opens only on an interactive terminal with no explicit
    body source — a scripted run (piped stdin, CI) must never block on
    an editor, so it records without a body, exactly as before.
    """
    if args.body is not None and args.body_file is not None:
        raise SuiteError("pass only one of --body / --body-file")
    if args.body is not None:
        return args.body
    if args.body_file is not None:
        path = Path(args.body_file).expanduser()
        if not path.is_file():
            raise SuiteError(f"body file does not exist: {path}")
        return path.read_text(encoding="utf-8")
    if sys.stdin.isatty():
        return core_editor.edit_text(
            what=f"statement {args.statement_id} body",
            instructions=(
                f"Compose the full statement body for {args.statement_id} "
                f"({args.interviewee}, {args.role}).",
                "Lines starting with # are instructions and are never saved.",
                "Save and exit to record; exit without saving to record with no body.",
            ),
        ) or ""
    return ""


def _cmd_statement_record(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    statement = statements.record_statement(
        workspace, args.case_id, args.statement_id,
        interviewee=args.interviewee, role=args.role, notes=" ".join(args.notes),
        body=_statement_body(args),
        actor=_actor(args),
    )
    print(
        f"recorded statement {statement.statement_id} on {args.case_id} "
        f"({statement.interviewee}, {statement.role}) — status: recorded"
    )
    body = statements.body_path(workspace, args.case_id, statement.statement_id)
    if body.is_file():
        print(f"body: {body}")
    return 0


def _cmd_statement_sign(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    actor = _actor(args)
    _ack(
        args, workspace, actor,
        action=f"case statement sign {args.case_id} {args.statement_id}",
        rationale="claiming a signed statement exists is a legally significant "
        "attestation",
    )
    statement = statements.sign_statement(
        workspace, args.case_id, args.statement_id, actor=actor
    )
    print(f"statement {statement.statement_id} on {args.case_id} marked signed")
    return 0


def _cmd_statement_list(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    case_statements = statements.list_statements(workspace, args.case_id)
    if not case_statements:
        print(f"{args.case_id}: no statements recorded")
        return 0
    lines = [f"{'statement':<20}{'status':<10}{'interviewee':<24}role"]
    lines += [
        f"{s.statement_id:<20}{s.status:<10}{s.interviewee:<24}{s.role}"
        for s in case_statements
    ]
    print("\n".join(lines))
    return 0


def _cmd_synopsis(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    path = synopsis.regenerate_synopsis(workspace, args.case_id)
    print(f"wrote {path}")
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    workspace = _workspace(args)
    # Export is a read-only copy operation (GREEN in the console): the
    # actor is optional and only recorded in the report header.
    actor = getattr(args, "actor", None) or ""
    bundle = export.export_case(workspace, args.case_id, args.out, actor=actor)
    print(f"exported case {args.case_id} -> {bundle}")
    print("sealed: manifest.csv + manifest.json written at the bundle root")
    print(f"verify with: chr0nix verify {bundle / 'manifest.json'} {bundle}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch; return the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError,) + user_facing_errors() as exc:
        # Expected, user-fixable failures get a clean one-line message;
        # tracebacks are reserved for genuine bugs.
        print(f"chr0nix case: error: {exc}", file=sys.stderr)
        return 2
