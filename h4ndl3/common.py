"""Shared utilities: UTC timestamps and output-path safety.

Two concerns live here because every module needs them and neither
deserves a module of its own:

- Timestamps. The entire suite standardizes on UTC ISO-8601. Centralizing
  the "now" helper means every tool stamps time the same way, and tests
  can inject fixed clocks for byte-deterministic output.
- Output-path safety. h4ndl3 is read-only on inputs. These guards make
  that promise *enforced* rather than aspirational: an output may never
  overwrite an input file, and may never be written inside a directory
  the tool is treating as evidence.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix.

    Seconds precision is sufficient for investigative documentation and
    keeps diffed outputs readable; the trailing ``Z`` makes the timezone
    unambiguous in every downstream consumer.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve(path: str) -> str:
    """Return the canonical absolute path, resolving symlinks.

    Guards compare *resolved* paths so that tricks like ``dir/../out``
    or a symlink into an evidence directory cannot slip past them.
    """
    return os.path.realpath(path)


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
    resolved_out = resolve(out_path)

    for protected in protected_files:
        if resolved_out == resolve(protected):
            raise OutputPathError(
                f"refusing to overwrite input file: {out_path}"
            )

    for directory in protected_dirs:
        resolved_dir = resolve(directory)
        # os.path.commonpath is prefix-safe: it cannot be fooled by a
        # sibling directory that merely shares a name prefix.
        if (
            resolved_out == resolved_dir
            or os.path.commonpath((resolved_out, resolved_dir)) == resolved_dir
        ):
            raise OutputPathError(
                f"refusing to write output inside input/evidence directory: "
                f"{out_path} is inside {directory}"
            )
