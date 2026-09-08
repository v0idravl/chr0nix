"""UTC clock access and the one timestamp format chr0nix emits.

Every timestamp chr0nix writes — in timelines, manifests, and reports —
is UTC in ISO-8601 form with a ``Z`` designator. Centralizing the format
here means there is exactly one place where "what does an exhibit
timestamp look like" is defined, and tests can pin it precisely.

Microseconds are preserved only when present: exhibit data is almost
always second-resolution, and emitting ``.000000`` everywhere would add
noise a human reader has to skip over. When a source genuinely carries
sub-second precision, it survives normalization untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime.

    Isolated into a function so callers (and tests) have a single,
    injectable seam for "now" rather than calls to ``datetime.now``
    scattered through the codebase.
    """
    return datetime.now(timezone.utc)


def format_utc(dt: datetime) -> str:
    """Format an aware datetime as UTC ISO-8601 with a ``Z`` suffix.

    Naive datetimes are rejected outright: by the time anything reaches a
    renderer it must already have passed through normalization, and a
    naive value at this stage is a programming error, not a data problem.
    """
    if dt.tzinfo is None:
        raise ValueError("format_utc requires a timezone-aware datetime")
    as_utc = dt.astimezone(timezone.utc)
    timespec = "microseconds" if as_utc.microsecond else "seconds"
    return as_utc.isoformat(timespec=timespec).replace("+00:00", "Z")
