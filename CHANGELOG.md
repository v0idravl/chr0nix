# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Arrow-key navigation menu** (`chr0nix/console/menu.py`, curses-free
  and unit-tested like the command layer). The console now opens into a
  selectable menu: the suite's tools as a highlighted list with inline
  summaries and a live detail pane (the highlighted item's module card
  or command help). Arrows and vim keys both navigate (`↑↓`/`jk` move,
  `Enter`/`→`/`l` select, `←`/`h`/`q`/Esc back); selecting a tool loads
  it (`use <tool>`) and opens its command menu; selecting a command
  runs it when it needs no arguments, or prefills the input line with
  its name when it does. Typing any other character leaves the menu and
  starts a command line with it. **The menu is never a one-way door:**
  the `menu` command or ←/Esc on an empty input line returns to the
  menu where you left it, rebuilt fresh against the session (position
  preserved, module cards current), and a hint line saying so appears
  whenever a menu action closes the menu. Split escape sequences (a
  bare `ESC [ B` arriving across reads) are decoded into arrow keys, in
  both the normal-mode and application-mode dialects.

- **Console operator-UX layer** (`chr0nix/console/commands.py`,
  `tools.py`, `session.py`, `ui.py`). Help is now scoped: bare `help`
  shows an overview (core table + tool list) until a tool is loaded,
  then the active tool's commands; `help <tool>` peeks without
  switching, `help core` is just the core table, `help <command>` shows
  usage with tier, rationale, and worked examples (new `Command.details`
  field), and `help all` keeps the full dump. Loading a tool (`use`, or
  a bare tool name) prints a **module card** — summary, what `run` does
  (new `Tool.run_summary`), the session options the tool draws on (new
  `Tool.requires`/`optional`, with required-but-unset called out), and a
  command teaser; the new `info [tool]` command reprints the card in
  full. `show options` is now a Name/Current-Setting/Required/Description
  table (descriptions from new `OPTION_DESCRIPTIONS`) that marks what
  the active tool requires and names what is missing.
- **Bash-reflex tab completion**: an ambiguous tab extends the line to
  the common prefix and a second tab lists the candidates in the
  scrollback. Completion knows the grammar — `show` targets, the second
  word of two-word commands (`subject a<Tab>`), a tool's commands after
  its name (`casework in<Tab>`), `help` topics, and filesystem paths for
  the path-valued `set` options (directories keep their `/` so tab
  descends).
- **Did-you-mean errors**: unknown commands, help topics, `show`
  targets, and option names suggest the closest difflib matches.

### Changed

- **Console tool names now all follow the suite's naming pattern**:
  `timeline` → `t1m3l1n3`, `casework` → `c4s3w0rk`, `guide` → `gu1d3`,
  and the menu's core entry is `c0r3`. The former names keep working as
  aliases in dispatch, `help`, `info`, and tab completion, but every
  display (module cards, help, `show tools`, the status bar,
  attestation log action strings) shows the canonical name. The
  non-interactive CLIs (`chr0nix case`, `chr0nix guide`,
  `chr0nix timeline`) are unchanged.

- The console input prompt names the active guided form and field
  position while a form owns the line (`new subject profile [3/12] >`),
  and the status bar shows an armed YELLOW challenge
  (`pending: <action>`) so the action an `ack` would run is never a
  surprise. `set <option>` shows the option's description beneath its
  value.

## [1.0.0] - 2026-09-12

### Added

- **`chr0nix case export <id>`: the sealed case bundle**
  (`chr0nix/casework/export.py`, console `export [case-id] [out-dir]`,
  GREEN). Assembles `<out>/<case-id>-export-<utc-stamp>/` (default out-root
  `<workspace>/exports`): byte-exact copies of the case record (case.json,
  events.csv, statements.csv + bodies, custody.csv), a freshly rendered
  deterministic synopsis.txt, the case's exhibits manifest (renamed
  `exhibits-manifest.*` so it cannot collide with the bundle's own pair),
  a links.csv excerpt, entity registry extracts filtered to the profiles
  linked to the case, the workspace attest.csv copied whole, and any other
  tool outputs under the case directory (timeline builds, h4ndl3 stores and
  reports, m3talex reports) with their structure preserved. The evidence
  bytes under `exhibits/` are deliberately referenced, not copied. A
  generated `CASE-REPORT.md` tops the bundle: case header, event timeline,
  entity profile cards and associations, statements, exhibits, custody,
  attestations, bundle contents, and verification instructions. The bundle
  then self-seals: a cust0dia-format manifest (`manifest.csv` +
  `manifest.json`, tool stamp `cust0dia 1.0.0`) is written last over the
  finished payload, so the bundle verifies from anywhere with
  `chr0nix verify manifest.json .`. Export is read-only on the workspace
  and refuses targets inside the evidentiary trees (`cases/`, `inbox/`) or
  an existing bundle directory.
