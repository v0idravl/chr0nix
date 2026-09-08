"""Module execution entry point: ``python -m h4ndl3 ...``.

Kept to three lines so the CLI logic in :mod:`h4ndl3.cli` stays directly
importable and testable without subprocess overhead.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
