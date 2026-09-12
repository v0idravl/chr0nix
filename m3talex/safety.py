"""Input validation and output-path safety for m3talex.

The security posture of the tool lives here, in one small auditable place:

* Inputs must exist and be the expected type (file vs. directory). Errors
  are raised before any parsing work happens, with messages that name the
  offending path.
* Output directories must **not** be the evidence directory or anywhere
  inside it. Reports written next to exhibits would be indistinguishable
  from case material on a casual inspection, so the tool flatly refuses.
* The tool never deletes, moves, or overwrites inputs — there is no code
  path in the package that opens an input file in a write mode.
"""

from __future__ import annotations

from pathlib import Path

from chr0nix.core.safety import is_within

from .errors import OutputRefusalError


def validate_input_file(raw_path: str) -> Path:
    """Resolve *raw_path* to an existing regular file or raise."""
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise OutputRefusalError(f"input does not exist: {path}")
    if not path.is_file():
        raise OutputRefusalError(f"input is not a regular file: {path}")
    return path


def validate_input_dir(raw_path: str) -> Path:
    """Resolve *raw_path* to an existing directory or raise."""
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise OutputRefusalError(f"input directory does not exist: {path}")
    if not path.is_dir():
        raise OutputRefusalError(f"input is not a directory: {path}")
    return path


def ensure_output_dir(raw_path: str, evidence_root: Path) -> Path:
    """Create and return the output directory, refusing unsafe locations.

    ``evidence_root`` is the directory that holds the exhibits being
    analyzed (the batch directory itself, or the parent of a single input
    file). Writing reports into that tree would commingle tool output with
    evidence, so both identity and containment are rejected.
    """
    output = Path(raw_path).expanduser().resolve()
    root = evidence_root.resolve()
    if is_within(output, root):
        raise OutputRefusalError(
            f"refusing to write reports inside the evidence directory: {output} "
            f"is within {root}"
        )
    if output.exists() and not output.is_dir():
        raise OutputRefusalError(f"output path exists and is not a directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    return output
