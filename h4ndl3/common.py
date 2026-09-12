"""Shared utilities: UTC timestamps and output-path safety.

Re-export shim over :mod:`chr0nix.core`, which now holds the single
implementation of both concerns:

- :func:`chr0nix.core.timeutil.utc_now` — the suite-standard UTC
  ISO-8601 "now" helper. Centralizing the clock means every tool stamps
  time the same way, and tests can inject fixed clocks for
  byte-deterministic output.
- :func:`chr0nix.core.safety.ensure_output_allowed` — output-path
  safety. h4ndl3 is read-only on inputs; these guards make that promise
  *enforced* rather than aspirational: an output may never overwrite an
  input file, and may never be written inside a directory the tool is
  treating as evidence.

This module keeps the original h4ndl3 API working — same names, same
signatures, same :class:`OutputPathError` type — while delegating the
behavior to the shared core.
"""

from __future__ import annotations

from chr0nix.core import safety as _core_safety

#: Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``. Seconds precision is
#: sufficient for investigative documentation and keeps diffed outputs
#: readable; the trailing ``Z`` makes the timezone unambiguous in every
#: downstream consumer. Alias of :func:`chr0nix.core.timeutil.utc_now`.
from chr0nix.core.timeutil import utc_now as utc_now_iso

__all__ = ["utc_now_iso", "resolve", "OutputPathError", "ensure_output_allowed"]


#: Canonical absolute path, resolving symlinks (re-export).
resolve = _core_safety.resolve


class OutputPathError(ValueError):
    """Raised when an output path would violate the read-only-inputs rule."""


def ensure_output_allowed(
    out_path: str,
    *,
    protected_files: tuple[str, ...] = (),
    protected_dirs: tuple[str, ...] = (),
) -> None:
    """Refuse to let ``out_path`` clobber an input or land inside evidence.

    ``protected_files`` are input files the tool has open (e.g. the
    findings store a report is rendered from); ``protected_dirs`` are
    directories the tool reads as evidence (e.g. the root of a manifest
    scan). Writing on top of the former would destroy the record; writing
    inside the latter would contaminate the very directory being
    documented — the manifest would no longer describe its subject.

    Raises:
        OutputPathError: if the resolved output path collides with any
            protected file or lies within any protected directory.
    """
    _core_safety.ensure_output_allowed(
        out_path,
        protected_files=protected_files,
        protected_dirs=protected_dirs,
        error=OutputPathError,
    )
