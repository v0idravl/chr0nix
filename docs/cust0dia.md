```text
 ██████╗██╗   ██╗███████╗████████╗ ██████╗ ██████╗ ██╗ █████╗ 
██╔════╝██║   ██║██╔════╝╚══██╔══╝██╔═████╗██╔══██╗██║██╔══██╗
██║     ██║   ██║███████╗   ██║   ██║██╔██║██║  ██║██║███████║
██║     ██║   ██║╚════██║   ██║   ████╔╝██║██║  ██║██║██╔══██║
╚██████╗╚██████╔╝███████║   ██║   ╚██████╔╝██████╔╝██║██║  ██║
 ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═╝
        sha-256 exhibit manifests & chain of custody · stdlib-only python
```

**cust0dia produces recursive SHA-256 manifests of evidence directories
and maintains an append-only chain-of-custody log.** — Point it at a
folder of case exhibits and it writes a court-presentable record — CSV
and JSON — of exactly what was collected: every file's relative path,
size, SHA-256 digest, modification time, and the UTC moment it was
hashed. Later, `verify` re-hashes the directory against that record and
reports, file by file, what is intact, what changed, what is missing,
and what appeared that was never collected.

The tool exists because chain-of-custody and integrity hashing are the
difference between evidence and a file on a laptop. Hashing at
collection time is what lets an investigator say "this file is exactly
what I collected, and here is the proof" — and mean it. Everything an
investigator stores should be hashed at collection, logged on every
touch, and verified before it goes anywhere near a report. cust0dia is
that habit, automated.

It is the foundational tool of a small suite of investigative
documentation utilities: its manifest format is deliberately simple,
fully specified, and consumed by the other tools in the suite.

> ⚠️ **Authorized use only.** cust0dia is for lawful, authorized
> investigative documentation work only. It is a defensive documentation
> tool — it records and verifies evidence you are entitled to handle; it
> does not collect anything you are not.

---

## ⚡ Quick start

The repository ships a fictional case folder under `examples/`. From the
repo root, hash it at "collection time":

```bash
python -m cust0dia manifest examples/cust0dia/case-2026-014 --output-dir out/demo
cat out/demo/manifest.csv
```

Prove the folder is still byte-for-byte what was collected:

```bash
python -m cust0dia verify out/demo/manifest.json examples/cust0dia/case-2026-014
```

Log a custody event, anchored to the exhibit's hash from the manifest:

```bash
python -m cust0dia custody out/demo/manifest.json out/demo/custody-log.csv \
    --exhibit exhibit-001_interview-notes.txt \
    --actor "John Doe" --action COLLECTED \
    --notes "Collected from LP office, sealed in evidence bag 14."
```

Or do the whole workflow interactively in the suite console:

```bash
python -m chr0nix console
```

```text
chr0nix > use cust0dia
chr0nix:cust0dia > set evidence examples/cust0dia/case-2026-014
chr0nix:cust0dia > set output out/demo
chr0nix:cust0dia > set actor John Doe
chr0nix:cust0dia > run                          # builds manifest.csv + manifest.json
chr0nix:cust0dia > show exhibits
chr0nix:cust0dia > log exhibit-001_interview-notes.txt COLLECTED sealed in bag 14
chr0nix:cust0dia > run                          # now verifies against the manifest
```

`out/` is disposable demo output and is git-ignored; delete it whenever
you like.

---

## 🖥 The console

cust0dia ships with no interface of its own beyond the CLI above — in
the chr0nix suite it is one of four tools registered in the suite
console (`python -m chr0nix console`, then `use cust0dia`). The console
is an interactive TUI (stdlib `curses`, Linux/macOS) modeled on
operator consoles like metasploit: a shared session holds your evidence
directory, output directory, and actor name so you set them once and
then work. The status bar always shows what the next command will
touch.

- `use <tool>` selects a tool from the suite registry (`show tools`);
  cust0dia is the first of them.
- `run` is two-phase: before a manifest exists it *collects* (builds
  the manifest); once one exists it *verifies* against it. To
  re-collect a legitimately changed tree, `unset manifest` and `run`.
- `log <exhibit> <ACTION> [notes...]` appends a custody event using the
  session's actor.
- `set` / `unset` manage `evidence`, `output`, `manifest`, `log`,
  `actor`; `show options` displays the session.
- Line editing with in-memory history (never written to disk) and tab
  completion; PgUp/PgDn pages the scrollback.

