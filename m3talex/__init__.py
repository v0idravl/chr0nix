"""m3talex — image metadata extraction and anomaly flagging.

m3talex is a small, read-only forensic documentation tool. It parses the
structures that carry metadata inside the two formats that dominate
investigative image collections — JPEG (EXIF inside APP1, via a hand-rolled
TIFF/IFD walker) and PNG (text chunks via a chunk walker) — using nothing
but the Python standard library.

Design decisions worth knowing up front:

* **No Pillow, no dependencies.** The binary layouts of JPEG segments, TIFF
  IFDs, and PNG chunks are short, stable, publicly documented formats.
  Implementing them directly keeps the tool auditable end-to-end and removes
  supply-chain surface from an evidence-handling workflow.
* **Read-only on inputs.** The tool never opens an input file for writing,
  and the CLI refuses to place its own output inside the evidence directory
  it was pointed at.
* **Observations, not verdicts.** Anomaly heuristics emit findings phrased
  as "consistent with …" plus a confidence level. Metadata inconsistencies
  are investigative leads; the tool deliberately never says "fake".
* **Everything is hashed.** Every input image is SHA-256-hashed into its
  report so a reviewer can tie a finding to an exact byte sequence.

The package is organized as a pipeline: format parsers (:mod:`m3talex.tiff`,
:mod:`m3talex.jpeg`, :mod:`m3talex.png`) → normalization
(:mod:`m3talex.analyze`) → heuristics (:mod:`m3talex.anomalies`) → rendering
(:mod:`m3talex.report`), orchestrated by :mod:`m3talex.cli`.
"""

__version__ = "1.0.0"

#: Tool name stamped into every report and manifest the package emits.
TOOL_NAME = "m3talex"
