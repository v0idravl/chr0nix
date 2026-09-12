"""chr0nix.core — the shared forensic primitives of the suite.

Every tool in the suite (cust0dia, chr0nix.timeline, h4ndl3, m3talex)
and the suite shell itself (tiers, casework, console) used to carry its
own copy of these primitives, with subtly divergent behavior — most
notably h4ndl3 silently skipping symlinked files in manifests. They
now live here exactly once:

- :mod:`chr0nix.core.hashing` — streamed SHA-256 file hashing.
- :mod:`chr0nix.core.timeutil` — the one UTC ISO-8601 timestamp format.
- :mod:`chr0nix.core.csvx` — append-only CSV writing with a stable,
  validated header.
- :mod:`chr0nix.core.fields` — control-character rejection for
  free-text fields (one record is one line).
- :mod:`chr0nix.core.safety` — path containment and evidence-tree
  write refusal.
- :mod:`chr0nix.core.manifest` — the shared suite manifest format:
  build (directory walk or explicit file list), write, read, and
  lookup.

The old per-package modules remain as thin re-export shims so existing
imports keep working; the behavior lives here.

Design rule: this package imports nothing from the tools or the shell —
the dependency arrow points only inward, so the core stays auditable in
isolation.
"""