- **Self-sealing verification exemption** (`cust0dia.verify`): when the
  manifest under verification lives inside the tree it describes, it (and
  its `manifest.csv`/`manifest.json` sibling) is exempt from the EXTRA
  sweep — a configuration that could never previously pass. Trees whose
  manifest lives outside verify exactly as before, and any other
  unmanifested file still fails. Applied in the cust0dia CLI and the
  console's verify phase.
- **`chr0nix completion bash|zsh`** (`chr0nix/completions.py`): static,
  dependency-free shell completion scripts for the dispatcher's top-level
  commands and the second-level words of `case` / `guide` / `timeline` and
  the passthrough groups, also shipped verbatim under `completions/`
  (pinned against the generator by tests).
- **`docs/quickstart.md`**: "your first case in 15 minutes" — one
  end-to-end walkthrough over `examples/` data, from `case init` to a
  verified sealed export bundle, linked from the README.
- **Adversarial test suites** (`tests/timeline/test_adversarial.py`,
  `tests/m3talex/test_adversarial.py`, `tests/h4ndl3/test_adversarial.py`,
  fixtures generated in-test): BOM / CRLF / embedded-newline /
  semicolon-dialect / duplicate-header / huge-field / whitespace-only /
  mixed-case-header CSVs; truncated / EOI-less / PNG-in-disguise JPEGs;
  bad-CRC / trailing-garbage / IEND-less PNGs; zero-byte files; and
  malformed, unprovenanced, non-UTC, and self-corroborating findings rows.

### Fixed

- **timeline: duplicate CSV headers now fail loudly.** `csv.DictReader`
  silently lets the last duplicated column win, making a row's provenance
  ambiguous; `schema.validate_header` rejects repeated column names with a
  source-named error.
- **timeline: oversized fields no longer traceback.** The per-field size
  limit is raised to 16 MiB for the duration of a source load (real exports
  carry large free-text fields) and any remaining `csv.Error` is translated
  to a clean `Chr0nixError` instead of escaping as an uncaught exception.
- **m3talex: missing terminators are now observations.** A JPEG whose
  segment table ends without an EOI marker and a PNG with no IEND chunk
  previously parsed silently; both now record a "file may be truncated"
  parse warning in the report. Truncated segments/chunks, zero-byte files,
  and magic/extension mismatches were already handled errors and are now
  pinned by tests.

- **Rich entity profiles** (`chr0nix/casework/entities.py`). Subjects gain
  `aliases`, `date_of_birth`, `physical_description`, `phones`, `emails`,
  `usernames`, `addresses`, `employer`, and `notes`; vehicles gain
  `jurisdiction`, `vin`, `make`, `model`, `year`, `color`, `body_style`,
  `registered_owner`, and `notes`. Multi-value fields (aliases, phones,
  emails, usernames, addresses) are `;`-separated inside their CSV column.
  Registries are profiles, not logs: `entities.update_subject` /
  `update_vehicle` replace an entity's row in place, and
  `get_subject` / `get_vehicle`, `subject_values` / `vehicle_values`, and
  the aligned `render_subject_card` / `render_vehicle_card` profile cards
  back both front ends. Backward compatible: the Phase 3 three-column
  headers (`SUBJECT_FIELDS_V1` / `VEHICLE_FIELDS_V1`) still parse (rows are
  padded), and the first write to a legacy registry upgrades the file in
  place, preserving every existing row.
- **Guided profile forms in the console** (`chr0nix/console/forms.py`).
  `subject add` / `vehicle add` walk each profile field in order with a
  self-explanatory label, format hints, and `[current]` values when
  editing; Enter keeps/skips, `done` saves, `cancel` aborts, and
  multi-value fields take comma-separated input. `subject edit <id>` /
  `vehicle edit <id>` run the same form prefilled, `subject show` /
  `vehicle show` render the aligned card plus linked cases, `subject set` /
  `vehicle set <id> <field> [value...]` stay the one-shot path, and
  `subjects` / `vehicles` list the registries. The form is a curses-free
  state machine (`GuidedForm`) held on the session — while active, typed
  lines are form input — so the whole flow is unit-testable in-process.
