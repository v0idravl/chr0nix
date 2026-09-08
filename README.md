```text
 ██████╗██╗  ██╗██████╗  ██████╗ ███╗   ██╗██╗██╗  ██╗
██╔════╝██║  ██║██╔══██╗██╔═████╗████╗  ██║██║╚██╗██╔╝
██║     ███████║██████╔╝██║██╔██║██╔██╗ ██║██║ ╚███╔╝
██║     ██╔══██║██╔══██╗████╔╝██║██║╚██╗██║██║ ██╔██╗
╚██████╗██║  ██║██║  ██║╚██████╔╝██║ ╚████║██║██╔╝ ██╗
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝╚═╝  ╚═╝

  the investigative-documentation suite · one repo · one security model
```

**chr0nix is the consolidated investigative-documentation suite** —
small, stdlib-only Python tools for documenting digital evidence, plus
case-management and research-guidance layers, developed together in a
single monorepo under a single security model. This repository
supersedes the standalone `cust0dia`, `h4ndl3`, and `m3talex`
repositories: all four modules live here, share their conventions, and
are tested together from the repo root.

The suite exists because defensible investigative documentation is a set
of habits, not a feature: hash everything at collection, timestamp
everything in UTC, never modify an original, flag ambiguity instead of
guessing, and keep every line of code small enough that a reviewer, an
attorney, or a court can audit it end-to-end. Each module automates one
of those habits:

- **cust0dia** — recursive SHA-256 exhibit manifests (CSV + JSON) and an
  append-only, manifest-anchored chain-of-custody log. Hash at
  collection, log every touch, verify before reporting.
- **chr0nix/timeline** — normalizes incident exports from multiple
  systems (case management, CCTV, POS, officer notes) into one
  UTC-ordered exhibit timeline, with per-row source citations, declared
  — never guessed — timezones, and DST edge cases flagged for review.
- **h4ndl3** — offline-first identifier research worksheets: which
  public sources to check, what to record, and a corroboration-gated
  findings store that refuses to call anything a claim without
  provenance.
- **m3talex** — read-only image metadata extraction (hand-rolled EXIF /
  PNG chunk parsing) and anomaly flagging: stripped metadata,
  editing-software signatures, timestamp inconsistencies,
  synthetic-media indicators.
- **casework** *(console-native)* — case workspaces: cases with a fixed
  status chain, investigator-editable category and taxonomy
  vocabularies, entity linking with visible associations, append-only
  event logs, and generated case synopses.
- **guide** *(console-native)* — an offline knowledge base of research
  methods: what to check, where (browser handoffs printed, never
  opened), what's high-ROI, and a tiered capture flow that records
  findings into the active case.

On top of the modules sits the **suite shell**: an interactive curses
console (`python -m chr0nix console`, Linux/macOS) with a
metasploit-style `use` / `set` / `run` interface, a static, in-code tool
registry, and a **legal-risk tier system** — person-affecting actions
require an attested `ack <reason>` before they execute. One operator
session over the exact same core modules the CLIs use.

> ⚠️ **Authorized use only.** Every tool in this suite is a defensive
> documentation tool for lawful, authorized investigative work —
> recording, verifying, and correlating evidence you are entitled to
> handle. Nothing in this repository collects anything you are not
> entitled to collect, and nothing in it makes a network call.

---

## ⚡ Quick start

Everything runs from the repository root with `python -m`; fictional
demo data ships under `examples/<module>/`.

```bash
# Hash a case folder into a manifest, then verify it later
python -m cust0dia manifest examples/cust0dia/case-2026-014 --output-dir out/demo
python -m cust0dia verify out/demo/manifest.json examples/cust0dia/case-2026-014

# Merge multi-source incident exports into one UTC timeline
python -m chr0nix.timeline --help

# Build an identifier research worksheet
python -m h4ndl3 --help

# Extract and flag image metadata
python -m m3talex --help

# Or drive the whole suite from the interactive console
python -m chr0nix console
```

`out/` is disposable demo output and is git-ignored; delete it whenever
you like. Full per-module walkthroughs live in `docs/` (see below).

---

## 🧠 What it does

- Consolidate four previously standalone investigative-documentation
  tools — plus the casework and guide layers — into **one repo and one
  security model**: shared conventions (UTC everywhere, deterministic
  diff-friendly output, evidence/output separation), shared manifest
  format, one test suite, one audit surface.
- Make evidence integrity a default habit rather than a manual chore —
  manifests and custody logs (cust0dia), corroborated timelines
  (chr0nix/timeline), corroboration-gated research (h4ndl3), documented
  image assessment (m3talex), attested case management (casework).
- Provide a single interactive front end (the suite console) that adds
  no new trust surface: no dependencies, no network paths, no dynamic
  code loading.
