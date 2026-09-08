"""Identifier validation and classification.

h4ndl3 accepts exactly three identifier types — username, email, domain —
because those are the pivots lawful public-source research actually
supports for in-house asset-protection casework. Everything else (plates,
restricted records, professional-tier databases) is deliberately out of
scope and flows through employer systems, not personal tooling.

Validation here is *sanitization*, not merely pattern-matching for its own
sake: identifiers are user-supplied strings that end up embedded in
generated Markdown and suggested shell commands, so anything with
whitespace, control characters, or URL metacharacters is rejected before
it can become a rendering or copy-paste hazard.
"""

from __future__ import annotations

import re

#: The identifier types h4ndl3 knows how to build a worksheet for.
IDENTIFIER_TYPES = ("username", "email", "domain")

# Conservative, intentionally restrictive patterns. A false rejection is
# cheap (the analyst re-types the identifier); a false acceptance embeds
# hostile text into a worksheet.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")
_EMAIL_LOCAL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}$")
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TLD_RE = re.compile(r"^[a-z]{2,63}$")


class IdentifierError(ValueError):
    """Raised when an identifier fails type-specific validation."""


def _reject_unsafe(value: str, id_type: str) -> None:
    """Reject identifiers containing characters unsafe to embed anywhere.

    Control characters, whitespace, and shell/URL metacharacters have no
    legitimate place in a username, email, or domain, so their presence
    is treated as an error rather than silently stripped — silent
    mutation of an identifier under investigation would corrupt the
    record.
    """
    if any(ch.isspace() for ch in value):
        raise IdentifierError(f"{id_type} identifier contains whitespace")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise IdentifierError(f"{id_type} identifier contains control characters")
    for ch in "/\\`'\"|;&$<>":
        if ch in value:
            raise IdentifierError(
                f"{id_type} identifier contains forbidden character: {ch!r}"
            )


def validate_username(value: str) -> str:
    """Validate and normalize a username identifier.

    Returns the username unchanged (case is preserved because platforms
    differ on case sensitivity, and the record must reflect what was
    actually researched). Raises :class:`IdentifierError` on failure.
    """
    _reject_unsafe(value, "username")
    if not _USERNAME_RE.match(value):
        raise IdentifierError(
            "invalid username: use 1-64 characters of letters, digits, "
            "'.', '_' or '-', starting and ending with a letter or digit"
        )
    return value


def validate_domain(value: str) -> str:
    """Validate and normalize a domain name.

    DNS names are case-insensitive, so the normalized form is lowercase.
    Schemes, paths, ports, and trailing dots are rejected: the identifier
    is a bare hostname, and forcing that discipline prevents accidental
    conflation of "a URL found during research" with "the identifier
    under investigation".
    """
    _reject_unsafe(value, "domain")
    normalized = value.lower()
    if "://" in normalized or ":" in normalized:
        raise IdentifierError(
            "invalid domain: provide a bare hostname, without scheme or port"
        )
    labels = normalized.split(".")
    if len(labels) < 2:
        raise IdentifierError("invalid domain: must contain at least one dot")
    for label in labels:
        if not _DOMAIN_LABEL_RE.match(label):
            raise IdentifierError(
                f"invalid domain label {label!r}: labels are 1-63 characters "
                "of letters, digits, or hyphens, not starting/ending with '-'"
            )
    if not _TLD_RE.match(labels[-1]):
        raise IdentifierError("invalid domain: final label must be alphabetic")
    return normalized


def validate_email(value: str) -> str:
    """Validate and normalize an email address.

    The local part is validated character-by-character rather than with a
    full RFC 5322 grammar — quoted-string and address-literal forms are
    vanishingly rare in casework and are exactly where hostile input
    hides. The domain part is held to the same standard as a bare domain.
    """
    _reject_unsafe(value, "email")
    if value.count("@") != 1:
        raise IdentifierError("invalid email: must contain exactly one '@'")
    local, _, domain = value.partition("@")
    if not _EMAIL_LOCAL_RE.match(local):
        raise IdentifierError(
            "invalid email: local part must be 1-64 characters of letters, "
            "digits, or '.', '_', '%', '+', '-'"
        )
    domain = validate_domain(domain)
    return f"{local}@{domain}"


_VALIDATORS = {
    "username": validate_username,
    "email": validate_email,
    "domain": validate_domain,
}


def validate(value: str, id_type: str) -> str:
    """Validate ``value`` as the given identifier type; return normalized form."""
    try:
        validator = _VALIDATORS[id_type]
    except KeyError:
        raise IdentifierError(
            f"unknown identifier type {id_type!r}; "
            f"expected one of: {', '.join(IDENTIFIER_TYPES)}"
        ) from None
    value = value.strip()
    if not value:
        raise IdentifierError("identifier must not be empty")
    return validator(value)


def classify(value: str) -> str:
    """Best-effort guess of an identifier's type from its shape.

    The heuristic is deliberately simple and documented: one ``@`` means
    email; otherwise, if the string is a well-formed domain it is a
    domain; otherwise it is a username. Analysts can always override the
    guess with an explicit ``--type``.
    """
    if value.count("@") == 1:
        return "email"
    try:
        validate_domain(value)
    except IdentifierError:
        return "username"
    return "domain"
