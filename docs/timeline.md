# chr0nix timeline

chr0nix timeline normalizes incident exports from multiple systems — AP case
management, CCTV bookmark logs, POS back-office servers, officer notes — into
a single UTC-ordered, hash-manifested exhibit timeline. Every row carries a
citation back to its source file and line number, and every input file is
fingerprinted with SHA-256 into a manifest in the shared suite format.

Cases die on muddled timelines. A store DVR stamps store-local wall-clock
time, a POS server logs UTC, an alarm panel reports in the monitoring
center's timezone, and an officer's bodycam may not have observed the DST
transition at all. Concatenate those exports naively and you get a timeline
that contradicts itself — exactly what a defense attorney looks for. chr0nix
timeline exists to make that class of error impossible to ship: three
systems, three timezones, one timeline, with every row traceable to its
source and every ambiguity flagged rather than silently guessed. That is what
"documented, corroborated, prosecution-ready" means in practice.

The tool is intentionally conservative. It never modifies an input file, it
refuses to write its outputs anywhere near the evidence, it never guesses a
timezone, and it treats an ambiguous timestamp as a finding to report — not a
problem to quietly paper over. chr0nix timeline is for lawful, authorized
investigative documentation work only.

---

## 30-second demo

The shipped `examples/timeline/sources/` data tells one story: an overnight
burglary at Store 114 on the night of the 2025 DST fall-back, recorded by
four systems in three timezones — including a DVR bookmark at a wall-clock
time that occurred twice and a bodycam whose clock never fell back.

```bash
chr0nix timeline build \
  --source ap=examples/timeline/sources/ap_incidents.csv --tz ap=America/Chicago \
  --source cctv=examples/timeline/sources/cctv_bookmarks.csv --tz cctv=America/Los_Angeles \
  --source pos=examples/timeline/sources/pos_backoffice.csv --tz pos=UTC \
  --source notes=examples/timeline/sources/officer_notes.csv --tz notes=America/Los_Angeles \
  --title "Case 2025-1102 — Overnight burglary, Store 114" \
  --out examples/out
```

(`chr0nix timeline ...` and `python -m chr0nix.timeline ...` are the same
CLI; from an unpacked repo without installing, use the `python -m` form.)

Expect two warnings on stderr: the DVR's `01:31:05` bookmark is ambiguous
(it occurs twice during the fall-back, so it is flagged
`AMBIGUOUS_LOCAL_TIME`) and the officer's second note carries an offset that
contradicts Pacific time at that instant (`OFFSET_TZ_MISMATCH`). Both rows
are placed deterministically and flagged in every output.

```bash
cat examples/out/timeline.md
cat examples/out/timeline.csv
python -m unittest
```

## Purpose

- Merge incident CSV exports from any number of source systems into one
  chronological exhibit timeline, ordered by true UTC instant.
- Normalize every timestamp with an explicitly declared timezone per source —
  never a guessed one — and flag DST edge cases (fall-back folds,
  spring-forward gaps, offset/timezone mismatches) for human review.
- Preserve provenance: every output row cites its source identifier, source
  file row number, raw timestamp, and declared timezone.
- Fingerprint all inputs into a SHA-256 manifest (CSV + JSON, shared suite
  format) so the timeline's evidentiary basis can be verified later.
- Produce outputs that diff cleanly: deterministic ordering, fixed columns,
  LF line endings.

## Security model

- **Standard library only.** Python 3.11+; zero third-party dependencies,
  including tests (`unittest` only).
- **Fully offline.** No network calls, ever — there is nothing in the
  dependency tree to make one with.
- **Read-only on inputs.** Source files are opened read-only, and the tool
  refuses to write outputs into an evidence/input directory, into any
  directory nested inside one, or into any directory that contains an input.
- **Fail closed, in two phases.** All input validation (schema, timezone,
  every timestamp of every row) completes before a single output file is
  written — a failed run leaves no partial artifacts behind.
- **Small and auditable.** A handful of focused modules under
  `chr0nix/timeline/`, heavily documented; the entire package can be read
  end-to-end in well under an hour.

## Usage

### `build` — normalize, merge, render, and manifest

```bash
chr0nix timeline build \
  --source cctv=dvr_export.csv --tz cctv=America/Los_Angeles \
  --source pos=pos_log.csv      --tz pos=UTC \
  --out case_output/
```

Registers each source CSV under a short identifier, declares each source's
timezone, and writes four files to `--out`: `timeline.csv`, `timeline.md`,
`manifest.csv`, and `manifest.json`.

- `--source NAME=PATH` (repeatable, required) — register a source CSV. Names
  must match `[A-Za-z0-9_-]{1,32}`.
