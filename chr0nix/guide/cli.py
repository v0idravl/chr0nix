"""Command-line interface for guide: the research-method catalogue, scriptable.

The console's ``use guide`` tool (``methods`` / ``hint`` / ``capture``)
as a non-interactive CLI — same catalogue, same rendering, same capture
validation, from :mod:`chr0nix.guide.methods`:

- ``list`` prints the catalogue, grouped by category and tier-marked.
- ``show`` prints one method's full guidance: ordered high-ROI steps,
  browser handoff URLs (rendered with the query when one is given — the
  suite prints URLs, it never opens them), and the capture vocabulary.
- ``capture`` records a method's findings into a case's append-only
  ``events.csv`` as an ``osint-finding`` event, validated against the
  method's capture fields.

``capture`` writes into the casework record, so it needs what the console
session would hold: ``--workspace PATH`` (or ``CHR0NIX_WORKSPACE``),
``--case ID`` (there is no "active case" outside the console), and
``--actor NAME`` (or ``CHR0NIX_ACTOR``). Capturing a YELLOW-tier method —
person-focused identifier research — additionally requires
``--ack "<reason>"``, the non-interactive form of the console's
challenge/ack flow; the reason is recorded in the workspace attest.csv.

Exit codes: ``0`` success, ``2`` operational error (unknown method,
unknown capture field, missing workspace/case/actor). ``main`` returns
the code rather than exiting so tests can drive the CLI in-process.
"""

import argparse
import os
import sys
from pathlib import Path

from .. import tiers
from ..casework import cases, workspace as workspace_mod
from ..errors import SuiteError, user_facing_errors
from . import methods

#: Environment variables consulted when the matching option is absent.
WORKSPACE_ENV = "CHR0NIX_WORKSPACE"
ACTOR_ENV = "CHR0NIX_ACTOR"


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with the three guide subcommands."""
    parser = argparse.ArgumentParser(
        prog="chr0nix guide",
        description=(
            "The offline research-method knowledge base: what to check, "
            "where (browser handoffs printed, never opened), and a capture "
            "flow that records findings into a case's event log."
        ),
        epilog="For lawful, authorized investigative documentation work only.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    list_parser = subparsers.add_parser(
        "list",
        help="list all research methods, grouped by category",
        description="Print the method catalogue, grouped by category, with "
        "YELLOW-tier (person-focused) methods marked.",
    )
    list_parser.set_defaults(func=_cmd_list)

    show_parser = subparsers.add_parser(
        "show",
        help="print a method's guidance: steps, handoff URLs, capture fields",
        description="Print one method's ordered steps (high-ROI first), its "
        "browser handoff URL templates — rendered with the query when one is "
        "given — and the field vocabulary `capture` accepts.",
    )
    show_parser.add_argument("method_id", help="a method id from `list`")
    show_parser.add_argument(
        "query", nargs="*", help="rendered into {query} handoff placeholders"
    )
    show_parser.set_defaults(func=_cmd_show)

    capture_parser = subparsers.add_parser(
        "capture",
        help="record a method's findings into a case's event log",
        description="Append an osint-finding event to the case's append-only "
        "events.csv. Field names must come from the method's capture "
        "vocabulary (`show <method-id>` lists them). YELLOW-tier methods "
        "require --ack.",
    )
    capture_parser.add_argument("method_id", help="a method id from `list`")
    capture_parser.add_argument(
        "pairs", nargs="+", metavar="field=value",
        help="findings as <field>=<value> pairs (quote values with spaces)",
    )
    capture_parser.add_argument(
        "--workspace",
        type=Path,
        default=os.environ.get(WORKSPACE_ENV),
        required=os.environ.get(WORKSPACE_ENV) is None,
        help=f"casework workspace directory (default: ${WORKSPACE_ENV})",
        metavar="PATH",
    )
    capture_parser.add_argument(
        "--case",
        dest="case_id",
        required=True,
        help="the case to record into (there is no active case outside the console)",
        metavar="ID",
    )
    capture_parser.add_argument(
        "--actor",
        default=os.environ.get(ACTOR_ENV),
        help=f"who is recording, stored in the event row (default: ${ACTOR_ENV})",
        metavar="NAME",
    )
    capture_parser.add_argument(
        "--ack",
        metavar="REASON",
        help="attestation reason — required for YELLOW (person-focused) "
        "methods; recorded in the workspace attest.csv",
    )
    capture_parser.set_defaults(func=_cmd_capture)

    return parser


def _cmd_list(args: argparse.Namespace) -> int:
    print(methods.render_listing())
    print(
        f"{len(methods.METHODS)} method(s) — `show <method-id>` for guidance; "
        "`capture` records findings into a case"
    )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    method = methods.lookup_method(args.method_id)
    query = " ".join(args.query).strip() or None
    print(methods.render_hint(method, query))
    return 0


def _cmd_capture(args: argparse.Namespace) -> int:
    method = methods.lookup_method(args.method_id)
    path = Path(args.workspace).expanduser()
    if not path.is_dir():
        raise SuiteError(f"workspace directory does not exist: {path}")
    workspace = workspace_mod.require_workspace(path)
    if not args.actor:
        raise SuiteError(
            f"actor is required (pass --actor NAME or set {ACTOR_ENV}) — "
            "it is recorded in the event row"
        )
    actor = workspace_mod.clean_field(args.actor, "actor", required=True)
    if method.tier == tiers.YELLOW:
        if args.ack is None:
            raise SuiteError(
                f"YELLOW — recording person-focused research findings about an "
                f"identifier — lawful only for authorized casework. Re-run with "
                f"--ack \"<reason>\"; the reason is recorded with a timestamp in "
                f"the workspace attestation log."
            )
        tiers.append_attestation(
            workspace, actor=actor,
            action=f"guide capture {method.id}", reason=args.ack,
        )
    pairs = methods.parse_capture_pairs(method, args.pairs)
    cases.load_case(workspace, args.case_id)
    cases.append_event(
        workspace, args.case_id, actor=actor, event_type="osint-finding",
        detail=methods.capture_detail(method, pairs),
    )
    print(f"recorded osint-finding on {args.case_id} ({method.id})")
    if method.related:
        print(
            "related methods: "
            + ", ".join(methods.lookup_method(mid).id for mid in method.related)
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch; return the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError,) + user_facing_errors() as exc:
        # Expected, user-fixable failures get a clean one-line message;
        # tracebacks are reserved for genuine bugs.
        print(f"chr0nix guide: error: {exc}", file=sys.stderr)
        return 2
