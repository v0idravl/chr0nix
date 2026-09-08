"""The one exception type chr0nix raises for expected failures.

Design decision: a single exception class keeps the CLI's error handling
honest and boring. Anything that is the user's fault (a missing file, an
undeclared timezone, an unsafe output path) is raised as ``Chr0nixError``
and reported as a clean ``chr0nix: error: ...`` message with a nonzero
exit code. Anything else that escapes is a genuine bug and is allowed to
traceback — bugs should be loud, not disguised as usage errors.
"""


class Chr0nixError(Exception):
    """A user-facing failure: bad input, unsafe paths, undeclared timezones.

    The message is written for the investigator at a terminal, not for a
    developer in a debugger: it states what is wrong, where, and usually
    what to do about it.
    """
