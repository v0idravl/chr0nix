#!/usr/bin/env python3
"""Regenerate the example images in examples/m3talex/images/ deterministically.

Every demo command in the README runs against these files. They are built
byte-by-byte by :mod:`tests.m3talex.samplegen` — no binary blobs, no mystery
provenance. Re-running this script reproduces identical files.

Run from anywhere:  python examples/m3talex/make_examples.py
"""

import sys
from pathlib import Path

# The builders live with the test suite (they ship no runtime purpose), so
# the repo root must be importable whichever directory this runs from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.m3talex.samplegen import _ASCII as ASCII, build_jpeg, build_png

IMAGES = Path(__file__).resolve().parent / "images"


def main() -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)

    # A clean camera original: consistent timestamps, no Software tag.
    # Expectation: zero findings.
    (IMAGES / "phone_photo.jpg").write_bytes(
        build_jpeg(
            ifd0_entries=[
                (0x010F, ASCII, "Apple"),
                (0x0110, ASCII, "iPhone 15 Pro"),
                (0x0132, ASCII, "2026:07:14 09:31:07"),
            ],
            exif_entries=[
                (0x9003, ASCII, "2026:07:14 09:31:07"),
                (0x9004, ASCII, "2026:07:14 09:31:07"),
            ],
        )
    )

    # An edited re-export: Photoshop signature, modify timestamp after
    # capture timestamp. Expectation: editing + timestamp-mismatch findings.
    (IMAGES / "edited_export.jpg").write_bytes(
        build_jpeg(
            ifd0_entries=[
                (0x010F, ASCII, "Canon"),
                (0x0110, ASCII, "Canon EOS R6"),
                (0x0131, ASCII, "Adobe Photoshop 26.1 (Macintosh)"),
                (0x0132, ASCII, "2026:08:02 14:05:55"),
            ],
            exif_entries=[
                (0x9003, ASCII, "2026:07:14 09:31:07"),
                (0x9004, ASCII, "2026:07:14 09:31:07"),
            ],
        )
    )

    # A stripped file: valid JPEG, no EXIF segment at all.
    # Expectation: missing-exif finding.
    (IMAGES / "stripped.jpg").write_bytes(build_jpeg())

    # A generator export with the classic Stable Diffusion parameter block.
    # Expectation: synthetic-media-indicator finding (high confidence).
    (IMAGES / "ai_render.png").write_bytes(
        build_png(
            texts=[
                (
                    "parameters",
                    "loading dock at night, wet asphalt, sodium lights\n"
                    "Negative prompt: blurry, watermark\n"
                    "Steps: 28, Sampler: Euler a, CFG scale: 7, "
                    "Seed: 4120508781, Size: 1024x1024, Model: sd_xl_base_1.0",
                )
            ]
        )
    )

    # An annotated PNG from an editor. Expectation: editing-software finding.
    (IMAGES / "annotated_diagram.png").write_bytes(
        build_png(
            texts=[
                ("Software", "GIMP 2.10.38"),
                ("Title", "Parking lot camera coverage sketch"),
            ]
        )
    )

    for path in sorted(IMAGES.iterdir()):
        print(f"wrote {path.relative_to(IMAGES.parent.parent)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
