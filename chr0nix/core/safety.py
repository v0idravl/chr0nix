"""Filesystem safety guards.

The suite's core safety promise is "read-only on evidence." That promise
is enforced here, as path predicates and refusals the command layers
call *before* opening any output file. Keeping the checks in one audited
place is safer than scattering ``resolve()`` calls across four CLIs.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from .errors import OutputRefusalError


def is_within(child: Path, parent: Path) -> bool:
    """True if ``child`` is ``parent`` itself or nested anywhere beneath it.

    Both paths must already be resolved (symlinks and ``..`` collapsed)
    by the caller; this is a pure lexical containment test. Used to
    refuse output locations that would land inside an evidence tree.
    """
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve(path: str | os.PathLike) -> str:
    """Return the canonical absolute path, resolving symlinks.

    Guards compare *resolved* paths so that tricks like ``dir/../out``
    or a symlink into an evidence directory cannot slip past them.
    """
    return os.path.realpath(path)


def validate_relative_path(rel: str) -> str:
    """Validate a manifest-relative path string; return it normalized.

    Manifest and custody inputs come from files and command lines, so
    they are untrusted. A relative path must stay inside the tree it
    refers to: absolute paths and ``..`` components are rejected, which
    closes the path-traversal hole a hand-crafted (or corrupted)
    manifest could otherwise open during verification.
    """
    pure = PurePosixPath(rel)
    if pure.is_absolute():
        raise ValueError(f"path must be relative, got absolute path: {rel!r}")
    if ".." in pure.parts:
        raise ValueError(f"path must not contain '..': {rel!r}")
    # PurePosixPath collapses redundant '.' and '//' for us; returning
    # as_posix() gives the canonical form stored in manifests.
    return pure.as_posix()


def ensure_output_allowed(
    out_path: str,
    *,
    protected_files: tuple[str, ...] = (),
    protected_dirs: tuple[str, ...] = (),
    error: type[Exception] = OutputRefusalError,
) -> None:
    """Refuse to let ``out_path`` clobber an input or land inside evidence.

    ``protected_files`` are input files the tool has open (e.g. the
    findings store a report is rendered from); ``protected_dirs`` are
    directories the tool reads as evidence (e.g. the root of a manifest
    scan). Writing on top of the former would destroy the record; writing
    inside the latter would contaminate the very directory being
    documented — the manifest would no longer describe its subject.

    Raises ``error`` (the consuming tool's own user-facing exception
    type) if the resolved output path collides with any protected file
    or lies within any protected directory.
    """
    resolved_out = resolve(out_path)

    for protected in protected_files:
        if resolved_out == resolve(protected):
            raise error(f"refusing to overwrite input file: {out_path}")

    for directory in protected_dirs:
        resolved_dir = resolve(directory)
        # os.path.commonpath is prefix-safe: it cannot be fooled by a
        # sibling directory that merely shares a name prefix.
        if (
            resolved_out == resolved_dir
            or os.path.commonpath((resolved_out, resolved_dir)) == resolved_dir
        ):
            raise error(
                f"refusing to write output inside input/evidence directory: "
                f"{out_path} is inside {directory}"
            )
