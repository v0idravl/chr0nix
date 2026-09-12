# chr0nix roadmap — from toolkit to finished product

Goal: an investigator installs once, types `chr0nix`, and gets a cohesive
suite that *operates* like p0rtix / Metasploit / Sliver — one front door, a
module registry, session state, predictable grammar — while keeping the
suite's differentiators: stdlib-only, offline, read-only on evidence, and
court-defensible output.

Non-goals (deliberate):

- No third-party runtime dependencies, no network code, no writes to
  evidence trees. That security model is the product.
- No GUI. Console + scriptable CLI covers the investigator audience.
- RED tier stays reserved until a genuinely destructive action exists.

## Current state (as of 2026-09)

- Four stdlib-only tools with independent CLIs (`cust0dia`,
  `chr0nix timeline`, `h4ndl3`, `m3talex`) plus a curses console with a
  tool registry, `use`/`set`/`run`, session context, tier/attestation
  system, casework, and guide layers. 793 unittest tests pass.
- No packaging metadata, no LICENSE, no CI, no CHANGELOG. Tools only run
  from the repo root.
- The forensic core (suite manifest, `sha256_file`, `utc_now_iso`,
  append-only CSV, field cleaning, write refusal) is implemented once
  in `chr0nix/core/`; the per-tool modules are re-export shims. One
  symlink policy everywhere: resolved content is hashed, broken links
  fail loudly.
- Casework and guide now have real CLIs (`chr0nix case`, `chr0nix guide`)
  alongside the console, so every console capability is reachable where
  curses cannot run (dumb terminal, Windows without windows-curses,
  screen readers).
- `chr0nix case export` seals a case's outputs into one self-manifested
  bundle with a generated CASE-REPORT.md; timeline, casework, guide, and
  console docs live in `docs/`, plus `docs/quickstart.md` and bash/zsh
  completions under `completions/`.
- All test data synthetic; nothing validated against messy real exports.

## Phase 0 — Foundations

- [x] LICENSE (MIT), CHANGELOG.md, fix stale docstring in
      `chr0nix/__init__.py`.
- [x] `pyproject.toml`: single distribution, `requires-python >= 3.11`,
      zero runtime deps, optional `windows-curses` on win32, version from
      `chr0nix.__version__`, `console_scripts: chr0nix = chr0nix.cli:main`.
- [x] CI (GitHub Actions): {3.11, 3.12, 3.13} x {ubuntu, windows, macos},
      `python -m unittest`, `pip install .` smoke test.

Exit: `pipx install .` on a clean machine; `chr0nix --help` works from any
directory on all three OSes in CI.

## Phase 1 — Unified CLI dispatcher

- [x] `chr0nix/cli.py` becomes a real dispatcher: `console`,
      `manifest|verify|custody` (cust0dia), `timeline build|schema`,
      `worksheet|add|validate|report` (h4ndl3), `extract|batch` (m3talex),
      plus `chr0nix <tool> ...` passthrough groups for everything.
- [x] Module CLIs (`python -m cust0dia` etc.) stay working as thin shims.

Exit: every README workflow reproducible through `chr0nix ...` alone.

## Phase 2 — De-duplicate the forensic core

- [x] New `chr0nix/core/`: hashing, timeutil, append-only CSV, suite
      manifest writer, field cleaning, evidence-tree write refusal.
- [x] Migrate cust0dia, h4ndl3, m3talex, timeline, casework, tiers onto it.
      Resolve the symlink-policy divergence to cust0dia's behaviour
      (hash resolved content); record the change in CHANGELOG.
- [x] Old module APIs remain as re-exports so imports don't break.

Exit: one `sha256_file`, one manifest writer; all tests green.

## Phase 3 — Console-only features get real CLIs

- [x] `chr0nix case ...` and `chr0nix guide ...` subcommands calling the
      same casework/guide functions the console uses.
- [x] Move `m3talex/samplegen.py` out of the shipped package into
      test/example tooling.
- [x] Docs: `docs/timeline.md` (recover from git history), `docs/casework.md`,
      `docs/guide.md`, `docs/console.md`.

Exit: every console capability reachable non-interactively and scriptable;
works on a dumb terminal and on Windows.

## Phase 4 — Investigator experience

- [x] Interactive profiles, sliver-module style: load a workspace, select a
      module, add/view/change subject and transportation (vehicle) profiles.
      Short fields (names, aliases, DOB, plates, VIN, phones, emails) are
      filled in-app through a guided field-by-field prompt with clean,
      self-explanatory labels — Enter keeps the current value.
- [x] Long-form text (statement bodies, case notes) hands off to the
      terminal editor (`$EDITOR`, nvim here) via a temp file with curses
      suspend/resume; same helper used by the non-interactive CLI.
- [x] Guide catalogue refreshed against modern real-world OSINT /
      investigative TTPs (still offline: URLs printed, never opened).
- [x] `chr0nix case export <id>`: assemble synopsis, timeline, findings,
      image reports, manifests, custody log, and attestations into one
      bundle with a top-level `CASE-REPORT.md` and a cust0dia manifest of
      the bundle itself (self-sealing output).
- [x] `docs/quickstart.md` — first case in 15 minutes using `examples/`.
- [x] Shell completions (bash/zsh).
- [x] Extended validation: adversarial CSV dialects and malformed/partial
      JPEG/PNG structures beyond the current synthetic fixtures.

Exit: a new user following only `docs/quickstart.md` produces a sealed
case bundle without reading source.

## Phase 5 — Release

- [x] Build sdist + wheel, verify install from wheel in a clean venv
      (`dist/chr0nix-1.0.0-py3-none-any.whl`, `dist/chr0nix-1.0.0.tar.gz`;
      installed into a fresh venv and exercised end-to-end: workspace init →
      case → profiles → timeline → intake → export → seal verifies).
- [x] CHANGELOG 1.0.0 section; full test suite green (793 tests).
- [ ] Tag 1.0.0, GitHub release with artifacts, optional PyPI publish
      (requires maintainer action/credentials — see below).
