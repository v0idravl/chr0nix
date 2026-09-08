"""PNG chunk walking and text-chunk extraction.

A PNG file is an 8-byte signature followed by chunks of the form
``length:4 | type:4 | data | CRC32:4`` (all big-endian, CRC over
type+data). PNG has no EXIF; its metadata lives almost entirely in the
three text chunk types, all of which are keyword/value pairs:

* ``tEXt`` — Latin-1 keyword, NUL, Latin-1 text;
* ``zTXt`` — same, but the text is zlib-compressed (method byte 0);
* ``iTXt`` — keyword, NUL, compression flag+method, language tag, NUL,
  translated keyword, NUL, UTF-8 text (optionally zlib-compressed).

Text chunks matter disproportionately in 2026 casework: mainstream
image generators (Stable Diffusion front ends in particular) habitually
embed full generation parameters in a ``parameters`` tEXt chunk, and
editors like GIMP stamp a ``Software`` keyword. The chunk walk itself is
short and fully offline; CRC mismatches are recorded as warnings rather
than fatal, because a damaged checksum is itself an observation worth
preserving in the report.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

from .errors import FormatError

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Chunk types whose payloads this module decodes into keyword/text pairs.
_TEXT_CHUNK_TYPES = ("tEXt", "zTXt", "iTXt")

#: IHDR color types, named for readability in reports.
_COLOR_TYPES = {0: "grayscale", 2: "truecolor", 3: "indexed", 4: "grayscale+alpha", 6: "truecolor+alpha"}


@dataclass
class TextChunk:
    """One decoded PNG text chunk."""

    chunk_type: str
    keyword: str
    text: str


@dataclass
class PngInfo:
    """Structured result of parsing one PNG file."""

    width: int | None = None
    height: int | None = None
    bit_depth: int | None = None
    color_type: str | None = None
    text_chunks: list[TextChunk] = field(default_factory=list)
    chunk_types: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_png(data: bytes) -> PngInfo:
    """Walk all chunks of a PNG and decode its metadata.

    Raises :class:`~m3talex.errors.FormatError` on a bad signature or a
    truncated chunk table; per-chunk problems (bad CRC, undecodable text)
    are warnings so one damaged chunk cannot hide the rest of the file.
    """
    if not data.startswith(_PNG_SIGNATURE):
        raise FormatError("not a PNG: bad 8-byte signature")

    info = PngInfo()
    position = len(_PNG_SIGNATURE)
    while position + 8 <= len(data):
        (length,) = struct.unpack_from(">I", data, position)
        chunk_type = data[position + 4 : position + 8]
        if position + 12 + length > len(data):
            raise FormatError(f"truncated PNG: chunk at offset {position} runs past EOF")
        payload = data[position + 8 : position + 8 + length]
        (declared_crc,) = struct.unpack_from(">I", data, position + 8 + length)
        position += 12 + length

        try:
            type_name = chunk_type.decode("ascii")
        except UnicodeDecodeError:
            info.warnings.append(f"non-ASCII chunk type at offset {position}; skipped")
            continue
        info.chunk_types.append(type_name)

        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if actual_crc != declared_crc:
            info.warnings.append(f"CRC mismatch in {type_name} chunk")

        if type_name == "IHDR":
            _parse_ihdr(info, payload)
        elif type_name in _TEXT_CHUNK_TYPES:
            _parse_text_chunk(info, type_name, payload)
        if type_name == "IEND":
            break
    return info


def _parse_ihdr(info: PngInfo, payload: bytes) -> None:
    """Decode the fixed 13-byte IHDR header."""
    if len(payload) < 13:
        info.warnings.append("IHDR chunk truncated; dimensions unavailable")
        return
    width, height, bit_depth, color_type = struct.unpack_from(">IIBB", payload, 0)
    info.width = width
    info.height = height
    info.bit_depth = bit_depth
    info.color_type = _COLOR_TYPES.get(color_type, f"unknown({color_type})")


def _parse_text_chunk(info: PngInfo, chunk_type: str, payload: bytes) -> None:
    """Decode one tEXt/zTXt/iTXt payload into a TextChunk, if possible."""
    try:
        if chunk_type == "tEXt":
            keyword, rest = _split_latin1(payload)
            text = rest.decode("latin-1", errors="replace")
        elif chunk_type == "zTXt":
            keyword, rest = _split_latin1(payload)
            if not rest or rest[0] != 0:
                raise FormatError("zTXt declares an unsupported compression method")
            text = zlib.decompress(rest[1:]).decode("latin-1", errors="replace")
        else:  # iTXt: keyword \0 flag method language \0 translated \0 text
            keyword, rest = _split_latin1(payload)
            if len(rest) < 2:
                raise FormatError("iTXt missing compression flag/method bytes")
            compressed = rest[0] == 1
            remainder = rest[2:]
            # Skip the language tag and translated keyword, both NUL-terminated.
            for _ in range(2):
                nul = remainder.find(b"\x00")
                if nul < 0:
                    raise FormatError("iTXt missing NUL-terminated fields")
                remainder = remainder[nul + 1 :]
            if compressed:
                remainder = zlib.decompress(remainder)
            text = remainder.decode("utf-8", errors="replace")
    except (FormatError, zlib.error) as exc:
        info.warnings.append(f"undecodable {chunk_type} chunk: {exc}")
        return
    info.text_chunks.append(TextChunk(chunk_type=chunk_type, keyword=keyword, text=text))


def _split_latin1(payload: bytes) -> tuple[str, bytes]:
    """Split a NUL-separated keyword from the rest of a text payload."""
    nul = payload.find(b"\x00")
    if nul < 0:
        raise FormatError("text chunk has no NUL keyword terminator")
    return payload[:nul].decode("latin-1", errors="replace"), payload[nul + 1 :]
