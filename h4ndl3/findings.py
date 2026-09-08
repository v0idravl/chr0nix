"""JSONL findings store with strict required-field validation.

The findings store is the evidentiary core of h4ndl3. It is append-only
by convention and validated on every read *and* every write, because a
research log that lets a malformed row in is a log a reviewer cannot
trust.

Format: one JSON object per line (JSONL). Chosen deliberately — JSONL is
diff-friendly, stream-processable with standard Unix tools, and a
corrupt line can be identified by number without parsing the rest.

Schema (all fields required unless noted):

- ``claim``            — non-empty string; the observation, stated plainly.
- ``source_url``       — http(s) URL where the analyst saw it.
- ``retrieved_at_utc`` — ISO-8601 timestamp, explicitly UTC.
- ``confidence``       — one of ``low``, ``medium``, ``high``.
- ``corroborated_by``  — list of http(s) URLs of *independent* sources;
                         must not contain ``source_url`` (a source cannot
                         corroborate itself). May be empty — the report,
                         not the store, enforces the two-corroboration
                         rule, because corroboration is often assembled
                         over days.
- ``notes``            — optional string for context.

The writer adds ``recorded_at_utc`` automatically: when the finding
entered the store, as opposed to when the source was viewed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from .common import utc_now_iso

#: Fields every finding must carry, in canonical report order.
REQUIRED_FIELDS = (
    "claim",
    "source_url",
    "retrieved_at_utc",
    "confidence",
    "corroborated_by",
)

#: Fields a finding may additionally carry.
OPTIONAL_FIELDS = ("notes", "recorded_at_utc")

#: Allowed confidence levels, lowest to highest.
CONFIDENCE_LEVELS = ("low", "medium", "high")


class FindingError(ValueError):
    """Raised when a finding fails schema validation.

    The message always identifies *which* rule failed so the analyst can
    fix the record instead of guessing.
    """


def _validate_url(value: object, field: str) -> str:
    """Require an absolute http(s) URL.

    Only http and https are accepted: findings cite public web sources,
    and exotic schemes (``file:``, ``javascript:``) have no lawful place
    in the record and are an injection risk in rendered reports.
    """
    if not isinstance(value, str) or not value:
        raise FindingError(f"{field}: must be a non-empty URL string")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FindingError(
            f"{field}: must be an absolute http(s) URL, got {value!r}"
        )
    return value


def validate_utc_timestamp(value: object, field: str = "retrieved_at_utc") -> str:
    """Require an ISO-8601 timestamp that is unambiguously UTC.

    Naive timestamps are rejected outright: "2026-08-31 14:00" with no
    offset is meaningless in a record that may be reviewed across time
    zones. The trailing ``Z`` form and the explicit ``+00:00`` form are
    both accepted; anything with a non-zero offset is rejected so the
    store stays uniformly UTC.
    """
    if not isinstance(value, str) or not value:
        raise FindingError(f"{field}: must be a non-empty ISO-8601 string")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise FindingError(
            f"{field}: not a valid ISO-8601 timestamp: {value!r}"
        ) from None
    if parsed.tzinfo is None:
        raise FindingError(f"{field}: timestamp must include a timezone")
    if parsed.tzinfo.utcoffset(parsed) != timezone.utc.utcoffset(None):
        raise FindingError(f"{field}: timestamp must be UTC")
    return value


def validate_finding(finding: object, *, where: str = "finding") -> dict:
    """Validate one finding against the schema; return it unchanged.

    ``where`` labels the finding in error messages (e.g. ``line 3``) so
    store-level validation can pinpoint bad rows.

    Raises:
        FindingError: listing every schema violation found.
    """
    errors: list[str] = []

    if not isinstance(finding, dict):
        raise FindingError(f"{where}: expected a JSON object")

    # Unknown fields are rejected, not ignored: a reviewer must be able
    # to trust that what is in the store is what the schema describes.
    allowed = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)
    for key in sorted(finding):
        if key not in allowed:
            errors.append(f"unknown field {key!r}")

    for field in REQUIRED_FIELDS:
        if field not in finding:
            errors.append(f"missing required field {field!r}")

    claim = finding.get("claim")
    if "claim" in finding and (not isinstance(claim, str) or not claim.strip()):
        errors.append("claim: must be a non-empty string")

    if "source_url" in finding:
        try:
            _validate_url(finding["source_url"], "source_url")
        except FindingError as exc:
            errors.append(str(exc))

    if "retrieved_at_utc" in finding:
        try:
            validate_utc_timestamp(finding["retrieved_at_utc"])
        except FindingError as exc:
            errors.append(str(exc))

    confidence = finding.get("confidence")
    if "confidence" in finding and confidence not in CONFIDENCE_LEVELS:
        errors.append(
            f"confidence: must be one of {', '.join(CONFIDENCE_LEVELS)}"
        )

    corroborated_by = finding.get("corroborated_by")
    if "corroborated_by" in finding:
        if not isinstance(corroborated_by, list):
            errors.append("corroborated_by: must be a list of URLs")
        else:
            for url in corroborated_by:
                try:
                    _validate_url(url, "corroborated_by")
                except FindingError as exc:
                    errors.append(str(exc))
            # Self-corroboration would inflate the corroboration count
            # with a non-independent source, defeating the rule's purpose.
            if (
                isinstance(finding.get("source_url"), str)
                and finding["source_url"] in corroborated_by
            ):
                errors.append(
                    "corroborated_by: a source cannot corroborate itself "
                    "(source_url appears in the list)"
                )

    notes = finding.get("notes")
    if "notes" in finding and notes is not None and not isinstance(notes, str):
        errors.append("notes: must be a string when present")

    if "recorded_at_utc" in finding:
        try:
            validate_utc_timestamp(finding["recorded_at_utc"], "recorded_at_utc")
        except FindingError as exc:
            errors.append(str(exc))

    if errors:
        joined = "; ".join(errors)
        raise FindingError(f"{where}: {joined}")
    return finding  # type: ignore[return-value]


def new_finding(
    *,
    claim: str,
    source_url: str,
    retrieved_at_utc: str,
    confidence: str,
    corroborated_by: list[str] | None = None,
    notes: str | None = None,
    recorded_at_utc: str | None = None,
) -> dict:
    """Build and validate a finding dict.

    Field order is fixed at construction (required fields first, then
    optional) so serialized lines are stable and diff cleanly.
    """
    finding = {
        "claim": claim,
        "source_url": source_url,
        "retrieved_at_utc": retrieved_at_utc,
        "confidence": confidence,
        "corroborated_by": list(corroborated_by or []),
    }
    if notes:
        finding["notes"] = notes
    finding["recorded_at_utc"] = recorded_at_utc or utc_now_iso()
    return validate_finding(finding)


def load_store(path: str) -> list[dict]:
    """Load and validate every finding in a JSONL store.

    The whole store is validated on load — a report rendered from a
    partially-valid store would silently launder bad rows into a
    professional document, so any invalid line fails the entire read.

    Returns findings in file order. An empty store yields an empty list.

    Raises:
        FileNotFoundError: if the store does not exist.
        FindingError: naming the first invalid line.
    """
    if os.path.isdir(path):
        raise FindingError(f"store path is a directory, not a file: {path}")
    findings: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue  # blank lines are tolerated, never produced
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise FindingError(
                    f"line {lineno}: invalid JSON: {exc.msg}"
                ) from None
            findings.append(validate_finding(obj, where=f"line {lineno}"))
    return findings


def append_finding(path: str, finding: dict) -> None:
    """Validate ``finding`` and append it as one JSON line to the store.

    The store file is created if it does not exist; a missing parent
    directory is an error rather than something to silently create, so a
    typo'd path fails loudly instead of scattering stores across the
    filesystem. The file is only ever opened in append mode — existing
    findings are never rewritten.
    """
    validated = validate_finding(finding)
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise FindingError(f"store directory does not exist: {parent}")
    line = json.dumps(validated, ensure_ascii=False, sort_keys=False)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
