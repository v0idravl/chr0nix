```text
 ██████╗██╗  ██╗██████╗  ██████╗ ███╗   ██╗██╗██╗  ██╗
██╔════╝██║  ██║██╔══██╗██╔═████╗████╗  ██║██║╚██╗██╔╝
██║     ███████║██████╔╝██║██╔██║██╔██╗ ██║██║ ╚███╔╝
██║     ██╔══██║██╔══██╗████╔╝██║██║╚██╗██║██║ ██╔██╗
╚██████╗██║  ██║██║  ██║╚██████╔╝██║ ╚████║██║██╔╝ ██╗
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝╚═╝  ╚═╝

  the investigative-documentation suite · one repo · one security model
```

**chr0nix is the consolidated investigative-documentation suite** — four
small, stdlib-only Python tools for documenting digital evidence, now
developed together in a single monorepo under a single security model.
This repository supersedes the standalone `cust0dia`, `h4ndl3`, and
`m3talex` repositories: all four modules live here, share their
conventions, and are tested together from the repo root.

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

On top of the four modules sits the **suite shell**: an interactive
curses console (`python -m chr0nix console`, Linux/macOS) with a
metasploit-style `use` / `set` / `run` interface and a static, in-code
tool registry — one operator session over the exact same core modules
the CLIs use.

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
  tools into **one repo and one security model**: shared conventions
  (UTC everywhere, deterministic diff-friendly output, evidence/output
  separation), shared manifest format, one test suite, one audit
  surface.
- Make evidence integrity a default habit rather than a manual chore —
  manifests and custody logs (cust0dia), corroborated timelines
  (chr0nix/timeline), corroboration-gated research (h4ndl3), documented
  image assessment (m3talex).
- Provide a single interactive front end (the suite console) that adds
  no new trust surface: no dependencies, no network paths, no dynamic
  code loading.
- Stay small enough that any reviewer can read the entire codebase
  end-to-end in one sitting.

### Repository layout

```text
chr0nix/            suite package: shell, console, and the timeline module
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
