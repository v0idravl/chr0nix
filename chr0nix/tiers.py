"""Legal-risk tiers and the attestation log.

Every console action carries a legal-risk tier:

- **GREEN** — pure offline documentation, always lawful. Reading
  evidence, hashing, listing, generating local reports. The large
  majority of commands.
- **YELLOW** — lawful only under specific circumstances. Researching an
  identifier tied to a person, associating a person across cases,
  marking a case submitted or referred to third parties. A YELLOW
  action does not run when typed: the command layer answers with a
  *challenge* (what, why it's yellow, and the legal weight), and the
  action runs only after the operator confirms with ``ack
  <reason...>``. The reason is recorded, timestamped and attributed to
  the session actor, in an append-only attestation log.
- **RED** — reserved for future use. The tier is defined so the
  vocabulary is stable; nothing is assigned to it yet.

A command's tier is usually a constant, but may be a callable of the
command's arguments resolved at dispatch time: casework ``status`` is
YELLOW only when the target status is ``submitted`` or ``referred``
(attesting accuracy to third parties), and casework ``link`` only when
the entity is a ``subject`` (associating a person across cases).
Argument-dependent tiers keep the friction proportionate — the internal
statuses (draft, pending, closed) and vehicle/case links stay GREEN.

The attestation log is ``attest.csv`` at the workspace root — not
per-case, because YELLOW actions span tools (h4ndl3 and casework so
far). It follows :mod:`cust0dia.custody`'s append-only pattern exactly:
a stable header validated before every append, control characters
rejected in free-text fields (one attestation is one line; a newline in
a field would smuggle in forged rows), and the only write ever
performed is adding bytes at the end of the file. Columns:
``timestamp_utc,actor,action,reason``.

Attestation requires a workspace: there is no other place the record
could live that the operator deliberately chose. A YELLOW action with
no workspace set is a clean error, never a silent skip.
"""

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cust0dia import timeutil

from .errors import SuiteError

#: Pure offline documentation; always lawful.
GREEN = "green"

#: Lawful only under specific circumstances; requires an acknowledged,
#: recorded reason (see the module docstring).
YELLOW = "yellow"

#: Reserved for future use. Defined so the vocabulary is stable;
#: no command is assigned this tier yet.
RED = "red"

#: A command's tier: a constant, or a callable resolving it from the
#: command's argument list at dispatch time.
TierSpec = str | Callable[[list[str]], str]

#: Attestation log filename, at the workspace root.
ATTEST_FILENAME = "attest.csv"

#: attest.csv columns, in canonical order.
ATTEST_FIELDS = ("timestamp_utc", "actor", "action", "reason")


@dataclass(frozen=True)
class PendingAction:
    """A YELLOW action that has been challenged and awaits ``ack``.

    The session holds at most one: a challenge sets it, ``ack``
    consumes it, and any other command clears it, so a stale challenge
    can never be confirmed by accident hours later.
    """

    #: The raw typed line, re-dispatched (with the tier check bypassed)
    #: when the operator acks.
    line: str
    #: The canonical action label written to the attestation log:
    #: "<tool> <typed line>".
    action: str
    #: Why the action is yellow, as shown in the challenge.
    rationale: str


def resolve_tier(spec: TierSpec, args: list[str]) -> str:
    """The effective tier of a command invocation.

    Constants pass through; callables are resolved against the
    command's arguments, so ``status case-1 pending`` and ``status
    case-1 submitted`` can carry different tiers.
    """
    return spec(args) if callable(spec) else spec


def is_yellow_capable(spec: TierSpec) -> bool:
    """True if the spec is YELLOW, or a callable that may resolve to it.

    Used for the ``[yellow]`` markers in ``help`` and ``show tools``: an
    argument-dependent tier is annotated because it *can* challenge,
    even when the current arguments would resolve GREEN.
    """
    return callable(spec) or spec == YELLOW


def validate_reason(reason: str) -> str:
    """Validate an ``ack`` reason; return it stripped.

    The same rule as the custody log's free-text fields: non-empty, and
    no control characters — one attestation is one line.
    """
    cleaned = reason.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise SuiteError("reason must not contain control characters")
    if not cleaned:
        raise SuiteError("a reason is required (usage: ack <reason...>)")
    return cleaned


def append_attestation(
    workspace: Path, *, actor: str, action: str, reason: str
) -> None:
    """Append one attestation row to <workspace>/attest.csv.

    :func:`cust0dia.custody.append_custody_row`'s pattern: an existing
    non-empty file's header must match exactly (we refuse to append to
    a file we did not create), free-text fields are control-character
    checked, and the write is append mode only. The reason is
    re-validated here so the log's integrity never depends on the
    caller having checked.
    """
    row = [
        timeutil.utc_now(),
        _clean_field(actor, "actor"),
        _clean_field(action, "action"),
        validate_reason(reason),
    ]
    path = workspace / ATTEST_FILENAME
    needs_header = True
    if path.exists():
        if path.stat().st_size > 0:
            _require_matching_header(path)
            needs_header = False
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if needs_header:
            writer.writerow(ATTEST_FIELDS)
        writer.writerow(row)


def _clean_field(value: str, field_name: str) -> str:
    """Strip and control-character-check one attestation field."""
    cleaned = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise SuiteError(f"{field_name} must not contain control characters")
    if not cleaned:
        raise SuiteError(f"{field_name} must not be empty")
    return cleaned


def _require_matching_header(path: Path) -> None:
    """Refuse to append unless the existing log has exactly our header."""
    with path.open("r", newline="", encoding="utf-8") as handle:
        first_line = handle.readline().rstrip("\n")
    if first_line != ",".join(ATTEST_FIELDS):
        raise SuiteError(
            f"refusing to append to {path}: its header does not match a "
            "chr0nix attestation log (is this the right file?)"
        )
