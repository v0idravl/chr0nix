"""Interactive console: a curses TUI shell for the investigative suite.

The console is a second front end alongside :mod:`chr0nix.cli`, aimed
at interactive evidence work rather than scripting. Its interaction
model borrows from operator consoles like metasploit and sliver: a
shared session context (the "workspace"), tools selected with ``use``,
options set with ``set``, and actions fired with ``run``.

Design invariants, in order of importance:

1. **The console never reimplements evidence logic.** Every read and
   every write flows through the same core modules the CLI uses —
   :mod:`cust0dia.manifest`, :mod:`cust0dia.verify`,
   :mod:`cust0dia.custody`. The console is a view over those modules,
   so its security properties (append-only custody, manifest-anchored
   exhibits, evidence-tree write protection) are inherited, not
   restated.
2. **All behavior is testable without a terminal.** :mod:`.session`,
   :mod:`.tools`, and :mod:`.commands` contain every decision the
   console makes and never import curses; :mod:`.ui` is a thin shell
   that renders text in and text out. The unit tests drive the command
   layer in-process, exactly like the CLI tests drive ``cli.main``.
3. **The plugin surface is static.** Tools are an explicit, in-code
   registry (:data:`chr0nix.console.tools.REGISTRY`). There is no
   runtime plugin discovery and no importing modules from arbitrary
   paths — in an evidence tool, dynamic code loading would be an
   attack surface, not a feature.
4. **Nothing leaks to disk.** Command history lives in memory for the
   duration of the session only; the console writes nothing except
   what the evidence commands themselves write (manifests and custody
   logs).
"""
