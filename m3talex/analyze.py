"""Analysis pipeline: image bytes in, normalized report record out.

:func:`analyze_image` is the single entry point used by both CLI
subcommands. It hashes the file first (integrity before interpretation),
detects the format from magic bytes rather than the extension (extensions
lie; a ``.jpg`` that is really a PNG should be parsed as a PNG), runs the
appropriate parser, flattens the result into a stable metadata dictionary,
and asks :mod:`m3talex.anomalies` to evaluate it.

The record schema is the tool's public contract — batch reports, manifests,
and downstream suite tools all consume it:

* ``tool`` / ``tool_version`` / ``generated_at_utc`` — provenance;
* ``file`` — path, relative path, size, SHA-256, mtime, detected format;
* ``metadata`` — flat, human-relevant fields (make, model, software,
  timestamps, dimensions) used by heuristics and the Markdown table;
* ``exif`` / ``gps`` / ``text_chunks`` — the raw decoded structures, kept
  verbatim so nothing the file said about itself is lost;
* ``parse_warnings`` / ``findings`` / ``notes`` — the narrative.
"""

from __future__ import annotations

from pathlib import Path

from . import TOOL_NAME, __version__
from .anomalies import evaluate
from .errors import FormatError
from .integrity import iso_utc, mtime_iso, sha256_file, utc_now_iso
from .jpeg import parse_jpeg
from .png import parse_png

#: Extensions scanned in batch mode. Detection itself is by magic bytes;
#: this set only decides which files get opened at all.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")

_JPEG_MAGIC = b"\xff\xd8"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def iter_images(root: Path) -> list[Path]:
    """Return all image files under *root*, sorted by relative POSIX path.

    Sorting here (rather than at render time) guarantees every downstream
    artifact — reports, manifests, console output — shares one deterministic
    order.
    """
    images = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(images, key=lambda path: path.relative_to(root).as_posix())


def analyze_image(path: Path, root: Path | None = None) -> dict:
    """Hash, parse, and evaluate one image file into a report record.

    ``root`` is the batch directory the path is reported relative to; when
    omitted (single-file mode) the bare filename is used.
    """
    relative = path.relative_to(root).as_posix() if root else path.name
    data = path.read_bytes()

    record: dict = {
        "tool": TOOL_NAME,
        "tool_version": __version__,
        "generated_at_utc": utc_now_iso(),
        "file": {
            "path": str(path),
            "relative_path": relative,
            "size_bytes": len(data),
            "sha256": sha256_file(path),
            "mtime_utc": mtime_iso(path),
            "format": None,
        },
        "metadata": {},
        "exif": {},
        "gps": {},
        "text_chunks": [],
        "parse_warnings": [],
        "findings": [],
        "notes": [],
    }

    if data.startswith(_JPEG_MAGIC):
        _analyze_jpeg(record, data)
    elif data.startswith(_PNG_MAGIC):
        _analyze_png(record, data)
    else:
        raise FormatError(
            f"unrecognized image format (neither JPEG nor PNG magic): {path}"
        )

    metadata = record["metadata"]
    metadata["mtime_utc"] = record["file"]["mtime_utc"]
    record["findings"] = evaluate(metadata)
    _add_context_notes(record)
    return record


def _analyze_jpeg(record: dict, data: bytes) -> None:
    """Fill the record from the JPEG parser's structured result."""
    info = parse_jpeg(data)
    record["file"]["format"] = "JPEG"
    ifd0, exif, gps = info.ifd0, info.exif, info.gps
    record["exif"] = {"ifd0": ifd0, "exif": exif}
    record["gps"] = gps
    record["parse_warnings"] = info.warnings
    record["metadata"] = {
        "format": "JPEG",
        "exif_present": info.exif_present,
        "jfif_present": info.jfif_present,
        "progressive_scan": info.progressive,
        "width": info.width,
        "height": info.height,
        "make": ifd0.get("Make"),
        "model": ifd0.get("Model"),
        "software": ifd0.get("Software"),
        "datetime": ifd0.get("DateTime"),
        "datetime_original": exif.get("DateTimeOriginal"),
        "datetime_digitized": exif.get("DateTimeDigitized"),
        "orientation": ifd0.get("Orientation"),
        "gps_present": bool(gps),
        "comments": info.comments,
        "markers": info.markers,
    }


def _analyze_png(record: dict, data: bytes) -> None:
    """Fill the record from the PNG parser's structured result."""
    info = parse_png(data)
    record["file"]["format"] = "PNG"
    record["text_chunks"] = [
        {"chunk_type": chunk.chunk_type, "keyword": chunk.keyword, "text": chunk.text}
        for chunk in info.text_chunks
    ]
    record["parse_warnings"] = info.warnings
    # PNG has no standard Software tag, but editors and generators
    # conventionally write one as a text chunk; surface it where the
    # heuristics look for it.
    software = next(
        (chunk.text for chunk in info.text_chunks if chunk.keyword.lower() == "software"),
        None,
    )
    record["metadata"] = {
        "format": "PNG",
        "width": info.width,
        "height": info.height,
        "bit_depth": info.bit_depth,
        "color_type": info.color_type,
        "software": software,
        "text_chunk_count": len(info.text_chunks),
        "chunk_types": info.chunk_types,
    }
    # The timestamp and text-chunk heuristics read these fields directly.
    record["metadata"]["text_chunks"] = record["text_chunks"]


def _add_context_notes(record: dict) -> None:
    """Attach non-finding context worth surfacing in a report.

    Notes are informational only: they carry no confidence label and are
    kept strictly separate from findings so a reader never confuses "handle
    with care" with "something looks off".
    """
    metadata = record["metadata"]
    if metadata.get("gps_present"):
        record["notes"].append(
            "GPS coordinates present in EXIF; handle per privacy policy "
            "before sharing this report."
        )
    if metadata.get("progressive_scan"):
        record["notes"].append(
            "Progressive JPEG encoding; cameras write baseline scans, so "
            "this file likely passed through a web-oriented encoder."
        )
