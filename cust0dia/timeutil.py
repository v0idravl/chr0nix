"""UTC timestamp helpers.

One small module with one job: every timestamp cust0dia emits goes
through here, so the format cannot drift between commands. The format
is ISO-8601 UTC at second precision with a ``Z`` suffix, e.g.
``2026-08-31T14:03:22Z``.

Second precision is deliberate: sub-second component times are noise
for custody purposes (no court cares which millisecond a hash
completed), and coarser timestamps keep manifests diff-friendly.
"""

from datetime import datetime, timezone


def _to_iso_z(moment: datetime) -> str:
    """Render an aware datetime as ``YYYY-MM-DDTHH:MM:SSZ``.

    ``isoformat`` emits ``+00:00`` for UTC; the ``Z`` suffix is the more
    conventional rendering in evidentiary and forensic tooling, so we
    normalize to it here.
    """
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now() -> str:
    """Current time as an ISO-8601 UTC string."""
    return _to_iso_z(datetime.now(timezone.utc))


def format_utc(epoch_seconds: float) -> str:
    """Render a POSIX timestamp (e.g. ``stat().st_mtime``) as ISO-8601 UTC."""
    return _to_iso_z(datetime.fromtimestamp(epoch_seconds, tz=timezone.utc))
