"""Integrity verification: re-hash a tree against a manifest.

Verification answers the question the manifest exists for: *is the
evidence still exactly what was collected?* Every manifested file is
re-hashed and classified, and the tree is swept for files the manifest
does not know about:

- ``OK``      — file present, hash matches the manifest.
- ``CHANGED`` — file present, hash differs. The headline tamper signal.
- ``MISSING`` — file in the manifest is gone from the tree.
- ``EXTRA``   — file in the tree is absent from the manifest. Not
  modification of an existing exhibit, but an unexpected object in an
  evidence container is an integrity event worth failing on.

Any non-OK result fails the verification (the CLI maps that to exit
code 1): for evidence, "mostly intact" is not a passing grade.
"""

from dataclasses import dataclass
from pathlib import Path

from . import hashing
from .manifest import ManifestEntry, iter_evidence_files

STATUS_OK = "OK"
STATUS_CHANGED = "CHANGED"
STATUS_MISSING = "MISSING"
STATUS_EXTRA = "EXTRA"

#: Report order for the summary line — worst news first after OK.
STATUS_ORDER = (STATUS_OK, STATUS_CHANGED, STATUS_MISSING, STATUS_EXTRA)


@dataclass(frozen=True)
class VerifyResult:
    """One file's verification outcome.

    ``detail`` carries human-readable context (e.g. expected vs. actual
    digest prefixes for a CHANGED file) and is empty otherwise.
    """

    status: str
    relative_path: str
    detail: str = ""


def verify_tree(root: Path, entries: list[ManifestEntry]) -> list[VerifyResult]:
    """Re-hash ``root`` against ``entries`` and return sorted results.

    ``root`` must be a resolved directory. Results are sorted by
    relative path so verification reports diff cleanly, just like the
    manifests they check.
    """
    results: list[VerifyResult] = []
    for entry in entries:
        # Manifest relative paths were validated at read time (no
        # absolute paths, no '..'), so this join cannot escape root.
        target = root / entry.relative_path
        if not target.is_file():
            results.append(VerifyResult(STATUS_MISSING, entry.relative_path))
            continue
        actual = hashing.sha256_file(target)
        if actual == entry.sha256:
            results.append(VerifyResult(STATUS_OK, entry.relative_path))
        else:
            results.append(
                VerifyResult(
                    STATUS_CHANGED,
                    entry.relative_path,
                    f"manifest {entry.sha256[:12]}… actual {actual[:12]}…",
                )
            )

    # Sweep for EXTRA files: anything on disk the manifest does not
    # claim. This catches evidence planted or dropped into the container
    # after collection.
    manifested = {entry.relative_path for entry in entries}
    for path in iter_evidence_files(root):
        relative = path.relative_to(root).as_posix()
        if relative not in manifested:
            results.append(VerifyResult(STATUS_EXTRA, relative))

    results.sort(key=lambda result: result.relative_path)
    return results


def summarize(results: list[VerifyResult]) -> dict[str, int]:
    """Count results by status, in canonical report order."""
    counts = {status: 0 for status in STATUS_ORDER}
    for result in results:
        counts[result.status] += 1
    return counts


def passed(results: list[VerifyResult]) -> bool:
    """True only if every result is OK."""
    return all(result.status == STATUS_OK for result in results)
