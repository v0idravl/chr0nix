"""chr0nix — UTC-normalized, hash-manifested exhibit timelines.

chr0nix merges incident exports from multiple systems (AP case management,
CCTV bookmark logs, POS back-office logs, officer notes) into a single,
chronologically ordered exhibit timeline. Every row is traceable to its
source file and row number, every ambiguous timestamp is flagged rather
than silently guessed, and every input is fingerprinted into a SHA-256
manifest in the shared suite format.

The package is deliberately small and standard-library only so that any
reviewer — a hiring manager, a supervisor, opposing counsel's expert —
can read it end-to-end and verify exactly what it does to the evidence
(nothing) and to the record (normalize, order, cite, hash).

Modules
-------
errors      : the single exception type the CLI surfaces as clean errors.
timeutil    : UTC clock access and ISO-8601/Z formatting helpers.
schema      : the input CSV contract and per-row validation.
normalize   : timestamp parsing and timezone/DST normalization.
timeline    : deterministic merge-sort of events from all sources.
render      : CSV and Markdown renderers for the unified timeline.
manifest    : SHA-256 input manifest in the shared suite format.
cli         : argparse wiring, path-safety enforcement, exit codes.
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