- **$EDITOR handoff for long-form text** (`chr0nix/core/editor.py`).
  `edit_text` opens `$VISUAL`/`$EDITOR` (fallback `nvim`, then `vi`) on a
  temp file seeded with initial text and a commented instructions header;
  comment-header lines are stripped (never stored), and a non-zero exit,
  empty content, or unchanged-when-required content aborts cleanly. In the
  console the handoff (`EditorHandoff`, raised through dispatch like
  `ConsoleExit`) suspends curses (`def_prog_mode`/`endwin`,
  `reset_prog_mode`/refresh) and resumes the UI with a one-line
  confirmation. Wired into: the notes step of the profile forms (`:edit`),
  `statement <id> <who> <role> :edit` (long-form body), and
  `event <type> :edit` (long detail, flattened to one log line).
- **Statement bodies.** `statements.record_statement` takes an optional
  `body`, stored verbatim at `cases/<id>/statements/<statement-id>.txt`
  (the CSV row stays one line; the `statement-recorded` event points at the
  body file). CLI: `chr0nix case statement record` gains `--body` and
  `--body-file`; on an interactive terminal with neither, it opens the
  editor (scripted runs are never blocked).
- **CLI parity for profiles.** `chr0nix case entity add` accepts every new
  field as an option (multi-value fields comma-separated); new
  `entity set <type> <id> field=value ...` updates profiles
  non-interactively (empty value clears), and `entity show <type> <id>`
  prints the profile card plus linked cases.
- **Guide catalogue refresh** (`chr0nix/guide/methods.py`): 13 → 16
  methods. Steps and tool lists refreshed against current practice
  (archiving social profiles before they vanish, multi-engine reverse image
  search, facial-recognition caveats, urlscan/Shodan pointers). Methods
  gain `tool_references` — name + URL + one-line caveat — grounded in
  Bellingcat's Online Investigation Toolkit (printed, never opened). New
  methods: `breach-corpus` (YELLOW; lawful exposure checking, never leaked
  payloads), `transport-tracking` (GREEN; flight/vessel tracking via
  Flightradar24, FlightAware, MarineTraffic, VesselFinder, Equasis), and
  `vehicle-records` (YELLOW; VIN decode via NHTSA vPIC, NICB VINCheck,
  owner-data restrictions) under a new `transport` category. Existing
  method ids, handoffs, and capture vocabularies are unchanged.

- **`chr0nix case ...`: the casework layer as a scriptable CLI**
  (`chr0nix/casework/cli.py`, also `python -m chr0nix.casework`), covering
  everything the console's `use casework` does: `init`, `new`, `list`,
  `show`, `status`, `categorize`, `classify`, `entity add|list`, `link`,
  `associations`, `event`, `inbox`, `file`, `statement record|sign|list`,
  and `synopsis`. The workspace comes from `--workspace PATH` or
  `CHR0NIX_WORKSPACE`, the actor from `--actor NAME` or `CHR0NIX_ACTOR`,
  and there is no active case — every case-acting command takes the case
  id explicitly. The console's YELLOW-tier gate maps to `--ack "<reason>"`
  for `status submitted|referred`, `link ... subject`, and
  `statement sign`; the reason is recorded in the workspace attest.csv,
  exactly as a console `ack` records it. New explicit registry functions
  `entities.register_subject` / `register_vehicle` back `entity add`
  (previously only auto-registration on link existed).
- **`chr0nix guide ...`: the guide layer as a scriptable CLI**
  (`chr0nix/guide/cli.py`, also `python -m chr0nix.guide`): `list` (the
  catalogue), `show <method-id> [query...]` (steps + browser handoffs,
  rendered with the query), and `capture <method-id> field=value ...`
  which records an `osint-finding` into a case's append-only events.csv.
  Capture requires `--workspace`, `--case`, and `--actor`; YELLOW
  (person-focused) methods additionally require `--ack`.
- Both are wired into the `chr0nix` dispatcher as forwarded groups, and
  every console capability is now reachable non-interactively (dumb
  terminals, Windows without curses, scripts).
- **New docs:** `docs/timeline.md` (recovered from the original
  standalone-repo README in git history, updated for the monorepo),
  `docs/casework.md`, `docs/guide.md`, and `docs/console.md`; the README
  usage table now links all of them.
