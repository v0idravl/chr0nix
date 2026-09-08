"""Module entry point so ``python -m m3talex ...`` works from the repo root."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
