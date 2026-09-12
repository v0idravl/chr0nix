"""UTC clock access and the one timestamp format chr0nix emits.

Re-export shim: the implementation now lives in
:mod:`chr0nix.core.timeutil`, shared by every tool in the suite. This
module keeps the original import paths (``chr0nix.timeline.timeutil.utcnow``,
``chr0nix.timeline.timeutil.format_utc``) working.

Every timestamp chr0nix writes — in timelines, manifests, and reports —
is UTC in ISO-8601 form with a ``Z`` designator. Microseconds are
preserved only when present: exhibit data is almost always
second-resolution, and emitting ``.000000`` everywhere would add noise a
human reader has to skip over. When a source genuinely carries
sub-second precision, it survives normalization untouched.
"""

from chr0nix.core.timeutil import format_utc, utcnow

__all__ = ["utcnow", "format_utc"]
