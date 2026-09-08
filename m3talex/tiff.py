"""TIFF/EXIF tag parsing, standard library only.

EXIF metadata is a TIFF structure embedded in a JPEG APP1 segment (after the
``Exif\\0\\0`` preamble). The layout is simple and fully documented:

* an 8-byte header: byte order (``II`` little / ``MM`` big), magic 42, and
  the offset of the first Image File Directory (IFD);
* each IFD: a 2-byte entry count, then 12-byte entries of
  ``(tag, type, count, value-or-offset)``, then a 4-byte next-IFD offset;
* values whose encoded size exceeds 4 bytes are stored out of line, with the
  entry's value field holding their offset from the TIFF header start.

Why hand-roll this: the format is stable, short, and read-only here; doing
it in ~150 lines means an evidence-handling tool carries zero third-party
code in its most security-sensitive path — parsing untrusted bytes.

Defensive posture: every offset and length is bounds-checked against the
buffer before it is dereferenced. Malformed structures raise
:class:`~m3talex.errors.FormatError`; individually unreadable entries are
skipped with a recorded warning so one corrupt tag cannot sink the whole
parse. Sub-IFD pointers are followed at most one level deep and visited
offsets are tracked, so a hostile or corrupt file cannot send the parser
into a loop.
"""

from __future__ import annotations

import struct

from .errors import FormatError

#: TIFF field type -> size in bytes of one value of that type.
_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}

#: TIFF field type -> struct format code for a single scalar value.
_SCALAR_FORMATS = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d"}

#: Tag names for IFD0 — the camera/file-level directory. Only tags an
#: investigator is likely to care about are named; the rest surface as
#: ``0xXXXX`` so nothing is silently dropped.
IFD0_TAGS = {
    0x010E: "ImageDescription",
    0x010F: "Make",
    0x0110: "Model",
    0x0112: "Orientation",
    0x0131: "Software",
    0x0132: "DateTime",
    0x013B: "Artist",
    0x8298: "Copyright",
    0x8769: "ExifIFDPointer",
    0x8825: "GPSInfoPointer",
}

#: Tag names for the EXIF sub-IFD, reached via the 0x8769 pointer.
EXIF_TAGS = {
    0x9000: "ExifVersion",
    0x9003: "DateTimeOriginal",
    0x9004: "DateTimeDigitized",
    0x9286: "UserComment",
    0xA002: "PixelXDimension",
    0xA003: "PixelYDimension",
    0xA434: "LensModel",
}

#: Tag names for the GPS sub-IFD, reached via the 0x8825 pointer. Raw
#: rationals are preserved as ``[numerator, denominator]`` pairs; converting
#: to decimal degrees is presentation work, not parsing work.
GPS_TAGS = {
    0x0000: "GPSVersionID",
    0x0001: "GPSLatitudeRef",
    0x0002: "GPSLatitude",
    0x0003: "GPSLongitudeRef",
    0x0004: "GPSLongitude",
    0x0005: "GPSAltitudeRef",
    0x0006: "GPSAltitude",
    0x0007: "GPSTimeStamp",
    0x001D: "GPSDateStamp",
}

#: Pointer tags followed one level deep, mapped to their tag dictionaries.
_SUB_IFDS = {"ExifIFDPointer": EXIF_TAGS, "GPSInfoPointer": GPS_TAGS}


def parse_tiff(data: bytes) -> dict:
    """Parse a TIFF/EXIF blob into a dictionary of directories.

    Returns ``{"ifd0": {...}, "exif": {...}, "gps": {...}, "warnings": [...]}``
    where the sub-IFD dictionaries are empty (not missing) when the file has
    no such directory. All values are JSON-serializable.
    """
    parser = _TiffParser(data)
    return parser.parse()


