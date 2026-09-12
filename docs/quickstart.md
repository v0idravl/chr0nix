# Quickstart: your first case in 15 minutes

This walkthrough builds one complete, sealed case bundle from nothing but the
fictional demo data shipped under `examples/`. Every command is real and
runnable; outputs below are trimmed where a listing is long. All timestamps
are illustrative — yours will differ.

You can drive the exact same workflow from the interactive console
(`chr0nix console`, then `use casework`); this page uses the scriptable CLI
so it works on any terminal and can be pasted into a shell verbatim. Where a
console command is nicer (guided forms, `:edit`), it is mentioned inline.

**Setup.** Run from the repository root (or anywhere, once `pip install .`
has put `chr0nix` on your PATH — substitute `chr0nix` for
`python -m chr0nix` throughout):

```bash
cd chr0nix                      # the repository root
DEMO=$(mktemp -d)               # a scratch area for the walkthrough
```

## 1. Initialize the workspace

A *workspace* holds the editable vocabularies and every case file:

```bash
$ python -m chr0nix case init "$DEMO/ws"
initialized casework workspace at /tmp/…/ws
wrote /tmp/…/ws/config/categories.csv
wrote /tmp/…/ws/config/taxonomy.csv
wrote /tmp/…/ws/entities/subjects.csv
wrote /tmp/…/ws/entities/vehicles.csv
wrote /tmp/…/ws/entities/links.csv
next: chr0nix case new <case-id> <title...>
```

Point the CLI at the workspace once, and name yourself — every log-appending
command records the actor:

```bash
export CHR0NIX_WORKSPACE="$DEMO/ws" CHR0NIX_ACTOR="A. Rivera"
```

## 2. Open a case

```bash
$ python -m chr0nix case new case-2026-014 "Stockroom concealed-merchandise theft"
created case case-2026-014 (draft)
```

Case ids are slug-safe (lowercase letters, digits, hyphens) because they
become directory names. Classify it against the starter vocabularies (both
are idempotent; add your own rows to `config/` anytime):

```bash
$ python -m chr0nix case categorize case-2026-014 external-theft
case-2026-014: categorized as external-theft
$ python -m chr0nix case classify case-2026-014 external-theft/method/concealment
case-2026-014: classified under external-theft/method/concealment
```

## 3. Build the exhibit timeline

Merge the four demo source exports (CCTV bookmarks, alarm panel, POS
back-office, officer notes) into one UTC-ordered timeline, written *into the
case directory* so the export picks it up later. The sources stamp naive
store-local times, so each gets its declared timezone — chr0nix never
guesses one:

```bash
$ python -m chr0nix timeline build \
    --source cctv=examples/timeline/sources/cctv_bookmarks.csv \
    --source ap=examples/timeline/sources/ap_incidents.csv \
    --source pos=examples/timeline/sources/pos_backoffice.csv \
    --source ofc=examples/timeline/sources/officer_notes.csv \
    --tz cctv=America/Los_Angeles --tz ap=America/Los_Angeles \
    --tz pos=America/Los_Angeles --tz ofc=America/Los_Angeles \
    --title "case-2026-014 exhibit timeline" \
    --out "$CHR0NIX_WORKSPACE/cases/case-2026-014/timeline"
chr0nix: warning: cctv row 2 (CCTV-01): AMBIGUOUS_LOCAL_TIME
chr0nix: warning: ofc row 3 (OFC-02): OFFSET_TZ_MISMATCH
chr0nix: normalized 13 events from 4 source(s); 2 flagged, 0 sharing an exact UTC instant
  wrote …/cases/case-2026-014/timeline/timeline.csv
  wrote …/cases/case-2026-014/timeline/timeline.md
  wrote …/cases/case-2026-014/timeline/manifest.csv
  wrote …/cases/case-2026-014/timeline/manifest.json
```

Two rows are flagged, not silently resolved: 2025-11-02 is the DST fall-back
date, so one DVR bookmark lands in the ambiguous fold and one bodycam row
carries an offset that disagrees with the declared zone. Both stay in the
timeline with citations; `timeline.md` explains each flag. (With `--strict`
the build would exit 3 here — success a reviewer must look at.)

## 4. File evidence through the inbox

`<workspace>/inbox/` is the drop zone for loose exports. `chr0nix case
inbox` lists it (and creates it on first use); `file` *moves* items into the
case's `exhibits/`, re-manifests them with cust0dia, and appends one
hash-anchored `COLLECTED` custody row per item:

