"""Exception types for m3talex.

A single shared hierarchy lives here so the CLI can catch one base class,
print a clean message, and exit nonzero — no tracebacks for expected
failure modes like a truncated JPEG or a refused output path.
"""


class M3talexError(Exception):
    """Base class for all expected, user-facing m3talex failures."""


class FormatError(M3talexError):
    """The input bytes do not conform to the expected image format.

    Raised for wrong magic bytes, truncated segments, malformed TIFF
    headers, and similar structural problems. Parsers raise this rather
    than returning garbage: a silently misparsed exhibit is worse than
    a loud failure.
    """


class OutputRefusalError(M3talexError):
    """The requested output location is unsafe.

    m3talex refuses to write reports into (or beneath) the input/evidence
    directory, because commingling tool output with exhibits undermines the
    integrity story the tool exists to tell.
    """
