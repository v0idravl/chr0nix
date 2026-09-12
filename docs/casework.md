# chr0nix casework — case workspaces

casework is the case-management layer of the chr0nix suite. Where cust0dia
answers "is this file exactly what was collected?" and "who touched it?",
casework answers the case-level questions: which cases exist, what are they
about, how are they classified, which entities (subjects, vehicles, other
cases) connect them, and what happened — in what order.

It has two front ends over the same code:

- the **CLI** — `chr0nix case ...` (or `python -m chr0nix.casework`),
  scriptable, usable on any terminal;
- the **console** — `python -m chr0nix console`, then `use casework`.

Both call the same functions in `chr0nix/casework/`; every safety rule
(append-only logs, slug-safe identifiers, control-character rejection) is
inherited, not reimplemented.

> ⚠️ **Authorized use only.** casework is for lawful, authorized
> investigative documentation work only.

---

## The workspace

A *workspace* is one directory holding the configurable vocabularies and all
case files, laid out so that every fact about a case is a line or a file a
reviewer can read and diff:

```text
<workspace>/
├── config/
│   ├── categories.csv    # case categories: id,label,description
│   └── taxonomy.csv      # behavior taxonomy: path,label,description
├── entities/
│   ├── subjects.csv      # subject profiles (see the field list below)
│   ├── vehicles.csv      # vehicle ("transportation") profiles
│   └── links.csv         # append-only: case_id,entity_type,entity_id,role,notes
├── inbox/                # evidence drop zone (created on first use)
├── attest.csv            # the tier-attestation log (created on first ack)
└── cases/<case-id>/
    ├── case.json         # the case record
    ├── events.csv        # append-only event log
    ├── synopsis.txt      # GENERATED — never hand-edit
    ├── exhibits/         # filed evidence
    ├── manifest.csv/json # cust0dia manifest of exhibits/
    ├── custody.csv       # per-case custody log (COLLECTED on filing)
    ├── statements.csv    # append-only statement record
    └── statements/       # long-form statement bodies (<statement-id>.txt)
```

Create it with `chr0nix case init <dir>` (console: `init [dir]`, which also
points the session at the directory). `init` refuses to re-initialize an
existing workspace: config history is never disposable.

### config/: the vocabularies

`categories.csv` and `taxonomy.csv` are investigator-edited, commented CSVs:
lines whose first non-space character is `#` are comments, blank lines are
skipped, and the starter content doubles as a format demonstration. A case
can only reference ids and paths listed here — the vocabulary a case uses is
always one the config defines. Taxonomy paths are full slash-delimited paths
(`external-theft/method/concealment`); an intermediate node is assignable
only if listed verbatim.

### Identifiers are slug-safe

Case ids, entity ids, and statement ids must match lowercase letters,
digits, and hyphens (`case-2026-014`, `subj-001`). A case id becomes a
directory name and an entity id a join key across CSVs, so anything with
slashes, dots, or whitespace is rejected rather than sanitized — a typo
fails loudly instead of silently addressing a different case.

---

## Cases: case.json and the status chain

A case is one directory under `cases/`. Its `case.json` is the mutable
record:

```json
{
  "id": "case-2026-014",
  "title": "LP office theft",
  "status": "draft",
  "categories": [],
  "taxonomy_paths": [],
  "opened_utc": "2026-09-12T08:17:39Z",
  "closed_utc": null
}
```

It is written with a fixed key order and `indent=2` so consecutive versions
diff line-locally, and it is parsed defensively on read (every key, type,
and status value validated) because it is hand-editable in principle.

The status chain is **`draft → pending → submitted → referred → closed`**.
Transitions may skip forward (a case opened and submitted the same day need
not visit `pending`) but never move backward, and `closed` is terminal:
closing stamps `closed_utc` once and the case becomes a record of fact.
Every transition is logged to `events.csv` as a `status-changed` event, so
the JSON shows *where* a case is and the log shows *how it got there*.

`submitted` and `referred` attest the case's accuracy to third parties, so
they are YELLOW-tiered: the console challenges them (`ack <reason>`), and
the CLI requires `--ack "<reason>"`. Either way the reason lands in the
workspace's append-only `attest.csv`.

## events.csv: the append-only log

`cases/<id>/events.csv` (`timestamp_utc,actor,event_type,detail`) follows
the cust0dia custody discipline exactly: the header is validated before
every append, control characters in free-text fields are rejected (one event
is one line), and the only write ever performed is adding bytes at the end.
Case creation, status transitions, evidence filings, statements, and guide
captures all land here, and `chr0nix case event <id> <type> <detail...>`
appends free-form entries.