The console is a second front end over the exact same core modules as
the CLI — every safety rule (append-only custody, manifest anchoring,
evidence-tree write protection, control-character rejection) is
inherited, not reimplemented. It adds no dependencies, no network
paths, and no dynamic code loading: the tool registry is a static,
in-code list. On terminals without curses (e.g. Windows) the CLI
remains fully functional and the console exits with a pointer to it.

---

## 🧠 What it does

- Produce deterministic, sorted SHA-256 manifests of exhibit directories at
  collection time, in both CSV and JSON.
- Re-verify a directory against a saved manifest and report per-file status:
  `OK`, `CHANGED`, `MISSING`, `EXTRA`.
- Maintain an append-only chain-of-custody log where every event is anchored to
  an exhibit hash that provably exists in a manifest.
- Make evidence integrity a default habit rather than a manual chore — hash at
  collection, log every touch, verify before reporting.
- Stay small enough that any reviewer can read the entire codebase end-to-end
  in one sitting.

### What this demonstrates

cust0dia evidences the working habits of a disciplined investigator-engineer:
forensically sound handling of digital exhibits, defense-in-depth input
validation, deterministic and diff-friendly output formats, and a security model
written down instead of implied. It is deliberately small, stdlib-only, and
auditable end-to-end — the kind of tool you can hand to a reviewer, an attorney,
or a court and explain line by line.

---

## 🔒 Security model

- **Standard library only.** Zero third-party dependencies — just `hashlib`,
  `pathlib`, `csv`, `json`, `argparse`, `curses`, `datetime`. Nothing to audit
  but this repository. The console adds no dependency, network, or dynamic
  code-loading surface: its tool registry is a static list in source.
- **Fully offline.** No network calls of any kind, ever. There is no code path
  that opens a socket.
- **Read-only on inputs.** Evidence files are only ever opened for reading. The
  tool refuses to write manifests or custody logs anywhere inside the evidence
  directory, so tool output can never contaminate the evidence it documents.
- **Small and auditable.** A handful of focused modules, heavily commented,
  stdlib `unittest` coverage, no metaprogramming, no `eval`/`exec`, no
  `shell=True`.

---

## 🛠 Install

Requirements: **Python 3.11+** and nothing else. There is no install step, no
virtualenv requirement, and no dependency to pin.

```bash
git clone https://github.com/v0idravl/chr0nix.git
cd chr0nix
python -m cust0dia --help
```

Run the test suite to confirm everything works on your machine:

```bash
python -m unittest
```

---

## Usage

All commands run from the repository root as `python -m cust0dia ...`.
Exit codes: `0` success, `1` verification failed, `2` operational error
(bad path, malformed manifest, unsafe output location).

### `manifest` — hash an exhibit directory

```bash
python -m cust0dia manifest /cases/2026-014/exhibits --output-dir /cases/2026-014/documentation
```

Walks the exhibit directory recursively, hashes every file with SHA-256, and
writes `manifest.csv` and `manifest.json` to the output directory. The output
directory must not be inside the evidence directory — cust0dia refuses outright
if it is. Re-running against an unchanged tree reproduces identical rows (only
the `hashed_at_utc` timestamps move), so manifests diff cleanly.

### `verify` — re-hash against a manifest

```bash
python -m cust0dia verify /cases/2026-014/documentation/manifest.json /cases/2026-014/exhibits
```

Accepts either the CSV or the JSON manifest. Prints one line per file —
`OK`, `CHANGED`, `MISSING`, or `EXTRA` — plus a summary, and exits `1` if
anything is not `OK`. For example, after someone edits an exhibit:

```text
OK      exhibit-001_interview-notes.txt
CHANGED exhibit-002_incident-report.txt  (manifest e1c4eb7377cf… actual 6f8ab719fd70…)
verification FAILED: 3 OK, 1 CHANGED, 0 MISSING, 0 EXTRA
```

An `EXTRA` file (present on disk, absent from the manifest) also fails
verification: an unexpected object in an evidence container is an integrity
event, not a footnote.

### `custody` — append a chain-of-custody event

```bash
python -m cust0dia custody /cases/2026-014/documentation/manifest.json \
    /cases/2026-014/documentation/custody-log.csv \
    --exhibit exhibit-002_incident-report.txt \
    --actor "John Doe" --action TRANSFERRED \
    --notes "Handed to D. Okafor, HQ evidence locker, signature on file."
```

