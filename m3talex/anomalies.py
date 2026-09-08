"""Anomaly heuristics: turning parsed metadata into documented observations.

Every heuristic here answers one narrow question and phrases its answer as
an *observation with a confidence level* — never a verdict. "Consistent
with post-capture editing" is a lead an investigator can act on; "fake" is
a claim this tool deliberately refuses to make, because metadata can be
stripped, rewritten, or absent for innocent reasons.

The heuristics, in the order they run:

1. **Missing EXIF where expected** — a JPEG with no EXIF block at all is
   consistent with metadata stripping, re-export through a platform, or a
   non-camera origin.
2. **Missing camera identity** — EXIF present but no Make/Model suggests
   the file did not come straight off a sensor.
3. **Software signatures** — ``Software`` tags (EXIF or PNG text) matching
   known editors indicate post-capture processing; matches against known
   generator toolchains indicate synthetic-media origin.
4. **Timestamp inconsistencies** — a modification timestamp that *predates*
   the capture timestamp is internally impossible without intervention;
   a merely *different* one is weaker evidence of a later edit pass.
5. **Synthetic-media fingerprints** — PNG text keywords like ``parameters``
   or values naming generator tooling are strong indicators of AI origin.

Confidence levels are qualitative (``low``/``medium``/``high``) and reflect
how specific the indicator is, not how certain any conclusion is.
"""

from __future__ import annotations

from datetime import datetime

#: Substrings identifying common editing software in Software tags.
#: Lowercase; matched with ``in`` against the lowercased tag value.
EDITING_SOFTWARE_SIGNATURES = (
    "photoshop",
    "lightroom",
    "gimp",
    "snapseed",
    "pixlr",
    "canva",
    "affinity photo",
    "paint.net",
    "darktable",
    "capture one",
    "illustrator",
    "inkscape",
    "photopea",
    "facetune",
    "picsart",
    "meitu",
)

#: Substrings identifying synthetic-media generator toolchains.
SYNTHETIC_MEDIA_SIGNATURES = (
    "stable diffusion",
    "automatic1111",
    "comfyui",
    "midjourney",
    "dall-e",
    "dalle",
    "novelai",
    "adobe firefly",
    "firefly",
    "invokeai",
    "sdxl",
    "diffusers",
    "leonardo.ai",
)

#: PNG text keywords habitually written by image generators. "parameters"
#: is the Automatic1111/Stable-Diffusion-webui convention and carries the
#: full prompt and sampler settings; "prompt"/"negative prompt" appear in
#: ComfyUI and NovelAI exports.
SYNTHETIC_TEXT_KEYWORDS = ("parameters", "prompt", "negative prompt", "dream", "workflow")


def parse_exif_datetime(raw) -> datetime | None:
    """Parse an EXIF ``YYYY:MM:DD HH:MM:SS`` timestamp, tolerating junk.

    Returns ``None`` for anything that does not fit the format — cameras
    and editors both write malformed values, and a heuristic must never
    crash on the data it is judging.
    """
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def evaluate(metadata: dict) -> list[dict]:
    """Apply all heuristics to a normalized metadata dict.

    ``metadata`` is the flat structure produced by :mod:`m3talex.analyze`.
    Returns findings sorted by id for deterministic output. Each finding is
    ``{"id", "category", "observation", "confidence", "evidence"}``.
    """
    findings: list[dict] = []
    _check_missing_exif(metadata, findings)
    _check_software(metadata, findings)
    _check_timestamps(metadata, findings)
    _check_text_chunks(metadata, findings)
    return sorted(findings, key=lambda finding: finding["id"])


def _finding(findings: list[dict], id_: str, category: str, observation: str,
             confidence: str, evidence: str) -> None:
    """Append one finding in the canonical shape."""
    findings.append({
        "id": id_,
        "category": category,
        "observation": observation,
        "confidence": confidence,
        "evidence": evidence,
    })


def _check_missing_exif(metadata: dict, findings: list[dict]) -> None:
    """Heuristic 1 and 2: absent EXIF, or EXIF without camera identity."""
    if metadata.get("format") != "JPEG":
        return  # PNG simply has no EXIF; absence is not anomalous there.
    if not metadata.get("exif_present"):
        _finding(
            findings, "missing-exif", "metadata-completeness",
            "JPEG contains no EXIF metadata; consistent with metadata "
            "stripping, re-export through a platform that removes it, or a "
            "non-camera origin.",
            "medium",
            "no EXIF APP1 segment found during segment walk",
        )
    elif not metadata.get("make") and not metadata.get("model"):
        _finding(
            findings, "missing-camera-identity", "metadata-completeness",
            "EXIF is present but carries no camera Make/Model; consistent "
            "with a file that did not come directly from a camera sensor, "
            "or with selective tag removal.",
            "low",
            "EXIF block parsed; Make and Model tags both absent",
        )