class _TiffParser:
    """Bounds-checking TIFF walker. Instantiated once per blob by parse_tiff."""

    def __init__(self, data: bytes) -> None:
        if len(data) < 8:
            raise FormatError(f"TIFF header truncated: {len(data)} byte(s)")
        if data[:2] == b"II":
            self._endian = "<"
        elif data[:2] == b"MM":
            self._endian = ">"
        else:
            raise FormatError(f"unrecognized TIFF byte order marker: {data[:2]!r}")
        (magic,) = struct.unpack_from(self._endian + "H", data, 2)
        if magic != 42:
            raise FormatError(f"bad TIFF magic number: {magic} (expected 42)")
        self._data = data
        self.warnings: list[str] = []

    def parse(self) -> dict:
        """Walk IFD0 plus any pointed-to EXIF/GPS sub-IFDs."""
        (ifd0_offset,) = struct.unpack_from(self._endian + "I", self._data, 4)
        ifd0 = self._read_ifd(ifd0_offset, IFD0_TAGS)
        result: dict = {"ifd0": ifd0, "exif": {}, "gps": {}, "warnings": self.warnings}

        visited = {ifd0_offset}  # loop guard for pointer chains
        for pointer_tag, tag_map in _SUB_IFDS.items():
            pointer = ifd0.get(pointer_tag)
            if not isinstance(pointer, int):
                continue
            if pointer in visited:
                self.warnings.append(f"{pointer_tag} forms a loop; ignored")
                continue
            visited.add(pointer)
            key = "exif" if pointer_tag == "ExifIFDPointer" else "gps"
            result[key] = self._read_ifd(pointer, tag_map)
        return result

    def _read_ifd(self, offset: int, tag_map: dict) -> dict:
        """Decode one IFD at *offset*, naming tags via *tag_map*."""
        if offset + 2 > len(self._data):
            self.warnings.append(f"IFD offset {offset} out of bounds; skipped")
            return {}
        (count,) = struct.unpack_from(self._endian + "H", self._data, offset)
        entries_start = offset + 2
        if entries_start + count * 12 > len(self._data):
            # Clamp rather than fail: a corrupt count byte should not cost
            # us the entries that are actually readable.
            count = max(0, (len(self._data) - entries_start) // 12)
            self.warnings.append("IFD entry count exceeds buffer; clamped")

        entries: dict = {}
        for index in range(count):
            entry_offset = entries_start + index * 12
            tag, field_type, value_count = struct.unpack_from(
                self._endian + "HHI", self._data, entry_offset
            )
            value = self._read_value(field_type, value_count, entry_offset + 8, tag)
            if value is not None:
                entries[tag_map.get(tag, f"0x{tag:04X}")] = value
        return entries

    def _read_value(self, field_type: int, count: int, field_offset: int, tag: int):
        """Decode one entry's value, following out-of-line offsets.

        Returns ``None`` (and records a warning) when the value cannot be
        read, so a single corrupt entry never aborts the directory.
        """
        unit = _TYPE_SIZES.get(field_type)
        if unit is None:
            self.warnings.append(f"tag 0x{tag:04X}: unknown field type {field_type}; skipped")
            return None
        total = unit * count
        if total <= 4:
            # Value is stored inline, left-justified in the 4-byte field,
            # regardless of byte order — reading from the field start is
            # correct for both endians.
            raw = self._data[field_offset : field_offset + total]
        else:
            (value_offset,) = struct.unpack_from(self._endian + "I", self._data, field_offset)
            if value_offset + total > len(self._data):
                self.warnings.append(f"tag 0x{tag:04X}: value offset out of bounds; skipped")
                return None
            raw = self._data[value_offset : value_offset + total]
        return self._decode(field_type, count, raw)

    def _decode(self, field_type: int, count: int, raw: bytes):
        """Turn raw bytes into a JSON-serializable Python value."""
        if field_type == 2:  # ASCII: NUL-terminated, camera-origin encoding
            return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
        if field_type in _SCALAR_FORMATS:
            fmt = self._endian + _SCALAR_FORMATS[field_type] * count
            values = struct.unpack(fmt, raw)
            return values[0] if count == 1 else list(values)
        if field_type in (5, 10):  # RATIONAL / SRATIONAL: numerator+denominator
            code = "I" if field_type == 5 else "i"
            pairs = struct.unpack(self._endian + (code + code) * count, raw)
            rationals = [[pairs[i], pairs[i + 1]] for i in range(0, len(pairs), 2)]
            return rationals[0] if count == 1 else rationals
        # UNDEFINED and anything else: hex string, truncated for readability.
        return raw[:64].hex() + ("…" if len(raw) > 64 else "")