Appends one row — `timestamp_utc,actor,action,exhibit_path,exhibit_sha256,notes`
— to the log, creating it (with header) if it does not exist. The exhibit must
appear in the given manifest; custody events can only be logged against evidence
that has actually been hashed. The log is append-only: cust0dia refuses to
append to a CSV whose header it does not recognize, rejects control characters
in all free-text fields (one event is always one line — no log injection), and
refuses to place the log inside the evidence directory.

### Arguments at a glance

- `manifest` `evidence_dir` — default: — (required). Exhibit directory
  to hash recursively.
- `manifest` `--output-dir` — default: — (required). Where
  `manifest.csv` / `manifest.json` are written; must not be inside the
  evidence directory.
- `verify` `manifest` — default: — (required). Path to a saved
  `manifest.json` or `manifest.csv`.
- `verify` `evidence_dir` — default: — (required). Directory to re-hash
  and compare against the manifest.
- `custody` `manifest` — default: — (required). Manifest the exhibit
  hash is anchored to (JSON carries the evidence root).
- `custody` `log` — default: — (required). Custody CSV to append to;
  created with header if missing.
- `custody` `--exhibit` — default: — (required). Exhibit path, exactly
  as it appears in the manifest.
- `custody` `--actor` — default: — (required). Who performed the action
  (free text).
- `custody` `--action` — default: — (required). What happened —
  `COLLECTED`, `TRANSFERRED`, `ANALYZED`, `RETURNED`, ...
- `custody` `--notes` — default: — (required). Free-text detail; control
  characters are rejected.

---

## ✅ Current capabilities

1. **Recursive manifest generation.** Every regular file under the evidence
   root is hashed in 64 KiB streams (constant memory, multi-GB files included)
   and recorded with relative path, size, digest, mtime, and hash time — all
   timestamps UTC ISO-8601, all rows sorted by path.
2. **Dual serialization, one shared format.** CSV with the header
   `relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc`, and JSON with
   `tool`, `generated_at_utc`, `root`, and `entries`. Both are written on every
   run; both are accepted by `verify` and `custody`.
3. **Integrity verification with tamper detection.** Per-file
   `OK`/`CHANGED`/`MISSING`/`EXTRA` reporting, digest-prefix detail on changed
   files, deterministic sorted output, and scriptable exit codes.
4. **Append-only chain-of-custody logging.** Header-validated appends,
   manifest-anchored exhibit hashes, control-character rejection, and creation
   of missing log directories.
5. **Evidence-tree write protection.** Output paths are resolved and checked
   before anything is written; anything landing inside the evidence directory
   is refused with a clear error.
6. **Defensive manifest parsing.** Manifests are treated as untrusted input:
   headers and field counts are validated, sizes must be integers, and relative
   paths containing `..` or absolute paths are rejected, closing path-traversal
   during verification.

---

## ⚠️ Known limitations

- Directory structure itself is not manifested — only files. An empty directory
  that disappears will not be reported.
- File metadata beyond mtime (ownership, permissions, xattrs, ACLs) is not
  recorded; the manifest proves content integrity, not attribute integrity.
- Symlinked directories are never descended (a deliberate cycle/escape guard);
  symlinked files are hashed as the content they resolve to. A broken symlink
  aborts the run with a clear error rather than being silently skipped.
- The custody log is tamper-evident only by convention (append-only CSV); it is
  not itself hash-chained. Sign or hash the log file externally if you need to
  prove the log was not rewritten.
- Hashes are computed per run with no cross-run caching, so re-manifesting a
  very large tree re-reads every byte. That is intentional: a manifest must
  reflect what is on disk now, not what a cache remembers.

---

## 📝 Notes

- Manifests are designed to diff: commit them to a case repository, or keep
  them in write-once storage alongside your reports.
- `verify` against a CSV manifest and `verify` against the JSON manifest from
  the same run produce identical results; the JSON additionally records the
  evidence root, which `custody` uses to keep its log out of the evidence tree.
- Custody actions are free text by design (`COLLECTED`, `TRANSFERRED`,
  `ANALYZED`, `RETURNED`, ...) — adopt a consistent vocabulary per case and
  stick to it.
- All fixtures under `examples/` are fictional and safe to modify; the tool
  never writes to them.
- cust0dia is for lawful, authorized investigative documentation work only.