- Stay small enough that any reviewer can read the entire codebase
  end-to-end in one sitting.

### Repository layout

```text
chr0nix/            suite package: shell, console, timeline module, and the
                    console-native layers (casework/, guide/) + tiers.py
cust0dia/           module package: manifests + chain of custody
h4ndl3/             module package: identifier research worksheets
m3talex/            module package: image metadata + anomaly flags
tests/              unified unittest suite, one subdirectory per module
examples/           fictional demo data, one subdirectory per module
docs/               per-module documentation (cust0dia.md, h4ndl3.md, ...)
```

---

## 🔒 Security model

One model, applied uniformly to every module and to the shell:

- **Standard library only.** Python 3.11+; zero third-party
  dependencies, including tests (`unittest` only). Nothing to audit but
  this repository. The console adds no dependency, network, or dynamic
  code-loading surface: its tool registry is a static list in source.
- **Fully offline.** No network calls of any kind, ever, in any module —
  there is no code path that opens a socket. h4ndl3 goes further and
  contains no HTTP code at all: it cannot scrape, so it cannot scrape
  improperly.
- **Read-only on evidence.** Evidence files are only ever opened for
  reading. The tools refuse to write manifests, logs, timelines, or
  reports anywhere inside an evidence/input directory, so tool output
  can never contaminate the evidence it documents.
- **Risk-tiered, with attestation.** Every console action carries a
  legal-risk tier. GREEN actions (pure offline documentation) run
  immediately. YELLOW actions — person-focused identifier research,
  associating a person across cases, attesting a case to third parties
  — challenge first and execute only after an explicit `ack <reason>`,
  which is recorded (timestamp, actor, action, reason) in the
  workspace's append-only `attest.csv`. RED is reserved for future use.
  See *Tiers and attestation* below.
- **Fail closed.** Malformed input, undeclared timezones, unanchored
  custody events, and unsafe output paths abort the run with a clear
  error rather than producing a partial or silently guessed artifact.
- **Small and auditable.** A handful of focused modules per tool,
  heavily commented, no metaprogramming, no `eval`/`exec`, no
  `shell=True`.

---

## 🛠 Install

Requirements: **Python 3.11+** and nothing else. There is no install
step, no virtualenv requirement, and no dependency to pin.

```bash
git clone https://github.com/v0idravl/chr0nix.git
cd chr0nix
python -m cust0dia --help
```

Run the full test suite to confirm everything works on your machine:

```bash
python -m unittest
```

---

## Usage

All commands run from the repository root. Each module package ships its
own full README in `docs/` with the complete command reference, worked
examples, and known limitations:

| Module | CLI | Console tool | Docs |
| --- | --- | --- | --- |
| cust0dia | `python -m cust0dia manifest \| verify \| custody` | `use cust0dia` | [docs/cust0dia.md](docs/cust0dia.md) |
| timeline | `python -m chr0nix.timeline build \| schema` | `use timeline` | `python -m chr0nix.timeline --help` |
| h4ndl3 | `python -m h4ndl3` | `use h4ndl3` | [docs/h4ndl3.md](docs/h4ndl3.md) |
| m3talex | `python -m m3talex` | `use m3talex` | [docs/m3talex.md](docs/m3talex.md) |
| casework | console-only | `use casework` | below |
| guide | console-only | `use guide` | below |

### The suite console

`python -m chr0nix console` opens an interactive TUI (stdlib `curses`,
Linux/macOS) modeled on operator consoles like metasploit: a shared
session holds your evidence directory, output directory, and actor name
so you set them once and then work. `use <tool>` selects a module from
the static registry (`show tools`), `set` / `unset` manage session
options, `show options` displays the session, and `run` executes the
selected tool against it. The console is a second front end over the
exact same core modules as the CLIs — every safety rule (append-only
custody, manifest anchoring, evidence-tree write protection,
control-character rejection) is inherited, not reimplemented. On
terminals without curses (e.g. Windows) the module CLIs remain fully
functional and the console exits with a pointer to them.

### Tiers and attestation

Every console action carries a legal-risk tier, and the tier decides
what "running it" means:

- **GREEN** — pure offline documentation. Runs immediately.
- **YELLOW** — lawful only under specific circumstances: identifier
  research tied to a person (h4ndl3 `worksheet` / `add`), associating a
  person across cases (casework `link ... subject`), attesting a case
  to third parties (casework `status ... submitted|referred`), and
  person-focused research guidance (guide `hint` / `capture` on the
  identifier-research methods).
- **RED** — reserved; defined but currently assigned to nothing.

A YELLOW action does not execute on first invocation. It answers with
a challenge — the tier, the rationale, and what confirmation looks
like — and only runs after an explicit, reasoned acknowledgment:

