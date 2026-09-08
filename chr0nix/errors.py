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


#: Each module package's user-facing error types, as ``(module, names)``
#: pairs. Resolved lazily inside :func:`user_facing_errors` — never at
#: import time — so this module stays importable in a partial checkout
#: of the suite, and so ``chr0nix --help`` never depends on the module
#: packages being present.
_MODULE_ERROR_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cust0dia", ("Cust0diaError",)),
    ("chr0nix.timeline.errors", ("Chr0nixError",)),
    ("h4ndl3.identifiers", ("IdentifierError",)),
    ("h4ndl3.findings", ("FindingError",)),
    ("h4ndl3.common", ("OutputPathError",)),
    ("m3talex.errors", ("M3talexError",)),
)


def user_facing_errors() -> tuple[type[Exception], ...]:
    """The error types the shell renders as one clean line, not a traceback.

    Always includes :class:`SuiteError`; each module package's own error
    types (an unknown exhibit, a malformed manifest row, an invalid
    finding, an unparseable image, a refused output path) are added when
    their package is importable. Both front ends — the suite CLI and the
    curses console — catch exactly this tuple, so a user-fixable failure
    surfaces identically no matter which door it came through. Anything
    outside the tuple is a bug and is allowed to traceback.
    """
    import importlib

    errors: list[type[Exception]] = [SuiteError]
    for module_name, attribute_names in _MODULE_ERROR_TYPES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        errors.extend(getattr(module, name) for name in attribute_names)
    return tuple(errors)
