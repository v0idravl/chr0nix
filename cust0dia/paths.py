"""Filesystem safety guards.

cust0dia's core safety promise is "read-only on evidence." That promise
is enforced here, as path predicates the command layer calls *before*
opening any output file. Keeping the checks in one audited place is
safer than scattering ``resolve()`` calls across the CLI.
"""

from pathlib import Path


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


def validate_relative_path(rel: str) -> str:
    """Validate a manifest-relative path string; return it normalized.

    Manifest and custody inputs come from files and command lines, so
    they are untrusted. A relative path must stay inside the tree it
    refers to: absolute paths and ``..`` components are rejected, which
    closes the path-traversal hole a hand-crafted (or corrupted)
    manifest could otherwise open during verification.
    """
    from pathlib import PurePosixPath

    pure = PurePosixPath(rel)
    if pure.is_absolute():
        raise ValueError(f"path must be relative, got absolute path: {rel!r}")
    if ".." in pure.parts:
        raise ValueError(f"path must not contain '..': {rel!r}")
    # PurePosixPath collapses redundant '.' and '//' for us; returning
    # as_posix() gives the canonical form stored in manifests.
    return pure.as_posix()