```bash
$ python -m chr0nix case inbox
inbox is empty (drop files into /tmp/…/ws/inbox)
$ cp examples/cust0dia/case-2026-014/exhibit-00*.txt \
     examples/cust0dia/case-2026-014/exhibit-003_register-log-export.csv \
     "$CHR0NIX_WORKSPACE/inbox/"
$ python -m chr0nix case file case-2026-014
filed 3 item(s) into case-2026-014's exhibits:
  exhibit-001_interview-notes.txt
  exhibit-002_incident-report.txt
  exhibit-003_register-log-export.csv
manifest + custody log updated (COLLECTED, hash-anchored)
next: synopsis case-2026-014
```

## 5. Image metadata sweep

Batch-analyze the demo images (one phone photo, one edited export, one
stripped file, two PNGs) into the case directory. Every image is hashed into
the manifest even when unparseable, and one corrupt file warns rather than
sinking the batch:

```bash
$ python -m chr0nix batch examples/m3talex/images \
    -o "$CHR0NIX_WORKSPACE/cases/case-2026-014/m3talex"
analyzed 5 image(s), 5 finding(s)
batch report: …/cases/case-2026-014/m3talex/m3talex-report.md
manifests:    …/cases/case-2026-014/m3talex/manifest.csv, …/m3talex/manifest.json
JSON reports: …/cases/case-2026-014/m3talex
```

## 6. Identifier research (h4ndl3)

Generate a research worksheet for the handle found in the case, keep the
findings store in the case directory, seed it from the demo store, and
render the corroboration-gated report:

```bash
$ CASE="$CHR0NIX_WORKSPACE/cases/case-2026-014"
$ python -m chr0nix worksheet j.doe_91 --store "$CASE/findings.jsonl" \
    --out "$CASE/worksheet-username-j.doe_91.md"
$ cp examples/h4ndl3/findings.jsonl "$CASE/findings.jsonl"
$ python -m chr0nix validate --store "$CASE/findings.jsonl"
/tmp/…/cases/case-2026-014/findings.jsonl: 3 finding(s), all valid
$ python -m chr0nix report --store "$CASE/findings.jsonl" \
    --out "$CASE/findings-report.md" --title "case-2026-014 identifier research"
```

The store is strict: every finding needs a claim, an http(s) source URL, an
explicitly-UTC retrieval timestamp, a confidence level, and corroborating
sources that may not include the source itself. `validate` re-checks the
whole store after any hand edit.

## 7. Register the subject and the vehicle

Entity profiles are the case's picture of a person or vehicle. The CLI takes
every field as an option (multi-value fields comma-separated); the console
equivalent — `subject add` / `vehicle add` — walks the same fields as a
guided form, Enter skipping any you don't have yet:

```bash
$ python -m chr0nix case entity add subject subj-001 --nickname "j.doe_91" \
    --aliases "smithy, smitty" --phones "+1 555 0100" \
    --usernames "ig:j.doe_91" --descriptor "tall, red hoodie"
registered subject subj-001 (j.doe_91)
subject profile — subj-001
==========================
  Name / primary nickname  j.doe_91
  Aliases & nicknames      smithy, smitty
  …
$ python -m chr0nix case entity add vehicle veh-001 --plate "ABC 123" \
    --jurisdiction CA --make Honda --model Civic --year 2019 \
    --color blue --body-style sedan
registered vehicle veh-001 (ABC 123)
```

Link both to the case. Linking a *subject* asserts a person's involvement,
so it is YELLOW-tiered: the CLI refuses without `--ack "<reason>"`, and the
reason lands in the workspace's append-only `attest.csv`:

```bash
$ python -m chr0nix case link case-2026-014 subject subj-001 suspect \
    --ack "employer-authorized LP investigation"
linked case-2026-014 -> subject subj-001
$ python -m chr0nix case link case-2026-014 vehicle veh-001 "getaway car"
linked case-2026-014 -> vehicle veh-001
```

## 8. Record a statement

```bash
$ python -m chr0nix case statement record case-2026-014 stmt-001 \
    "R. Sosa" witness "saw subject at the east exit" \
    --body "At approximately 02:40 I saw a tall person in a red hoodie exit \
through the east door carrying a store tote bag."
recorded statement stmt-001 on case-2026-014 (R. Sosa, witness) — status: recorded
body: …/cases/case-2026-014/statements/stmt-001.txt
```

