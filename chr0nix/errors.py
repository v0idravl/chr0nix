"""Suite-level error types.

Kept in their own module (rather than in ``chr0nix/__init__.py``) so
every layer of the shell — CLI, console, session — can import them
without pulling in the package root, and so the module packages keep
their own error types (e.g. :class:`cust0dia.Cust0diaError`) beside
their own code.
"""


class SuiteError(Exception):
    """A user-facing operational error.

    Raised for any expected failure mode in the suite shell: unknown
    console commands, invalid session options, unsafe paths, a terminal
    that cannot host the UI. The CLI and console UI layers catch this,
    print a clean one-line message, and exit nonzero — no tracebacks
    for conditions that are the user's to fix.
    """