```text
chr0nix:h4ndl3 > worksheet j.doe_91
YELLOW — h4ndl3 worksheet: identifier research tied to a person;
lawful only for authorized casework. Confirm with: ack <reason>
chr0nix:h4ndl3 > ack employer-authorized LP investigation, case-2026-014
```

Every ack is appended to the workspace's append-only `attest.csv` —
`timestamp_utc,actor,action,reason` — so the judgment call itself is
part of the case record, with the same header-validation and
control-character rules as the custody log. `show attestations` prints
the log. Yellow actions require a workspace (nowhere to attest,
no action) and a session actor (attestations are signed).

### casework — case management

`use casework` manages whole investigations, compartmentalized per case
but linkable when they share an entity. A workspace (created with
`init`) holds the configurable vocabularies and the case files:

```text
<workspace>/
├── config/      categories.csv + taxonomy.csv — commented,
│                investigator-editable vocabularies (slash-delimited
│                tree paths, e.g. external-theft/method/concealment)
├── entities/    subjects.csv, vehicles.csv, links.csv — the shared
│                registry through which cases associate
├── attest.csv   the tier-attestation log
└── cases/<id>/  case.json · events.csv (append-only) · synopsis.txt
                 (generated, never hand-edited)
```

```text
chr0nix:casework > set workspace /cases/2026 && init
chr0nix:casework > new case-2026-014 LP office theft
chr0nix:casework > classify case-2026-014 external-theft/method/concealment
chr0nix:casework > link case-2026-014 subject subj-001 suspect
chr0nix:casework > links case-2026-014        # associated cases, with reasons
chr0nix:casework > status case-2026-014 pending
chr0nix:casework > synopsis case-2026-014     # regenerated, deterministic
```

Cases follow `draft → pending → submitted → referred → closed`
(forward-only; `submitted`/`referred` are YELLOW). Associations surface
two ways, always with the reason shown: shared subjects/vehicles (the
repeat-offender pattern) and direct case-to-case links. `synopsis`
regenerates a standard-field-order case summary from the record.

### guide — offline research guidance

`use guide` is an offline knowledge base of 13 research methods across
identifier-research, imagery, infrastructure, property, environmental,
and preservation — what you *could* do with tools like Sherlock,
Maigret, or phoneinfoga, encoded as documented procedure instead of
executed automation. The suite prints; the human browses.

```text
chr0nix:guide > methods                            # catalogue, tier-marked
chr0nix:guide > hint satellite-imagery 123 Main St # steps + browser handoffs
chr0nix:guide > hint username-search j.doe_91      # YELLOW — challenges first
chr0nix:guide > capture satellite-imagery coordinates=34.05,-118.24 imagery_date=2026-07-12 source=google-earth
```

`hint` prints ordered high-ROI steps and browser handoff URLs
(rendered with your query, never opened). `capture` records what came
back into the active case's append-only event log, validated against
the method's field vocabulary, and suggests the next corroboration
step. The design answers the four questions courts and compliance
teams ask of OSINT work: *where did it come from* (provenance fields
are mandatory), *when was it accessed* (UTC event timestamps), *was it
public* (passive public sources only; person-focused research is
YELLOW-attested), and *can the process be documented* (the process is
the artefact — attestations, event log, and guidance readable in
source).

---

## ✅ Testing

The unified suite uses stdlib `unittest` only and runs from the repo
root:

```bash
python -m unittest            # everything
python -m unittest discover -s tests/cust0dia    # one module's tests
```

Tests are organized one subdirectory per module under `tests/` and use
the same fictional fixtures as the examples. All fixtures under
`examples/` are fictional and safe to modify; no tool ever writes to
them.

---

## 📝 Notes

- The standalone `cust0dia`, `h4ndl3`, and `m3talex` repositories are
  **superseded by this monorepo**; their histories are preserved in
  their original repos, and their READMEs live on here under `docs/`.
- The chr0nix timeline tool previously lived at this repository's root;
  its CLI is now `python -m chr0nix.timeline`, and its original README —
  the full command reference — is preserved in this repository's git
  history.
- Outputs are designed to diff: commit manifests, custody logs, and
  timelines to a case repository, or keep them in write-once storage
  alongside your reports.
- `out/` and `examples/out/` are git-ignored so demo runs never dirty
  the tree.
- Image annotation is a manual, external step: annotate a *copy* with
  swappy, never the original, and manifest both. Recommended swappy
  defaults for legible, report-grade markup (thicker lines, larger
  monospace text, no auto-save) live in
  [docs/image-annotation.md](docs/image-annotation.md).
- chr0nix is for lawful, authorized investigative documentation work
  only.
