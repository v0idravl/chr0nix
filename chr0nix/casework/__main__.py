"""Entry point for ``python -m chr0nix.casework``.

Kept to three lines of substance: all behavior lives in ``cli.main``,
which returns an exit code rather than exiting, so the whole CLI is
testable in-process.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
