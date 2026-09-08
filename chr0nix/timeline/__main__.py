"""Module entry point: enables ``python -m chr0nix ...`` from anywhere."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
