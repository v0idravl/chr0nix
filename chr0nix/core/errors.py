"""Exception types for chr0nix.core.

Core functions take an ``error`` keyword so each consuming tool can have
failures raised as its own user-facing error type (e.g.
:class:`cust0dia.Cust0diaError`), which the tool's CLI already renders
as one clean line. The classes here are the defaults when a caller does
not bind its own type; shell front ends that want to render them cleanly
should catch :class:`CoreError`.
"""


class CoreError(Exception):
    """Base class for expected, user-facing failures raised by chr0nix.core."""


class ManifestError(CoreError):
    """A manifest is malformed, or an entry could not be hashed.

    Raised for unreadable manifests, schema violations inside one, and
    unstatable entries (almost always a broken symlink) during a build.
    """


class OutputRefusalError(CoreError):
    """The requested output location would violate the read-only-inputs rule."""