- `--tz NAME=IANA_TZ` (repeatable) — declare a source's timezone. Required
  for any source whose rows have naive timestamps; optional (but
  cross-checked) for sources whose rows carry explicit UTC offsets.
- `--out DIR` (required) — output directory. Must be disjoint from every
  input/evidence directory, or the run is refused.
- `--title TEXT` — case title rendered into the Markdown report header.
- `--strict` — exit with code 3 (writing nothing) if any row is flagged.
  Use this when a filed exhibit must contain zero unresolved ambiguities.

A source with naive timestamps and no declared `--tz` fails the run —
chr0nix timeline does not guess. Rows with explicit offsets (e.g.
`2025-11-02T02:12:44-08:00` or `...Z`) stand on their recorded offset and
need no `--tz`.

### `schema` — the input contract

```bash
chr0nix timeline schema                      # print the schema
chr0nix timeline schema --template new.csv   # write an empty header row
```

Every source CSV uses the same minimal schema: required columns `event_id`,
`timestamp`, `event_type`, `description`; optional columns `location`,
`reference`. Timestamps must be ISO-8601. Extra columns are ignored with a
warning, so verbose real-world exports can be trimmed to the schema with a
simple column mapping.

### In the console

The same pipeline is reachable interactively: `python -m chr0nix console`,
then `use timeline`. `run` builds the timeline from the session's evidence
directory into the session output; `build <sources-dir> [output-dir]
[NAME=IANA_TZ ...]` registers every `*.csv` under a directory as a source;
`schema` prints the input contract. See
[docs/console.md](console.md).

## Current capabilities

1. **Multi-source normalization.** Any number of sources, each with an
   explicit `--tz` (any IANA name, or `UTC`). Naive timestamps are
   interpreted in the declared timezone; offset-aware timestamps are honored
   as recorded.
2. **DST edge-case handling.** Fall-back folds are placed at the first
   occurrence and flagged `AMBIGUOUS_LOCAL_TIME`; spring-forward gaps are
   resolved against the post-transition offset and flagged
   `NONEXISTENT_LOCAL_TIME`; recorded offsets that contradict the declared
   timezone are honored but flagged `OFFSET_TZ_MISMATCH`. Flagged rows are
   reported on stderr, marked in both output formats, and explained in the
   Markdown report's flag legend.
3. **Deterministic unified timeline.** Events are sorted by UTC instant with
   ties broken by source name and source row — so identical timestamps
   across systems (corroboration) always render in the same reproducible
   order, and repeated runs produce byte-identical `timeline.csv` output.
4. **Dual rendering.** `timeline.csv` for machines and diffing (fixed
   columns, LF endings, one-based sequence numbers); `timeline.md` as a
   chronological narrative grouped by UTC date, with a source provenance
   table and per-event citations.
5. **SHA-256 input manifest.** Every input file is hashed (read-only) into
   `manifest.csv` and `manifest.json` in the shared suite format
   (`relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc` / JSON object
   with `tool`, `generated_at_utc`, `root`, `entries`), so the exact inputs
   behind a timeline can be re-verified at any time.
6. **Evidence-boundary enforcement.** Output locations that touch the
   evidence — the input's directory, anything inside it, or anything
   containing an input — are refused before any work begins.

## Known limitations

- Input must already be CSV shaped to the chr0nix schema; the tool does not
  map proprietary export formats. Trim exports to the six schema columns
  first (`chr0nix timeline schema --template` gives the header).
- Timestamps must be ISO-8601. Slash dates (`11/02/2025`), month names, and
  epoch integers are rejected rather than heuristically parsed — parsing
  ambiguity is exactly what the tool exists to eliminate.
- Ambiguous and nonexistent local times are resolved by documented,
  deterministic policy (first occurrence; post-transition offset) and
  flagged. chr0nix timeline flags these rows for review; it does not and
  cannot know which interpretation the source device intended.
- The entire timeline is held in memory. This is deliberate — case exports
  are thousands of rows, not billions — but chr0nix timeline is not a
  big-data tool.
- Sub-second precision is preserved when present, but cross-system ordering
  below one second is only as meaningful as the source clocks'
  synchronization.

## Notes

- Exit codes: `0` success; `2` usage or validation error (matching
  `argparse`); `3` success blocked by `--strict` due to flagged rows.
- `timeline.csv` and the manifest's row ordering are fully deterministic;
  `timeline.md` and the manifest timestamps record the run time, so diff
  those artifacts with the header/timestamp lines in mind.
- Run the test suite from the repo root with `python -m unittest`.
- Outputs land in the directory given by `--out`; the repository's
  `examples/out/` is git-ignored so demo runs never dirty the tree.