- `pyproject.toml` packaging metadata: a single `chr0nix` distribution
  (setuptools backend), `requires-python >= 3.11`, zero runtime
  dependencies, version read dynamically from `chr0nix.__version__`, an
  optional `windows` extra (`windows-curses`), and a `chr0nix` console
  script entry point.
- MIT `LICENSE` file (copyright 2026 v0idravl).
- GitHub Actions CI: Python 3.11/3.12/3.13 across Ubuntu, Windows, and
  macOS — full unittest suite plus a `pip install .` / `chr0nix --help`
  smoke test.
- Unified `chr0nix` command-line entry point installable from any
  directory (previously the tools only ran from the repo root).
- `chr0nix` is now a full dispatcher: top-level convenience subcommands
  forward to the module CLIs — `manifest`/`verify`/`custody` (cust0dia),
  `timeline build`/`timeline schema`, `worksheet`/`add`/`validate`/`report`
  (h4ndl3), `extract`/`batch` (m3talex) — plus passthrough groups
  `chr0nix cust0dia|h4ndl3|m3talex ...` equivalent to `python -m <pkg>`.
  Top-level `manifest` is cust0dia's; h4ndl3's manifest is reachable as
  `chr0nix h4ndl3 manifest`. Exit codes propagate unchanged, and
  `python -m cust0dia` / `python -m chr0nix.timeline` / `python -m h4ndl3`
  / `python -m m3talex` keep working as thin shims.

### Changed

- **`m3talex/samplegen.py` moved out of the shipped package to
  `tests/m3talex/samplegen.py`.** It is fixture-generation tooling used
  only by the test suite and `examples/m3talex/make_examples.py`; the
  installed distribution no longer contains it. Imports in the tests and
  the examples script were updated, and the examples script — which
  previously only ran from the repo root — now runs from any directory
  and still regenerates the example images byte-identically.
- **Console casework/guide logic consolidated into the core modules** so
  the new CLIs share it instead of duplicating it: the workspace case
  table and status summary moved into `chr0nix/casework/cases.py`
  (`render_case_table` / `render_status_summary`), and `capture`'s
  `field=value` validation moved into `chr0nix/guide/methods.py`
  (`parse_capture_pairs` / `capture_detail`). Console behavior is
  unchanged (pinned by its tests).
- **Consolidated the duplicated forensic core into a new `chr0nix/core`
  package.** `sha256_file` (was 3 copies), UTC ISO-8601 timestamp
  helpers (3 copies), the append-only CSV writer with header validation
  (3 copies), control-character field cleaning (4 copies), evidence-tree
  write refusal / path containment (4 copies), and the shared suite
  manifest format (4 copies) now live once in `chr0nix/core/`
  (`hashing`, `timeutil`, `csvx`, `fields`, `safety`, `manifest`).
  cust0dia, h4ndl3, m3talex, chr0nix.timeline, chr0nix.casework,
  chr0nix.tiers, and the console session layer all consume the shared
  implementation; the old per-package modules remain as re-export shims
  with unchanged names and signatures, so existing imports keep working.
- **h4ndl3's manifest now follows the suite-wide symlink policy.**
  Previously `h4ndl3 manifest` silently skipped symlinked files;
  symlinks are now hashed as the content they resolve to (matching
  cust0dia — what an examiner opening the file would see), and a broken
  symlink is a loud error instead of a silent omission.
- **The JSON manifest `tool` field is uniformly stamped
  `"<tool name> <version>"`.** cust0dia and chr0nix.timeline already
  did this; h4ndl3 (`"h4ndl3"` → `"h4ndl3 1.0.0"`) and m3talex
  (`"m3talex"` → `"m3talex 1.0.0"`) now match.
- m3talex's CSV manifests now use LF line endings (previously the
  `csv` module's CRLF default), matching the rest of the suite.
- JSON manifests now render non-ASCII characters literally
  (`ensure_ascii=False`) across all producers so evidence paths stay
  human-readable; cust0dia and chr0nix.timeline previously emitted
  `\uXXXX` escapes.
- Manifest relative paths are POSIX-style on every platform from every
  producer (h4ndl3 previously used OS-native separators).

### Fixed

- Stale package docstring in `chr0nix/__init__.py` that described h4ndl3
  as "file-handle and artifact inspection"; h4ndl3 is the offline-first
  identifier research worksheet and findings tool.