def _check_software(metadata: dict, findings: list[dict]) -> None:
    """Heuristic 3: editing-software and generator signatures in tags."""
    software = metadata.get("software")
    if not software:
        return
    lowered = software.lower()
    if any(sig in lowered for sig in SYNTHETIC_MEDIA_SIGNATURES):
        _finding(
            findings, "synthetic-media-indicator", "synthetic-media",
            "Software tag names tooling associated with synthetic-media "
            "generation; consistent with an AI-generated or AI-processed image.",
            "high",
            f"Software: {software!r}",
        )
    elif any(sig in lowered for sig in EDITING_SOFTWARE_SIGNATURES):
        _finding(
            findings, "editing-software-signature", "provenance",
            "Software tag identifies image-editing software; consistent with "
            "post-capture editing or re-export.",
            "medium",
            f"Software: {software!r}",
        )
    else:
        _finding(
            findings, "software-tag-present", "provenance",
            "A Software tag is present; camera originals typically omit it, "
            "so some processing step likely wrote this file.",
            "low",
            f"Software: {software!r}",
        )


def _check_timestamps(metadata: dict, findings: list[dict]) -> None:
    """Heuristic 4: internal consistency of create/modify timestamps."""
    captured = parse_exif_datetime(metadata.get("datetime_original"))
    modified = parse_exif_datetime(metadata.get("datetime"))
    digitized = parse_exif_datetime(metadata.get("datetime_digitized"))

    if captured and modified:
        if modified < captured:
            _finding(
                findings, "timestamp-inconsistency", "timestamps",
                "The EXIF modify timestamp predates the capture timestamp, "
                "which is internally inconsistent for an unmodified camera "
                "original; consistent with metadata rewriting.",
                "high",
                f"DateTime={metadata['datetime']!r} < "
                f"DateTimeOriginal={metadata['datetime_original']!r}",
            )
        elif modified != captured:
            _finding(
                findings, "timestamp-mismatch", "timestamps",
                "The EXIF modify timestamp differs from the capture "
                "timestamp; consistent with a post-capture edit or re-save.",
                "medium",
                f"DateTime={metadata['datetime']!r} vs "
                f"DateTimeOriginal={metadata['datetime_original']!r}",
            )
    if captured and digitized and digitized != captured:
        _finding(
            findings, "digitized-timestamp-mismatch", "timestamps",
            "The digitization timestamp differs from the capture timestamp; "
            "a weak indicator seen when files pass through conversion tooling.",
            "low",
            f"DateTimeDigitized={metadata['datetime_digitized']!r} vs "
            f"DateTimeOriginal={metadata['datetime_original']!r}",
        )

    # Cross-check EXIF capture time against the filesystem mtime. File times
    # are trivially rewritten by copies and downloads, so this can only ever
    # be a low-confidence note — but a file whose mtime *predates* its
    # claimed capture moment is worth a second look.
    if captured and metadata.get("mtime_utc"):
        try:
            mtime = datetime.strptime(metadata["mtime_utc"], "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return
        if mtime < captured:
            _finding(
                findings, "file-timestamp-anomaly", "timestamps",
                "The filesystem modification time predates the EXIF capture "
                "timestamp; filesystem times are unreliable, but the ordering "
                "is consistent with metadata written after the fact.",
                "low",
                f"mtime={metadata['mtime_utc']!r} < "
                f"DateTimeOriginal={metadata['datetime_original']!r}",
            )


def _check_text_chunks(metadata: dict, findings: list[dict]) -> None:
    """Heuristic 5: synthetic-media fingerprints in PNG text chunks."""
    if any(f["id"] == "synthetic-media-indicator" for f in findings):
        return  # the Software tag already fired this finding; don't double-report
    synthetic_hits: list[str] = []
    for chunk in metadata.get("text_chunks", []):
        keyword = chunk.get("keyword", "").lower()
        value = chunk.get("text", "").lower()
        if keyword in SYNTHETIC_TEXT_KEYWORDS:
            synthetic_hits.append(f"keyword {chunk['keyword']!r}")
        elif any(sig in value for sig in SYNTHETIC_MEDIA_SIGNATURES):
            synthetic_hits.append(f"{chunk['keyword']!r} mentions generator tooling")
    if synthetic_hits:
        _finding(
            findings, "synthetic-media-indicator", "synthetic-media",
            "PNG text chunks contain generator-style parameter blocks or "
            "references to synthetic-media tooling; consistent with an "
            "AI-generated image.",
            "high",
            "; ".join(sorted(synthetic_hits)),
        )
