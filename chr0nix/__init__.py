"""chr0nix — a consolidated suite of investigative-documentation tools.

chr0nix is one repository containing the suite shell (this package) and
the module packages that do the evidentiary work:

- :mod:`cust0dia` — recursive SHA-256 exhibit manifests and append-only
  chain-of-custody logs.
- :mod:`chr0nix.timeline` — normalized, cross-source event timelines.
- :mod:`h4ndl3` — offline-first identifier research worksheets and a
  corroboration-gated findings store.
- ``m3talex`` — image metadata extraction and anomaly reporting.

This package is the shell: the ``chr0nix`` command-line entry point and
the interactive console framework (:mod:`chr0nix.console`) that the
module packages plug into. The console never reimplements evidence
logic — every read and every write flows through the module packages'
own cores.

Design decisions that apply across the whole suite:

- **Standard library only.** A tool that may be scrutinized in court
  should have zero dependency surface.
- **Read-only on evidence.** No tool in the suite modifies, renames, or
  deletes anything inside an evidence directory, and each refuses to
  write its own outputs there. Evidence is only ever *read*.
- **Strictly offline.** No network calls of any kind.
- **Court-auditable.** Behavior is documented in the source, output is
  deterministic, and the set of code that can execute is exactly the
  set of code a reviewer can read.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
