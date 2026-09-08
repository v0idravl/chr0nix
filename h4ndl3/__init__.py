"""h4ndl3 — offline-first identifier research worksheet CLI.

h4ndl3 encodes a single professional conviction: in lawful investigative
documentation work, *restraint is the skill*. The tool never touches the
network — there is no lookup code, optional or otherwise — because its job
is rigor, not volume. It does three things and does them defensibly:

1. Generates a structured research worksheet mapping an identifier type
   (username, email, or domain) to a checklist of lawful public checks an
   analyst performs *manually*, in a browser, under employer authorization.
2. Maintains a JSONL findings store in which every row is strictly
   validated: source URL, retrieved-at UTC timestamp, confidence level,
   and corroborating sources are all mandatory.
3. Renders a Markdown report whose corroboration summary enforces the
   house rule: a claim is only "corroborated" when two independent
   sources back it.

The package is standard-library only and small enough to audit in a
single sitting — that auditability is a deliberate feature, not a
limitation.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
