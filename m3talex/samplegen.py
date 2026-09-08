"""Programmatic builders for tiny, deterministic sample images.

This module exists so that neither the test suite nor the shipped
``examples/`` directory depends on binary blobs nobody can inspect. Every
fixture is built byte-by-byte from the same format specifications the
parsers implement — writing a valid EXIF block is also the strongest
possible test that we understand one.

Nothing here is used at analysis time; these builders serve tests and
example generation only. All output is deterministic: same arguments, same
bytes, every run, on every platform.
"""

from __future__ import annotations

import struct
import zlib

#: TIFF field types used by the builders (mirror tiff.py's table).
_ASCII, _SHORT, _LONG, _RATIONAL = 2, 3, 4, 5

_TYPE_SIZES = {2: 1, 3: 2, 4: 4, 5: 8}

_EXIF_IFD_POINTER = 0x8769


def build_tiff(ifd0_entries: list[tuple], exif_entries: list[tuple] | None = None) -> bytes:
    """Build a minimal little-endian TIFF blob with IFD0 and an EXIF sub-IFD.

    Entries are ``(tag, type, value)`` tuples; ``value`` is a ``str`` for
    ASCII, an ``int`` for SHORT/LONG, or a ``(numerator, denominator)``
    tuple for RATIONAL. Layout: 8-byte header, IFD0, EXIF sub-IFD, then the
    out-of-line value area. The ExifIFD pointer tag (0x8769) is inserted
    automatically when ``exif_entries`` is given.
    """
    entries = sorted(ifd0_entries)
    has_exif = exif_entries is not None
    if has_exif:
        entries.append((_EXIF_IFD_POINTER, _LONG, 0))  # patched with the real offset below
        entries.sort()
        exif_entries = sorted(exif_entries)

    ifd0_offset = 8
    ifd0_size = 2 + 12 * len(entries) + 4
    exif_offset = ifd0_offset + ifd0_size
    exif_size = 2 + 12 * len(exif_entries) + 4 if has_exif else 0
    data_area_offset = exif_offset + exif_size

    blob = bytearray(b"II" + struct.pack("<HI", 42, ifd0_offset))
    data_area = bytearray()

    def emit_ifd(entry_list, base_offset):
        blob.extend(struct.pack("<H", len(entry_list)))
        for tag, field_type, value in entry_list:
            if tag == _EXIF_IFD_POINTER and has_exif:
                value = exif_offset  # patch the placeholder with the real sub-IFD offset
            raw = _encode_value(field_type, value)
            count = _value_count(field_type, value, raw)
            blob.extend(struct.pack("<HHI", tag, field_type, count))
            if len(raw) <= 4:
                blob.extend(raw.ljust(4, b"\x00"))  # inline, left-justified
            else:
                blob.extend(struct.pack("<I", base_offset + len(data_area)))
                data_area.extend(raw)
                if len(data_area) % 2:
                    data_area.extend(b"\x00")  # keep values word-aligned, per TIFF convention
        blob.extend(struct.pack("<I", 0))  # no next IFD

    emit_ifd(entries, data_area_offset)
    if has_exif:
        emit_ifd(exif_entries, data_area_offset)
    blob.extend(data_area)
    return bytes(blob)


def _encode_value(field_type: int, value) -> bytes:
    """Encode one Python value into little-endian TIFF field bytes."""
    if field_type == _ASCII:
        return value.encode("ascii") + b"\x00"
    if field_type == _SHORT:
        return struct.pack("<H", value)
    if field_type == _LONG:
        return struct.pack("<I", value)
    if field_type == _RATIONAL:
        numerator, denominator = value
        return struct.pack("<II", numerator, denominator)
    raise ValueError(f"unsupported field type for builder: {field_type}")


def _value_count(field_type: int, value, raw: bytes) -> int:
    """Compute the TIFF count field for an encoded value."""
    return len(raw) if field_type == _ASCII else 1


def build_jpeg(
    ifd0_entries: list[tuple] | None = None,
    exif_entries: list[tuple] | None = None,
    jfif: bool = True,
    comment: str | None = None,
) -> bytes:
    """Build a tiny structurally valid JPEG: SOI, segments, EOI.

    Passing ``ifd0_entries=None`` yields the stripped-metadata case (no
    APP1/EXIF at all). The file intentionally carries no scan data — the
    parsers stop at SOS and fixtures only need the metadata segments.
    """
    out = bytearray(b"\xff\xd8")
    if jfif:
        payload = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        out += b"\xff\xe0" + struct.pack(">H", len(payload) + 2) + payload
    if ifd0_entries is not None:
        tiff = build_tiff(ifd0_entries, exif_entries)
        payload = b"Exif\x00\x00" + tiff
        out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    if comment is not None:
        payload = comment.encode("latin-1")
        out += b"\xff\xfe" + struct.pack(">H", len(payload) + 2) + payload
    out += b"\xff\xd9"
    return bytes(out)


def png_chunk(chunk_type: str, payload: bytes) -> bytes:
    """Wrap *payload* in a length-prefixed, CRC-terminated PNG chunk."""
    type_bytes = chunk_type.encode("ascii")
    crc = zlib.crc32(type_bytes + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + type_bytes + payload + struct.pack(">I", crc)


def build_png(
    width: int = 1,
    height: int = 1,
    texts: list[tuple[str, str]] | None = None,
    ztexts: list[tuple[str, str]] | None = None,
    itexts: list[tuple[str, str]] | None = None,
    include_idat: bool = True,
) -> bytes:
    """Build a tiny valid 8-bit truecolor PNG with optional text chunks.

    ``texts``/``ztexts``/``itexts`` are ``(keyword, value)`` pairs written
    as tEXt/zTXt/iTXt chunks respectively. A minimal IDAT for a black image
    is included by default so the file is renderable, not merely parseable.
    """
    parts = [b"\x89PNG\r\n\x1a\n"]
    parts.append(png_chunk("IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    for keyword, value in texts or []:
        parts.append(png_chunk("tEXt", keyword.encode("latin-1") + b"\x00" + value.encode("latin-1")))
    for keyword, value in ztexts or []:
        payload = keyword.encode("latin-1") + b"\x00\x00" + zlib.compress(value.encode("latin-1"))
        parts.append(png_chunk("zTXt", payload))
    for keyword, value in itexts or []:
        # keyword \0 flag=0 method=0 language="" \0 translated="" \0 text
        payload = keyword.encode("latin-1") + b"\x00\x00\x00\x00\x00" + value.encode("utf-8")
        parts.append(png_chunk("iTXt", payload))
    if include_idat:
        scanline = b"\x00" + b"\x00\x00\x00" * width  # filter byte + black RGB pixels
        parts.append(png_chunk("IDAT", zlib.compress(scanline * height)))
    parts.append(png_chunk("IEND", b""))
    return b"".join(parts)