The CSV row stays one line; the long-form body lives beside it as
`statements/stmt-001.txt`. For anything longer, hand off to your editor: the
CLI opens `$VISUAL`/`$EDITOR` (fallback `nvim`, then `vi`) when neither
`--body` nor `--body-file` is given on an interactive terminal, and in the
console `statement stmt-001 "R. Sosa" witness :edit` does the same with
curses suspended.

Marking the statement signed is a legally significant claim, so it is
YELLOW-tiered too:

```bash
$ python -m chr0nix case statement sign case-2026-014 stmt-001 \
    --ack "statement signed in my presence 2026-09-12"
statement stmt-001 on case-2026-014 marked signed
```

## 9. Move the case forward

The status chain is `draft → pending → submitted → referred → closed`,
forward-only, `closed` terminal. `submitted`/`referred` attest the case to
third parties, so they take `--ack`:

```bash
$ python -m chr0nix case status case-2026-014 pending
case-2026-014: status -> pending
$ python -m chr0nix case status case-2026-014 submitted --ack "submitted to LP regional manager"
case-2026-014: status -> submitted
```

## 10. Capture research guidance into the record

The offline guide (`chr0nix guide list`, 16 methods) prints steps and
browser handoff URLs — never opens them — and `capture` records findings
into the case's append-only event log as an `osint-finding`:

```bash
$ python -m chr0nix guide capture satellite-imagery \
    coordinates=34.0522,-118.2437 imagery_date=2025-11-02 source=google-earth \
    --workspace "$CHR0NIX_WORKSPACE" --case case-2026-014
recorded osint-finding on case-2026-014 (satellite-imagery)
related methods: maps-geolocation, web-archive
```

## 11. Synopsis, export, verify

Regenerate the deterministic case brief, then assemble the sealed bundle:

```bash
$ python -m chr0nix case synopsis case-2026-014
wrote …/cases/case-2026-014/synopsis.txt
# GENERATED — do not hand-edit
…
$ python -m chr0nix case export case-2026-014
exported case case-2026-014 -> /tmp/…/ws/exports/case-2026-014-export-20260912T100927Z
sealed: manifest.csv + manifest.json written at the bundle root
verify with: chr0nix verify /tmp/…/manifest.json /tmp/…/case-2026-014-export-20260912T100927Z
```

The bundle gathers the case record, event log, statements (with bodies),
the timeline and m3talex outputs, the h4ndl3 store and report, the linked
entity profiles, the links excerpt, the custody log, and the workspace
attestation log — plus a generated `CASE-REPORT.md` brief on top. The
evidence bytes under `exhibits/` are referenced by their manifest, not
copied. The bundle then seals itself: its own `manifest.csv`/`manifest.json`
(written last, stamped `cust0dia 1.0.0`) hash every other file in it.

Verify the seal — this works from anywhere, and survives copying the bundle
to other media:

```bash
$ BUNDLE=$(echo "$DEMO/ws/exports/case-2026-014-export-"*)
$ python -m chr0nix verify "$BUNDLE/manifest.json" "$BUNDLE"
OK      CASE-REPORT.md
OK      attest.csv
…
verification PASSED: 28 OK, 0 CHANGED, 0 MISSING, 0 EXTRA
```

(With an installed `chr0nix`, `cd "$BUNDLE" && chr0nix verify manifest.json .`
is the equivalent short form — the bundle manifest records relative paths, so
verification never depends on where the bundle sits.)

Any later edit to any bundled file flips that to `CHANGED` and exit code 1.
The original evidence bytes verify against the case's own manifest:

```bash
python -m chr0nix verify "$CHR0NIX_WORKSPACE/cases/case-2026-014/manifest.json" \
    "$CHR0NIX_WORKSPACE/cases/case-2026-014/exhibits"
```

## Where to next

- The same session interactively: `chr0nix console`, `use casework`, then
  `init`, `new`, `file`, `link`, `subject add` (guided form), `statement
  … :edit`, `export`. The console tiers person-affecting actions YELLOW and
  challenges them (`ack <reason>`) instead of taking `--ack`.
- Per-module references: [casework](casework.md), [timeline](timeline.md),
  [h4ndl3](h4ndl3.md), [m3talex](m3talex.md), [cust0dia](cust0dia.md),
  [guide](guide.md), [console](console.md).
