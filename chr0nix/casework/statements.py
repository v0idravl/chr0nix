"""Interview statements: recorded, and marked signed.

Attorneys and investigators track two facts about every interview
statement: that it exists (who, about what, recorded when, by whom) and
whether a *signed* statement was obtained. Both live in
``cases/<case-id>/statements.csv``:

    statement_id,timestamp_utc,interviewee,role,status,notes

The file is append-only, like every evidentiary CSV in the suite: a
status change is a *new row* under the same ``statement_id`` (with a
new timestamp), never an edit of the old one. The current state of a
statement is its latest row; the file itself is the full history of
how it got there — ``recorded`` first, ``signed`` when the signature
is obtained.

Marking a statement signed is a legally significant claim, so the
console tiers ``statement-sign`` YELLOW: it only executes through the
attested ack flow, and the ack lands in the workspace's ``attest.csv``
alongside the row appended here.

A statement's long-form *body* does not fit the one-record-one-line CSV
rule, so it lives beside the log as
``cases/<case-id>/statements/<statement-id>.txt``, written once at
record time (usually composed in the terminal editor via the console's
``:edit`` handoff or the CLI's default when no ``--body`` is given).
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from chr0nix.core import timeutil

from . import CaseworkError
from .cases import append_event, load_case
from .workspace import append_csv_row, case_dir, clean_field, validate_slug

#: cases/<case-id>/statements.csv columns, in canonical order.
STATEMENT_FIELDS = ("statement_id", "timestamp_utc", "interviewee", "role", "status", "notes")

#: The statement lifecycle. ``recorded`` is the only valid initial
#: status; ``signed`` is terminal (a signature cannot be unsigned).
STATUS_RECORDED = "recorded"
STATUS_SIGNED = "signed"


@dataclass(frozen=True)
class Statement:
    """One row of statements.csv."""

    statement_id: str
    timestamp_utc: str
    interviewee: str
    role: str
    status: str
    notes: str


def _log_path(workspace: Path, case_id: str) -> Path:
    return case_dir(workspace, case_id) / "statements.csv"


def body_path(workspace: Path, case_id: str, statement_id: str) -> Path:
    """Where a statement's long-form body lives: cases/<id>/statements/<stmt>.txt.

    The CSV row carries the facts (who, role, status, short notes); the
    verbatim body — composed in the terminal editor — is a text file
    beside it, named by the slug-safe statement id.
    """
    statement_id = validate_slug(statement_id, "statement id")
    return case_dir(workspace, case_id) / "statements" / f"{statement_id}.txt"


def read_statements(workspace: Path, case_id: str) -> list[Statement]:
    """Read statements.csv defensively, in recorded (append) order."""
    path = _log_path(workspace, case_id)
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise CaseworkError(f"statement log {path} is empty") from None
        if tuple(header) != STATEMENT_FIELDS:
            raise CaseworkError(
                f"statement log {path} has unexpected header {header!r}; "
                f"expected {list(STATEMENT_FIELDS)!r}"
            )
        statements = []
        for line_no, row in enumerate(reader, start=2):
            if len(row) != len(STATEMENT_FIELDS):
                raise CaseworkError(
                    f"statement log {path}, line {line_no}: "
                    f"expected {len(STATEMENT_FIELDS)} fields, got {len(row)}"
                )
            statements.append(Statement(*row))
    return statements


def latest_status(workspace: Path, case_id: str, statement_id: str) -> Statement | None:
    """The current (latest) row for ``statement_id``, or None if unknown."""
    current: Statement | None = None
    for statement in read_statements(workspace, case_id):
        if statement.statement_id == statement_id:
            current = statement
    return current


def record_statement(
    workspace: Path,
    case_id: str,
    statement_id: str,
    *,
    interviewee: str,
    role: str,
    notes: str,
    body: str = "",
    actor: str,
) -> Statement:
    """Record a new interview statement in status ``recorded``.

    Statement ids are unique per case: a second ``recorded`` row under
    an existing id would fork its history, so it is rejected. Signing
    is a separate, attested step — see :func:`sign_statement`.

    ``body`` is the long-form statement text (typically composed in the
    terminal editor). It is too big and too free-form for the
    single-line CSV, so it is written verbatim to
    :func:`body_path` and the CSV row's ``notes`` stay a one-line
    summary.
    """
    load_case(workspace, case_id)
    statement_id = validate_slug(statement_id, "statement id")
    if latest_status(workspace, case_id, statement_id) is not None:
        raise CaseworkError(
            f"statement {statement_id!r} already exists on case {case_id} "
            "(statement ids are unique per case)"
        )
    statement = Statement(
        statement_id=statement_id,
        timestamp_utc=timeutil.utc_now(),
        interviewee=clean_field(interviewee, "interviewee", required=True),
        role=clean_field(role, "role", required=True),
        status=STATUS_RECORDED,
        notes=clean_field(notes, "notes", required=False),
    )
    append_csv_row(
        _log_path(workspace, case_id), STATEMENT_FIELDS,
        [statement.statement_id, statement.timestamp_utc, statement.interviewee,
         statement.role, statement.status, statement.notes],
    )
    detail = f"statement {statement_id}: {statement.interviewee} ({statement.role})"
    if body.strip():
        path = body_path(workspace, case_id, statement_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
        detail += f" — body: statements/{statement_id}.txt"
    append_event(
        workspace, case_id, actor=clean_field(actor, "actor", required=True),
        event_type="statement-recorded",
        detail=detail,
    )
    return statement


def sign_statement(
    workspace: Path, case_id: str, statement_id: str, *, actor: str
) -> Statement:
    """Mark a recorded statement ``signed`` by appending a new row.

    Only a statement whose latest row is ``recorded`` can be signed;
    signing an unknown or already-signed statement is rejected. The
    console tiers this action YELLOW — claiming a signed statement
    exists is a legally significant attestation, and the ack reason is
    recorded in the workspace attestation log.
    """
    load_case(workspace, case_id)
    statement_id = validate_slug(statement_id, "statement id")
    current = latest_status(workspace, case_id, statement_id)
    if current is None:
        raise CaseworkError(
            f"unknown statement {statement_id!r} on case {case_id} "
            "(record it first with: statement)"
        )
    if current.status == STATUS_SIGNED:
        raise CaseworkError(f"statement {statement_id!r} is already signed")
    signed = Statement(
        statement_id=statement_id,
        timestamp_utc=timeutil.utc_now(),
        interviewee=current.interviewee,
        role=current.role,
        status=STATUS_SIGNED,
        notes=current.notes,
    )
    append_csv_row(
        _log_path(workspace, case_id), STATEMENT_FIELDS,
        [signed.statement_id, signed.timestamp_utc, signed.interviewee,
         signed.role, signed.status, signed.notes],
    )
    append_event(
        workspace, case_id, actor=clean_field(actor, "actor", required=True),
        event_type="statement-signed",
        detail=f"statement {statement_id} signed ({current.interviewee})",
    )
    return signed


def list_statements(workspace: Path, case_id: str) -> list[Statement]:
    """The latest row of every statement on the case, sorted by id."""
    latest: dict[str, Statement] = {}
    for statement in read_statements(workspace, case_id):
        latest[statement.statement_id] = statement
    return [latest[key] for key in sorted(latest)]
