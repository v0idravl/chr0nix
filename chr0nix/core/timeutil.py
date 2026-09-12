"""UTC clock access and the one timestamp format the suite emits.

Every timestamp any suite tool writes — manifests, custody and
attestation logs, timelines, reports — is UTC in ISO-8601 form with a
``Z`` designator. Centralizing both the format and the "now" seam here
means the format cannot drift between tools, and tests can inject fixed
clocks for byte-deterministic output.

Second precision is the default because sub-second component times are
noise for custody purposes and coarser timestamps keep output
diff-friendly. Sub-second precision survives only where a source
genuinely carries it (see :func:`format_utc`).
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


def utc_now() -> str:
    """Current time as ``YYYY-MM-DDTHH:MM:SSZ`` (second precision)."""
    return format_utc(utcnow(), timespec="seconds")


def format_utc(moment: datetime, *, timespec: str = "auto") -> str:
    """Format an aware datetime as UTC ISO-8601 with a ``Z`` suffix.

    Naive datetimes are rejected outright: by the time anything reaches a
    renderer it must already have passed through normalization, and a
    naive value at this stage is a programming error, not a data problem.

    ``timespec="auto"`` (the default) keeps microseconds only when the
    value genuinely carries sub-second precision — exhibit data is almost
    always second-resolution, and emitting ``.000000`` everywhere would
    add noise a human reader has to skip over. ``timespec="seconds"``
    truncates unconditionally, for outputs that must never carry
    fractional seconds (manifest timestamps, log rows).
    """
    if moment.tzinfo is None:
        raise ValueError("format_utc requires a timezone-aware datetime")
    as_utc = moment.astimezone(timezone.utc)
    if timespec == "auto":
        timespec = "microseconds" if as_utc.microsecond else "seconds"
    # isoformat emits "+00:00" for UTC; the Z suffix is the more
    # conventional rendering in evidentiary and forensic tooling.
    return as_utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def format_epoch(epoch_seconds: float) -> str:
    """Render a POSIX timestamp (e.g. ``stat().st_mtime``) as ISO-8601 UTC.

    Always second precision: filesystem mtimes frequently carry
    sub-second components that are noise in a manifest.
    """
    return format_utc(datetime.fromtimestamp(epoch_seconds, tz=timezone.utc), timespec="seconds")
