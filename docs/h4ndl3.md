```text
██╗  ██╗██╗  ██╗███╗   ██╗██████╗ ██╗     ██████╗
██║  ██║██║  ██║████╗  ██║██╔══██╗██║     ╚════██╗
███████║███████║██╔██╗ ██║██║  ██║██║      █████╔╝
██╔══██║╚════██║██║╚██╗██║██║  ██║██║      ╚═══██╗
██║  ██║     ██║██║ ╚████║██████╔╝███████╗██████╔╝
╚═╝  ╚═╝     ╚═╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚═════╝

  offline-first identifier research worksheets · corroboration before claims
```

**h4ndl3 is an offline-first identifier research worksheet CLI** — give
it one identifier (a username, an email address, or a domain) and it
produces a structured research worksheet: which public sources to check,
what to record from each, and how to record it.

Findings go into a strictly validated JSONL store, and a Markdown report
renderer summarizes exactly which claims are corroborated and which are
still leads. The tool exists because the center of gravity in OSINT work
has shifted from collection to verification. Platforms closed their
APIs, scraping against terms of service is both an ethics problem and an
employer-policy problem, and AI-generated profiles make unverified
"hits" worse than no hits at all. The professional skill is no longer
firing a scraper — it is running a defensible, documented process.
h4ndl3 encodes that process in software: a documented source, a
documented time, and two independent corroborations before anything is
called a claim.

The restraint is built in on purpose, and it is the point of the tool.
h4ndl3 contains no network code at all — not optional, not behind a
flag, not even an import of an HTTP library. It cannot scrape, so it
cannot scrape improperly. The fast way and the compliant way are the
same way: the worksheet tells you what to check manually, and the store
refuses to accept a finding that lacks provenance.

> ⚠️ **Authorized use only.** h4ndl3 is intended strictly for lawful,
> authorized investigative documentation work — employer-authorized
> casework, public sources only. It is a defensive documentation tool:
> it performs no lookups, accesses no systems, and collects nothing on
> its own. Plates, restricted records, and professional-tier databases
> are out of scope and belong in employer systems.

---

## ⚡ Quick start

Generate a worksheet for a username, record one finding with full
provenance, then validate and render the shipped example store into a
report:

```bash
mkdir -p out
python -m h4ndl3 worksheet "j.doe_91" --type username --store out/findings.jsonl --out out/worksheet.md

python -m h4ndl3 add --store out/findings.jsonl \
    --claim "Handle resolves to a public profile" \
    --source-url "https://example-social.example/users/j.doe_91" \
    --retrieved-at "2026-08-31T09:14:22Z" \
    --confidence medium \
    --corroborated-by "https://example-forum.example/members/j.doe_91" "https://web.archive.example/snap/example-social-j.doe_91"

python -m h4ndl3 validate --store examples/h4ndl3/findings.jsonl
python -m h4ndl3 report --store examples/h4ndl3/findings.jsonl --out out/report.md
```

`out/report.md` shows the corroboration summary: the example store
contains two corroborated findings and one explicitly flagged as an
uncorroborated lead. Finish by hashing everything produced into a
shared-format integrity manifest:

```bash
python -m h4ndl3 manifest --root examples --out out/manifest.csv
```

---

## 🧠 What it does

- Generate structured research worksheets mapping an identifier type
  (username, email, domain) to a checklist of lawful public checks, each
  with its lawful basis and recording guidance stated in writing.
- Store findings in an append-only JSONL log where every row is strictly
  validated: source URL, retrieved-at UTC timestamp, confidence level,
  and corroborating sources are mandatory.
- Render Markdown reports whose corroboration summary enforces one
  rule — a claim is corroborated only when two independent sources back
  it; anything less is presented as a lead.
- Produce SHA-256 integrity manifests of case outputs in the format
  shared across this tool suite.
- Make the compliant workflow the path of least resistance: the tool
  cannot take shortcuts because the shortcuts do not exist in it.

### What this demonstrates

h4ndl3 evidences the professional skills that matter in modern
investigative work: designing a verification-first methodology and
encoding it in software, strict input validation and provenance
enforcement at a data-store boundary, deterministic and reproducible
artifact generation for review, and integrity manifesting compatible
with a wider tool suite. It shows restraint as an engineering
decision — the compliant process is not a policy bolted on top of the
tool, it is the only process the tool can run.

---

## 🔒 Security model

- Standard library only; zero third-party dependencies, including tests.
- Fully offline: no network calls, no sockets, no HTTP — there is no
  lookup code of any kind in the codebase.
- Read-only on inputs: original evidence is never modified, and the tool
  refuses to overwrite an input file or write outputs inside a directory
  it is documenting.
- Identifier sanitization: usernames, emails, and domains are validated
  against strict character sets before they are embedded in any output.
- Small and auditable: every module fits in one reading; the entire
  methodology is plain data you can review in minutes.

---

## 🛠 Install

Requirements: Python 3.11 or newer. Nothing else.

```bash
git clone https://github.com/v0idravl/chr0nix.git
cd chr0nix
```

There is no install step and no dependency resolution — run the tool in
place with `python -m h4ndl3` from the repository root.

---

## Usage

### `worksheet` — generate a research worksheet

```bash
python -m h4ndl3 worksheet "j.doe_91" --type username --out out/worksheet.md
python -m h4ndl3 worksheet "shop-example.net" --now 2026-08-31T12:00:00Z
```

- `identifier` — default: — (required). Username, email, or domain to
  build the worksheet around.
