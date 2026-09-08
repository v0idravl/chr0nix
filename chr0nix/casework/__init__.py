"""chr0nix.casework — case workspaces: structured, auditable case management.

casework is the case-management layer of the suite. Where cust0dia
answers "is this file exactly what was collected?" and "who touched
it?", casework answers the case-level questions: which cases exist,
what are they about, how are they classified, which entities (subjects,
vehicles, other cases) connect them, and what happened — in what order.

A *workspace* is one directory the investigator points the console at
(``set workspace <dir>``), laid out so that every fact about a case is
a line or a file a reviewer can read and diff::

    <workspace>/
    ├── config/
    │   ├── categories.csv    # user-definable case categories
    │   └── taxonomy.csv      # tree-structured behavior taxonomy
    ├── entities/
    │   ├── subjects.csv      # known subjects
    │   ├── vehicles.csv      # known vehicles
    │   └── links.csv         # append-only case<->entity associations
    └── cases/
        └── <case-id>/
            ├── case.json     # the case record
            ├── events.csv    # append-only event log
            └── synopsis.txt  # GENERATED, never hand-edited

Design decisions, in the suite's tradition:

- **Append-only where evidentiary.** ``events.csv`` and
  ``entities/links.csv`` follow :mod:`cust0dia.custody`'s pattern
  exactly: a stable header validated before every append, control
  characters rejected in free-text fields, one record per line, and the
  only write ever performed is adding bytes at the end of the file.
- **User-configurable vocabularies.** Categories and the behavior
  taxonomy live in commented CSV files the investigator edits; a case
  can only reference ids and paths that are listed there, so an
  on-the-fly vocabulary can never drift away from what the config
  actually defines.
- **Deterministic output.** ``case.json`` is written with a stable key
  order, and ``synopsis.txt`` is regenerated from sorted, stable inputs
  so two generations of the same case state are byte-identical.
- **Standard library only, strictly offline.** Same promise as the rest
  of the suite: nothing to audit but what a reviewer can read here.
"""

from ..errors import SuiteError

__all__ = ["CaseworkError"]


class CaseworkError(SuiteError):
    """A user-facing operational error in the casework layer.

    Raised for every expected failure mode: an uninitialized workspace,
    an unknown case/category/taxonomy path/entity, an invalid status
    transition, a refused append. Casework is part of the shell package
    rather than a standalone module package, so its error type derives
    from :class:`chr0nix.errors.SuiteError` directly — the console and
    CLI already render that as one clean line, and no separate
    registration in ``user_facing_errors`` is needed.
    """
