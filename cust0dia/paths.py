"""Filesystem safety guards.

Re-export shim: the implementation now lives in
:mod:`chr0nix.core.safety`, shared by every tool in the suite. This
module keeps the original import paths (``cust0dia.paths.is_within``,
``cust0dia.paths.validate_relative_path``) working.

cust0dia's core safety promise is "read-only on evidence"; the command
layer calls these predicates *before* opening any output file.
"""

from chr0nix.core.safety import is_within, validate_relative_path

__all__ = ["is_within", "validate_relative_path"]