- `--type` — default: auto-detected from shape. Explicit identifier type
  (`username`, `email`, `domain`).
- `--out` — default: stdout. File path to write the worksheet to.
- `--store` — default: —. Findings-store path embedded in the
  worksheet's ready-to-use `add` command template.
- `--now` — default: current UTC time. Pins the stamped timestamp for
  byte-reproducible output.

Identifier type is auto-detected from shape unless `--type` is given.
Output goes to stdout unless `--out` is provided.

### `add` — append a validated finding

```bash
python -m h4ndl3 add --store findings.jsonl \
    --claim "Registration record shows creation date 2024-03-11" \
    --source-url "https://rdap.example/shop-example.net" \
    --retrieved-at "2026-08-31T09:14:22Z" \
    --confidence high \
    --corroborated-by "https://ctlogs.example/?q=shop-example.net" \
    --notes "Registrar data viewed via public RDAP web interface"
```

- `--store` — default: — (required). Path to the JSONL findings store;
  created if it does not exist.
- `--claim` — default: — (required). The claim being recorded.
- `--source-url` — default: — (required). Absolute http/https URL of the
  source.
- `--retrieved-at` — default: — (required). UTC ISO-8601 timestamp of
  when the source was retrieved.
- `--confidence` — default: — (required). `low`, `medium`, or `high`.
- `--corroborated-by` — default: —. Independent corroborating source
  URLs (the `source_url` itself is rejected — a source cannot
  corroborate itself).
- `--notes` — default: —. Free-text notes on the finding.

Every required field must be present and valid or nothing is written.
Existing rows are never modified.

### `validate` — re-validate an existing store

```bash
python -m h4ndl3 validate --store findings.jsonl
```

Validates every row and reports the count, or names the offending line.
Useful after hand edits and before handing a store to a reviewer.

### `report` — render a Markdown report

```bash
python -m h4ndl3 report --store findings.jsonl --out out/report.md --title "Case 26-081 — Handle Pivot"
```

| Argument | Default | Description |
| --- | --- | --- |
| `--store` | — (required) | Path to the JSONL findings store to render. |
| `--out` | stdout | File path to write the report to. |
| `--title` | — | Report title. |

Renders findings sorted deterministically, each tagged CORROBORATED (2+
independent sources), PARTIAL (1), or UNCORROBORATED (0 — shown as a
lead, not a claim). Refuses to overwrite the store it reads from.

### `manifest` — hash outputs into an integrity manifest

```bash
python -m h4ndl3 manifest --root out --out manifests/out-manifest.csv --format csv
python -m h4ndl3 manifest --root out --out manifests/out-manifest.json --format json
```

| Argument | Default | Description |
| --- | --- | --- |
| `--root` | — (required) | Directory to recursively hash. |
| `--out` | — (required) | Manifest output path; must not be inside `--root`. |
| `--format` | — | `csv` or `json`. |

Recursively hashes regular files under `--root` (SHA-256) and writes the
shared suite format: CSV with header
`relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc`, rows sorted
by path; or JSON with keys `tool`, `generated_at_utc`, `root`,
`entries`. Refuses to write the manifest inside the directory it
describes.

---

## ✅ Current capabilities

1. **Worksheet generation (offline).** Three identifier types, each
   mapped to a curated checklist of lawful public checks. Every check
   states why it is lawful and exactly what to record, so the worksheet
   doubles as documentation of a defensible methodology.
2. **Strictly validated findings store.** JSONL, append-only, validated
   on every read and write. Required fields: `claim`, `source_url`
   (absolute http/https), `retrieved_at_utc` (explicitly UTC ISO-8601),
   `confidence` (low/medium/high), `corroborated_by` (independent URLs
   only). Unknown fields and self-corroboration are rejected.
3. **Markdown report with corroboration summary.** Status counts,
   confidence counts, and per-finding provenance; uncorroborated entries
   are labeled leads in the rendered document itself.
4. **Shared-format integrity manifests.** CSV and JSON manifests of
   output directories, deterministic and compatible with the rest of the
   tool suite.
5. **Reproducible output.** Deterministic sorting throughout plus a
   `--now` flag on every command that stamps time, so identical inputs
   produce byte-identical artifacts.

---

## ⚠️ Known limitations

- The tool performs no lookups at all. The worksheet tells you *what* to
  check; the checking is manual, by design. Analysts expecting
  automation will find none.
- Corroboration is counted per finding from its `corroborated_by` list;
  the tool does not reason about source independence beyond rejecting
  self-corroboration — judging whether two sources are truly independent
  remains the analyst's job.
- The store has no case or subject field; one store per subject/case is
  the intended discipline, enforced by convention rather than schema.
- Identifier auto-detection is a shape heuristic; an unusual handle that
  looks like a domain needs an explicit `--type`.
- No multi-user or concurrent-write handling: the store assumes a single
  analyst appending from one process at a time.

---

## 📝 Notes

- Intended strictly for lawful, authorized investigative documentation
  work — employer-authorized casework, public sources only. Plates,
  restricted records, and professional-tier databases are out of scope
  and belong in employer systems.
- All timestamps are UTC ISO-8601. Naive or non-UTC timestamps are
  rejected at the store boundary so records survive cross-timezone
  review.
- `examples/h4ndl3/findings.jsonl` is synthetic fixture data for demonstration;
  it documents no real person or entity.
- Run the test suite with `python -m unittest` from the repository root.