## Entities and links.csv

Three CSVs under `entities/` connect cases to the world and to each other:
`subjects.csv`, `vehicles.csv`, and the append-only `links.csv`, where
`entity_type` is `subject`, `vehicle`, or `case`.

### Profiles

The two registries are *profiles* — the current best picture of a person or
a vehicle — not logs, so editing one replaces the row (the evidentiary
record of an entity's involvement stays in append-only `links.csv` and the
case event logs).

Subject fields: `subject_id`, `nickname` (name/primary nickname), `aliases`,
`date_of_birth`, `physical_description`, `phones`, `emails`, `usernames`,
`addresses`, `employer`, `descriptor_summary`, `notes`.
Vehicle ("transportation profile") fields: `vehicle_id`, `plate`,
`description`, `jurisdiction`, `vin`, `make`, `model`, `year`, `color`,
`body_style`, `registered_owner`, `notes`.
Multi-value fields (`aliases`, `phones`, `emails`, `usernames`, `addresses`)
are `;`-separated inside their CSV column — one entity stays one line.

Workspaces created before the rich profiles (three-column registries) keep
working: reads accept the old header, and the first write upgrades the file
in place — header rewritten, existing rows preserved and padded.

In the **console**, profiles are filled in with a guided form (the "fill in
the boxes" flow — see [docs/console.md](console.md#guided-profile-forms)):

```text
chr0nix:casework > subject add            # walks every field; Enter skips
chr0nix:casework > subject edit subj-001  # same form, current values prefilled
chr0nix:casework > subject show subj-001  # the aligned profile card + linked cases
chr0nix:casework > subject set subj-001 phones "+1 555 0100, +1 555 0101"
```

(`vehicle add` / `vehicle edit` / `vehicle show` / `vehicle set` and the
`subjects` / `vehicles` listings work the same way.)

On the **CLI** the same fields are options on `entity add`, plus a `set`
subcommand taking `field=value` pairs and a `show` for the card:

```bash
chr0nix case entity add subject subj-001 --nickname "Red Hoodie" \
  --aliases "smithy, smitty" --phones "+1 555 0100" --employer "Depot Warehouse"
chr0nix case entity set vehicle veh-001 color=blue vin=1HGBH41JXMN109186
chr0nix case entity show subject subj-001
```

### Links

Linking is one step: naming an unknown subject or vehicle id auto-registers
it in the matching registry (with the role/notes as its initial descriptor),
so the registries grow as a by-product of real casework.
`chr0nix case entity add subject|vehicle ...` is the explicit form for
registering one ahead of any link; duplicate ids are rejected. Case links
are stricter — both cases must exist, and a case cannot link to itself.

Two association kinds are computed from `links.csv` (nothing is stored, so
the view can never disagree with the record):

- **shared entities** — two cases linked to the same `subj-001` or
  `veh-001` are associated ("shared subject subj-001"): repeat-offender and
  vehicle-reuse patterns emerge without anyone declaring them (a subject's
  vehicles are the same mechanism: link both to the case);
- **direct case→case links** — treated symmetrically, because the
  investigator asserted the *relationship*, not a direction.

Linking a **subject** asserts a person's involvement across cases and is
YELLOW-tiered (console `ack` / CLI `--ack`), with the attestation recorded.

## Evidence intake: the inbox

`<workspace>/inbox/` is a drop zone where anything lands — phone exports,
screenshots, PDFs. `chr0nix case file <case-id> [name...]` (no names = all)
*moves* items into `cases/<id>/exhibits/` with the full evidence discipline
applied at filing time:

1. the exhibits are re-manifested with cust0dia (both CSV and JSON) into
   the case directory — never inside `exhibits/` itself;
2. one `COLLECTED` custody row per item is appended to the case's
   `custody.csv`, anchored to the item's fresh SHA-256;
3. an `evidence-filed` event summarizes the batch in `events.csv`.

Filing moves rather than copies: an item is either unfiled or filed, never
both, so there is exactly one authoritative copy of every byte. The inbox
itself is never manifested — it is staging, and becomes evidence at the
moment of filing, which is also the moment hashing starts. Inbox names are
containment-checked: `..` and absolute paths are rejected.

## Statements

Interview statements live in `cases/<id>/statements.csv`
(`statement_id,timestamp_utc,interviewee,role,status,notes`), append-only:
recording creates a `recorded` row; signing appends a *new* `signed` row
under the same id with a new timestamp — the file is the full history, and
the latest row is the current state. Statement ids are unique per case.

Marking a statement signed is a legally significant claim, so
`statement sign` is YELLOW-tiered: console `ack`, CLI `--ack "<reason>"`,
recorded in `attest.csv`.

A statement's long-form **body** doesn't fit the one-record-one-line CSV
rule, so it lives beside the log as `cases/<id>/statements/<stmt-id>.txt`,
written once at record time. In the console,
`statement <id> <who> <role> :edit` composes the body in `$VISUAL`/`$EDITOR`
(fallback `nvim`, then `vi`) with curses suspended; the CLI takes
`--body TEXT` / `--body-file PATH`, and opens the same editor when neither
is given on an interactive terminal (scripted runs record without a body).
The comment-header lines the editor seeds are instructions and are never
stored. The same `:edit` convention works on `event` for a long detail
(`event <type> :edit`), flattened to one log line.

## Export: the sealed case bundle

`chr0nix case export <case-id> [--out DIR]` (console: `export [case-id]
[out-dir]`, active-case default) assembles everything about one case into
`<out>/<case-id>-export-<utc-stamp>/` — default out-root
`<workspace>/exports` — and self-seals it:

```text
<case-id>-export-<stamp>/
├── CASE-REPORT.md          # generated review brief (see below)
├── case.json · events.csv · statements.csv · custody.csv   # byte-exact copies
├── synopsis.txt            # freshly rendered, deterministic
├── statements/             # long-form statement bodies
├── exhibits-manifest.csv/json   # the case's cust0dia exhibits manifest
├── links.csv               # excerpt: every association naming this case
├── entities/               # subjects/vehicles CSVs, filtered to linked profiles
├── attest.csv              # the workspace attestation log, copied whole
├── <timeline/outputs, findings stores, m3talex reports under the case dir>
└── manifest.csv · manifest.json   # the bundle's OWN manifest, written last
```

The evidence bytes under `exhibits/` are deliberately **not** copied — the
export is a review deliverable, not a second authoritative copy; the
exhibits manifest and custody log travel with it, and CASE-REPORT.md says
how to verify the originals in the workspace. The bundle's own
`manifest.csv`/`manifest.json` describe every other file in the bundle and
cannot list themselves; `cust0dia verify` exempts exactly that pair, so a
bundle verifies clean from anywhere:

```bash
cd <bundle> && chr0nix verify manifest.json .   # verification PASSED
```

`CASE-REPORT.md` carries: the case header (title/id/status/actors), the
full event timeline, linked entity profile cards and case associations,
the statements table, the exhibits table, the custody log, the attestation
log, the bundle file listing, and verification instructions.

Export is read-only on the workspace and GREEN-tiered (the console actor,
when set, is recorded in the report header). Two refusals keep the suite's
output discipline: the target may not land inside the workspace's
evidentiary trees (`cases/`, `inbox/`), and an existing bundle directory is
never overwritten — re-running the export makes a new stamped bundle.

## Synopsis

`chr0nix case synopsis <case-id>` rebuilds `cases/<id>/synopsis.txt` — a
generated file ("GENERATED — do not hand-edit") in standard investigative
field order: header (id, title, status, opened/closed), categories and
taxonomy classifications with their config labels, linked cases with
association reasons, an event-timeline summary, and a one-paragraph
plain-language synopsis composed from all of the above. Generation is
deterministic (everything sorted or in append order), so two generations of
the same state are byte-identical, and a term whose config row was deleted
since degrades to a "(not in config/...)" note rather than failing.

---

## CLI reference: `chr0nix case ...`

The workspace comes from `--workspace PATH` or the `CHR0NIX_WORKSPACE`
environment variable; the actor — required by every log-appending command —
from `--actor NAME` or `CHR0NIX_ACTOR`. Both options may come before or
after the subcommand. There is no "active case": every case-acting command
takes the case id explicitly, so a scripted run never acts on an implicit
default.

| Command | Console equivalent | What it does |
| --- | --- | --- |
| `init [dir]` | `init [dir]` | create the workspace layout with starter config |
| `new <id> <title...>` | `new <id> <title...>` | create a case (status draft) |
| `list` | `cases` / `run` | case table + status-count summary |
| `show <id>` | `show case [id]` | one case's case.json fields and synopsis path |
| `status <id> <new-status>` | `status [id] <new-status>` | advance the status chain (`submitted`/`referred` need `--ack`) |
| `categorize <id> <category>` | `categorize [id] <category>` | attach a config-defined category (idempotent) |
| `classify <id> <path>` | `classify [id] <path>` | attach a config-defined taxonomy path (idempotent) |
| `entity add subject <id> [--nickname] [--descriptor] [--aliases] [--phones] ...` | `subject add [id]` (guided form) | register a subject profile |
| `entity add vehicle <id> [--plate] [--vin] [--make] ...` | `vehicle add [id]` (guided form) | register a transportation profile |
| `entity set subject\|vehicle <id> field=value ...` | `subject set` / `vehicle set` | update profile fields (empty value clears) |
| `entity show subject\|vehicle <id>` | `subject show` / `vehicle show` | the profile card + linked cases |
| `entity list subjects\|vehicles\|links` | `subjects` / `vehicles` (registries) | print a registry |
| `link <id> subject\|vehicle\|case <entity-id> [role...]` | `link [id] ...` | append an association (`subject` needs `--ack`) |
| `associations <id>` | `links [id]` | associated cases, with reasons |
| `event <id> <type> <detail...>` | `event [id] ...` (`:edit` composes a long detail) | append to the case's event log |
| `inbox` | `inbox` | list unfiled inbox items |
| `file <id> [name...]` | `file [id] [name...]` | file inbox items into exhibits (manifest + custody) |
| `statement record <id> <stmt-id> <who> <role> [notes...] [--body\|--body-file]` | `statement [id] ...` (`:edit` composes the body) | record a statement (status: recorded) |
| `statement sign <id> <stmt-id>` | `statement-sign [id] <stmt-id>` | mark signed (needs `--ack`) |
| `statement list <id>` | `statements [id]` | list statements with current status |
| `synopsis <id>` | `synopsis [id]` | regenerate and print synopsis.txt |
| `export <id> [--out DIR]` | `export [id] [out-dir]` | assemble the sealed case bundle (CASE-REPORT.md + self-manifest) |

Exit codes: `0` success; `2` operational error (uninitialized workspace,
unknown case or vocabulary term, invalid transition, missing actor, refused
append). Usage errors exit `2` via argparse.

### Example session (CLI)

```bash
chr0nix case init /cases/2026
export CHR0NIX_WORKSPACE=/cases/2026 CHR0NIX_ACTOR="A. Rivera"

chr0nix case new case-2026-014 LP office theft
chr0nix case classify case-2026-014 external-theft/method/concealment
cp phone-export.csv /cases/2026/inbox/
chr0nix case file case-2026-014                       # moved, manifested, custody-logged
chr0nix case link case-2026-014 subject subj-001 suspect --ack "employer-authorized LP case"
chr0nix case associations case-2026-014               # associated cases, with reasons
chr0nix case statement record case-2026-014 stmt-001 "J. Doe" witness "saw subject"
chr0nix case statement sign case-2026-014 stmt-001 --ack "signed in my presence"
chr0nix case status case-2026-014 pending
chr0nix case synopsis case-2026-014                   # regenerated, deterministic
```

### Example session (console)

```text
chr0nix > use casework
chr0nix:casework > init /cases/2026            # creates + sets + initializes
chr0nix:casework > set actor A. Rivera
chr0nix:casework > new case-2026-014 LP office theft
chr0nix:casework > classify external-theft/method/concealment
chr0nix:casework > inbox                       # 1 unfiled item(s)
chr0nix:casework > file                        # moved, manifested, custody-logged
chr0nix:casework > link subject subj-001 suspect   # YELLOW — then: ack <reason>
chr0nix:casework > links                       # associated cases, with reasons
chr0nix:casework > subject edit subj-001       # guided form, values prefilled
chr0nix:casework > subject show subj-001       # the profile card
chr0nix:casework > statement stmt-001 "J. Doe" witness :edit   # body in $EDITOR
chr0nix:casework > statement-sign stmt-001     # YELLOW — attested
chr0nix:casework > status pending
chr0nix:casework > synopsis                    # regenerated, deterministic
```

In the console, every case-acting command defaults to the *active case*
(set by `new` / `open`) — the case id is always accepted but rarely needed,
and the output always echoes the case acted on so the default is never
silent. See [docs/console.md](console.md) for the console itself.

---

## Notes

- casework is part of the `chr0nix` shell package (`chr0nix/casework/`),
  not a standalone module; its error type derives from the suite's
  `SuiteError`, so CLI and console render failures identically.
- The evidentiary CSVs are append-only by construction; `case.json` is the
  only mutable record, and it is rewritten in full under a fixed key order.
- Commit a workspace to version control, or keep it in write-once storage:
  every file in it is designed to diff.
