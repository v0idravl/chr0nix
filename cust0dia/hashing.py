"""Streamed SHA-256 file hashing.

Re-export shim: the implementation now lives in
:mod:`chr0nix.core.hashing`, shared by every tool in the suite. This
module keeps the original import path (``cust0dia.hashing.sha256_file``)
working.
"""

from chr0nix.core.hashing import sha256_file

__all__ = ["sha256_file"]
