"""UTC timestamp helpers.

Re-export shim: the implementation now lives in
:mod:`chr0nix.core.timeutil`, shared by every tool in the suite. This
module keeps the original import paths (``cust0dia.timeutil.utc_now``,
``cust0dia.timeutil.format_utc``) working.

The format is ISO-8601 UTC at second precision with a ``Z`` suffix,
e.g. ``2026-08-31T14:03:22Z`` — coarser timestamps keep manifests
diff-friendly, and no court cares which millisecond a hash completed.
"""

from chr0nix.core import timeutil as _core_timeutil

__all__ = ["utc_now", "format_utc"]

#: Current time as an ISO-8601 UTC string (``YYYY-MM-DDTHH:MM:SSZ``).
utc_now = _core_timeutil.utc_now

#: Render a POSIX timestamp (e.g. ``stat().st_mtime``) as ISO-8601 UTC.
format_utc = _core_timeutil.format_epoch
