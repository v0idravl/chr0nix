"""Control-character rejection for free-text fields.

Append-only logs and registries across the suite share one invariant:
one record is one line. A newline (or any other control character)
inside a free-text field would let a single "record" smuggle in forged
additional rows, so fields are stripped and rejected — never silently
sanitized — before they reach a CSV.
"""

from .errors import CoreError


def has_control_characters(value: str) -> bool:
    """True if ``value`` contains any C0 control character or DEL."""
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def clean_field(
    value: str,
    field_name: str,
    *,
    required: bool,
    error: type[Exception] = CoreError,
) -> str:
    """Validate and normalize one free-text field; return it stripped.

    ``error`` is the consuming tool's own user-facing exception type, so
    the failure surfaces the same way as the rest of that tool's errors.
    """
    cleaned = value.strip()
    if has_control_characters(cleaned):
        raise error(f"{field_name} must not contain control characters")
    if required and not cleaned:
        raise error(f"{field_name} must not be empty")
    return cleaned
