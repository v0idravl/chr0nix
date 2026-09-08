"""cust0dia — recursive SHA-256 exhibit manifests and chain-of-custody logging.

cust0dia is the foundational tool of a small suite of investigative
documentation utilities. It answers the two questions every evidence
handler must be able to answer under oath:

1. "Is this file exactly what was collected?"  — answered by the manifest:
   a recursive SHA-256 inventory of an exhibit directory, recorded at
   collection time and re-verifiable at any later date.
2. "Who touched it, when, and why?" — answered by the custody log: an
   append-only CSV of custody events, each anchored to an exhibit hash
   that must exist in a manifest.

Design decisions that apply across the whole package:

- **Standard library only.** Everything here is built on ``hashlib``,
  ``pathlib``, ``csv``, ``json``, ``argparse`` and ``datetime``. A tool
  that may be scrutinized in court should have zero dependency surface.
- **Read-only on evidence.** The tool never modifies, renames, or
  deletes anything inside an evidence directory, and it refuses to write
  its own outputs there. Evidence is only ever *read*.
- **Deterministic output.** Manifest rows are sorted by relative path so
  two manifests of the same tree diff cleanly line-by-line.
- **UTC everywhere.** All timestamps are ISO-8601 UTC with a ``Z``
  suffix, second precision. Timezone ambiguity has no place in a
  custody record.
- **Strictly offline.** No network calls of any kind.
"""

__version__ = "1.0.0"

__all__ = ["Cust0diaError", "__version__"]


class Cust0diaError(Exception):
    """A user-facing operational error.

    Raised for any expected failure mode: missing paths, malformed
    manifests, unsafe output locations, unknown exhibits. The CLI layer
    catches this, prints a clean message, and exits nonzero — no
    tracebacks for conditions that are the user's to fix.
    """
