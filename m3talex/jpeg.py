"""JPEG structure parsing: segment walk, EXIF extraction, comments.

A JPEG file is a start-of-image marker (``FF D8``) followed by segments of
the form ``FF <marker> <length:2> <payload>``, ending in entropy-coded scan
data (after SOS) and an end-of-image marker. Everything metadata-relevant
lives in the marker segments, so the walker stops at SOS — the scan data is
image pixels, not metadata, and reading it would only cost time.

What this module extracts:

* **APP0/JFIF presence** — an encoder fingerprint of sorts; its absence in
  a camera-claimed file is itself interesting.
* **APP1/EXIF** — the ``Exif\\0\\0`` preamble followed by a TIFF blob, parsed
  by :mod:`m3talex.tiff`.
* **COM comments** — free-text encoder comments; sometimes revealing.
* **SOF dimensions and progressive flag** — SOF2 (and friends) indicate a
  progressive scan, typical of web re-exports rather than camera originals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import FormatError
from .tiff import parse_tiff

#: Human-readable names for the markers we surface in reports.
MARKER_NAMES = {
    0xC0: "SOF0",
    0xC1: "SOF1",
    0xC2: "SOF2",
    0xC4: "DHT",
    0xD8: "SOI",
    0xD9: "EOI",
    0xDA: "SOS",
    0xDB: "DQT",
    0xDD: "DRI",
    0xE0: "APP0",
    0xE1: "APP1",
    0xFE: "COM",
}

#: Markers that carry no length field (standalone plus restart markers).
_STANDALONE = {0x01, *range(0xD0, 0xD9)}

#: SOF markers (0xC0–0xCF minus DHT, JPG, DAC) carry frame dimensions.
_SOF_MARKERS = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}

#: Baseline SOFs; anything else in the SOF range implies a progressive or
#: arithmetic-coded scan, which cameras essentially never write directly.
_BASELINE_SOFS = {0xC0, 0xC1}

_EXIF_PREAMBLE = b"Exif\x00\x00"


@dataclass
class JpegInfo:
    """Structured result of parsing one JPEG file."""

    exif_present: bool = False
    jfif_present: bool = False
    ifd0: dict = field(default_factory=dict)
    exif: dict = field(default_factory=dict)
    gps: dict = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    progressive: bool = False
    markers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_jpeg(data: bytes) -> JpegInfo:
    """Walk the marker segments of a JPEG and extract metadata structures.

    Raises :class:`~m3talex.errors.FormatError` when the file does not start
    with the SOI magic or the segment table is truncated past all sense.
    """
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise FormatError("not a JPEG: missing SOI marker (FF D8)")

    info = JpegInfo(markers=["SOI"])
    position = 2
    terminated = False  # True once EOI or SOS ends the metadata walk
    while position < len(data):
        # Between segments the byte must be 0xFF (possibly padded). Anything
        # else means we have drifted into scan data or corruption — stop.
        if data[position] != 0xFF:
            info.warnings.append(f"non-marker byte at offset {position}; stopped walking")
            break
        while position < len(data) and data[position] == 0xFF:
            position += 1  # markers may be preceded by any number of FF fill bytes
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        name = MARKER_NAMES.get(marker, f"0xFF{marker:02X}")
        info.markers.append(name)

        if marker == 0xD9:  # EOI: clean end of file
            terminated = True
            break
        if marker in _STANDALONE:
            continue
        if position + 2 > len(data):
            raise FormatError(f"truncated JPEG: length field of {name} runs past EOF")
        segment_length = int.from_bytes(data[position : position + 2], "big")
        if segment_length < 2:
            raise FormatError(f"corrupt JPEG: {name} declares length {segment_length}")
        payload = data[position + 2 : position + segment_length]
        if len(payload) < segment_length - 2:
            raise FormatError(f"truncated JPEG: {name} payload runs past EOF")
        position += segment_length

        _dispatch(info, marker, payload)
        if marker == 0xDA:  # SOS: entropy-coded pixel data follows; stop here
            terminated = True
            break
    if not terminated and not info.warnings:
        # The segment table simply ran out: no EOI ever arrived. Parseable
        # metadata is still worth reporting, but the missing terminator is
        # itself an observation (a truncated or hand-edited file).
        info.warnings.append("no EOI marker reached before end of file; file may be truncated")
    return info


def _dispatch(info: JpegInfo, marker: int, payload: bytes) -> None:
    """Route one segment payload to the appropriate sub-parser."""
    if marker == 0xE0 and payload.startswith(b"JFIF\x00"):
        info.jfif_present = True
    elif marker == 0xE1 and payload.startswith(_EXIF_PREAMBLE):
        try:
            tiff = parse_tiff(payload[len(_EXIF_PREAMBLE) :])
        except FormatError as exc:
            # A broken EXIF block is a finding-worthy observation, not a
            # reason to abandon the rest of the file.
            info.warnings.append(f"EXIF block present but unparseable: {exc}")
            return
        info.exif_present = True
        info.ifd0 = tiff["ifd0"]
        info.exif = tiff["exif"]
        info.gps = tiff["gps"]
        info.warnings.extend(tiff["warnings"])
    elif marker == 0xFE:
        info.comments.append(payload.decode("latin-1", errors="replace").strip())
    elif marker in _SOF_MARKERS and len(payload) >= 5:
        info.height = int.from_bytes(payload[1:3], "big")
        info.width = int.from_bytes(payload[3:5], "big")
        info.progressive = marker not in _BASELINE_SOFS
