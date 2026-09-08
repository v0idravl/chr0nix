"""Report rendering: per-image JSON, batch Markdown, batch manifests.

Three artifacts, three audiences:

* **Per-image JSON** — the complete machine-readable record, one file per
  image. Keys are sorted and indentation fixed so two runs over unchanged
  inputs produce byte-identical reports apart from the timestamp.
* **Batch Markdown** — the human-readable summary an investigator pastes
  into a case file: one summary table, then per-image finding details.
* **Manifests (CSV + JSON)** — the shared *cust0dia* interchange
  format, so m3talex output slots into the same chain-of-custody workflow
  as the other suite tools.

All renderers sort by relative path; nothing here depends on dictionary or
filesystem iteration order.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import TOOL_NAME, __version__
from .integrity import utc_now_iso, write_manifest_csv, write_manifest_json

#: Batch report and manifest filenames, fixed so scripts can rely on them.
BATCH_REPORT_NAME = "m3talex-report.md"
MANIFEST_CSV_NAME = "manifest.csv"
MANIFEST_JSON_NAME = "manifest.json"


def report_filename(relative_path: str) -> str:
    """Derive a collision-free report filename from an image's relative path.

    Path separators become ``__`` so images from different subdirectories
    with the same basename never overwrite each other's reports.
    """
    return relative_path.replace("/", "__") + ".meta.json"


def write_json_report(record: dict, outdir: Path, filename: str | None = None) -> Path:
    """Write one image's record as pretty-printed, key-sorted JSON."""
    destination = outdir / (filename or report_filename(record["file"]["relative_path"]))
    destination.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def render_batch_markdown(records: list[dict], root: Path) -> str:
    """Render the batch summary document for *records* (already sorted)."""
    generated = utc_now_iso()
    with_findings = sum(1 for record in records if record["findings"])

    lines = [
        "# m3talex batch report",
        "",
        f"- Tool: {TOOL_NAME} {__version__}",
        f"- Generated (UTC): {generated}",
        f"- Root analyzed: `{root}`",
        f"- Images analyzed: {len(records)}",
        f"- Images with findings: {with_findings}",
        "",
        "Findings are observations with confidence levels, not verdicts. "
        "Each links to a per-image JSON report containing the full record, "
        "including the SHA-256 of the exact bytes analyzed.",
        "",
        "## Summary",
        "",
        "| File | Format | Size (bytes) | SHA-256 (first 16) | Software | Findings |",
        "|---|---|---|---|---|---|",
    ]
    for record in records:
        file_info = record["file"]
        software = record["metadata"].get("software") or "—"
        lines.append(
            f"| `{record['file']['relative_path']}` "
            f"| {file_info['format']} "
            f"| {file_info['size_bytes']} "
            f"| `{file_info['sha256'][:16]}` "
            f"| {_escape(software)} "
            f"| {len(record['findings'])} |"
        )

    lines += ["", "## Findings by image", ""]
    for record in records:
        rel = record["file"]["relative_path"]
        lines.append(f"### `{rel}`")
        lines.append("")
        if not record["findings"]:
            lines.append("No anomalies flagged.")
        for finding in record["findings"]:
            lines.append(
                f"- **{finding['id']}** (confidence: {finding['confidence']}) — "
                f"{finding['observation']} _Evidence: {_escape(finding['evidence'])}_"
            )
        for note in record["notes"]:
            lines.append(f"- Note: {note}")
        for warning in record["parse_warnings"]:
            lines.append(f"- Parse warning: {_escape(warning)}")
        lines.append("")

    lines += [
        "---",
        "",
        "_m3talex records what a file says about itself — and what it "
        "conspicuously does not. For lawful, authorized investigative "
        "documentation work only._",
        "",
    ]
    return "\n".join(lines)


def write_batch_outputs(
    records: list[dict], manifest_entries: list[dict], outdir: Path, root: Path
) -> dict:
    """Write every batch artifact; returns a name → path map."""
    written: dict[str, Path] = {}
    for record in records:
        path = write_json_report(record, outdir)
        written[f"json:{record['file']['relative_path']}"] = path
    report_path = outdir / BATCH_REPORT_NAME
    report_path.write_text(render_batch_markdown(records, root), encoding="utf-8")
    written["markdown"] = report_path
    written["manifest_csv"] = write_manifest_csv(manifest_entries, outdir / MANIFEST_CSV_NAME)
    written["manifest_json"] = write_manifest_json(manifest_entries, outdir / MANIFEST_JSON_NAME, root)
    return written


def _escape(text: str) -> str:
    """Escape Markdown table metacharacters in metadata values."""
    return str(text).replace("|", "\\|").replace("\n", " ")
