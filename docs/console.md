# The chr0nix console

The console is the suite's interactive front end: a curses TUI (stdlib
`curses`, Linux/macOS) modeled on operator consoles like metasploit. One
operator session over the exact same core modules the CLIs use — it adds no
new trust surface: no dependencies, no network paths, no dynamic code
loading, and its tool registry is a static, in-code list
(`chr0nix/console/tools.py`), so the set of code that can execute is exactly
the set of code a reviewer can read.

```bash
chr0nix console          # or: python -m chr0nix console
```

Requires a curses-capable terminal (at least 80×20). On terminals without
curses (e.g. Windows without `windows-curses`) the console exits with a
clean pointer to the CLIs, which remain fully functional — and since
casework and guide have their own CLIs (`chr0nix case`, `chr0nix guide`),
every console capability is reachable non-interactively.

The screen is, top to bottom: a **status bar** (active tool, workspace,
active case, evidence/output/manifest/log — what the next command will
touch, before it runs), a **scrollback** (verify statuses color-coded when
the terminal supports color), and an **input line** with a small line
editor: arrows, home/end, Ctrl-U clear, up/down history (in memory only —
never written to disk), tab completion, PgUp/PgDn paging, Ctrl-C/Ctrl-D to
leave.

---

## Core grammar

The grammar is deliberately tiny, in the operator-console tradition:

| Command | Meaning |
| --- | --- |
| `help [command]` | usage for everything available now, or one command |
| `show tools` | the registered tools, tier-marked, with the active one |
| `show options` | the session: evidence / output / manifest / log / actor / workspace |
| `show attestations` | the workspace attestation log, verbatim |
| `use <tool>` | make a tool active (bare: list tools) |
| `set <option> <value>` | set a session option (bare `set` shows options; `set <option>` shows one value) |
| `unset <option>` | clear an option |
| `run` | the active tool's primary action |
| `ack <reason...>` | confirm the pending YELLOW action (recorded in attest.csv) |
| `clear` | wipe the screen (alias: `/clear`) |
| `exit` / `quit` | leave the console |

### Forgiving dispatch

Dispatch is deliberately forgiving, in the sliver tradition:

- a bare tool name selects the tool: `casework` is `use casework`;
- a tool name as the first word runs the rest of the line in that tool's
  context: `casework init /cases/2026` is `use casework` plus
  `init /cases/2026`;
- any tool command typed from anywhere switches the active tool to its
  owner — announcing the switch, never silently.

Parsing uses `shlex.split`: quoted arguments work, and there is no shell —
an evidence console has no business evaluating command lines.

### Session options

`set` / `unset` manage six options, each validated eagerly at `set` time
(an investigator should learn immediately that a path is wrong, not after
composing the rest of a command):

- `evidence` — an existing directory; the case's evidence tree;
- `output` — where tools write; setting it *proposes* `manifest` and `log`
  paths inside it (`manifest.json`, `custody-log.csv`) when they are unset;
- `manifest` — an existing manifest file, when set explicitly;
- `log` — the custody log; never the same file as the manifest;
- `actor` — the operator's name, recorded in custody and event logs;
- `workspace` — the casework workspace (an initialized one, or an empty
  directory casework's `init` can take over).

Every writable path (output, log, workspace) is refused if it resolves
inside the evidence tree — the cardinal "read-only on evidence" rule.

## The tools

`show tools` lists the registry. Each tool adds its own commands on top of
the core grammar, and `run` executes the active tool's primary action:

| Tool | `run` | Commands |
| --- | --- | --- |
| `cust0dia` | two-phase: collect the manifest, then verify against it | `show exhibits`, `show log`, `log <exhibit> <ACTION> [notes...]` |
| `timeline` | build from the session evidence tree into the session output | `build <sources-dir> [output-dir] [NAME=IANA_TZ ...]`, `schema` |
| `h4ndl3` | validate the case store and refresh its report | `worksheet`, `add`, `validate`, `report` |
| `m3talex` | batch-scan the session evidence tree | `scan <image-or-directory> [output-dir]` |
| `casework` | the workspace case table + status summary | `init`, `new`, `cases`, `open`, `status`, `categorize`, `classify`, `link`, `links`, `subject add\|edit\|show\|set`, `subjects`, `vehicle add\|edit\|show\|set`, `vehicles`, `event`, `synopsis`, `show case`, `inbox`, `file`, `statement`, `statement-sign`, `statements` |
| `guide` | the method catalogue | `methods`, `hint <method-id> [query...]`, `capture <method-id> <field>=<value> ...` |

cust0dia's `run` is deliberately two-phase: before a manifest exists there
is nothing to verify against, so it *collects*; once one exists, it
*verifies*. To re-collect a legitimately changed tree, `unset manifest` and
`run` again. For casework and guide details see
[docs/casework.md](casework.md) and [docs/guide.md](guide.md); every
casework and guide command also has a CLI equivalent (`chr0nix case ...`,
`chr0nix guide ...`).

## Guided profile forms

Adding or editing a subject or transportation (vehicle) profile is a
guided, field-by-field prompt — short info in boxes, sliver-style, rather
than one long command line:

```text
chr0nix:casework > subject add
new subject profile
Enter keeps [current] / skips; `done` saves now; `cancel` aborts.
[1/12] Subject id (slug-safe: lowercase letters, digits, hyphens (e.g. subj-001)): subj-001
[2/12] Name / primary nickname (defaults to the id if left blank): Red Hoodie
[3/12] Aliases & nicknames (comma-separated): smithy, smitty
...
[12/12] Notes (free text) — or :edit for $EDITOR:
```

Each step shows a self-explanatory label and a format hint; when editing
(`subject edit subj-001`) the current value appears in brackets and **Enter
keeps it**. Multi-value fields take comma-separated input. `done` saves the
form as it stands; `cancel` writes nothing. While a form is active, every
typed line is form input — commands resume when the form ends.

`subject set <id> <field> [value...]` remains the quick one-shot path (no
value clears the field), and `subject show <id>` renders the aligned
profile card with the cases the subject is linked to. The `vehicle`
commands mirror all of this.

## The $EDITOR handoff

Anything long-form belongs in a real editor, not a line prompt. Typing
`:edit` at a form's notes step, or as the detail/body of `statement` or
`event` (`statement stmt-001 "J. Doe" witness :edit`), suspends curses and
opens `$VISUAL` / `$EDITOR` (fallback `nvim`, then `vi`) on a temp file
seeded with the current text and a commented instructions header. Save and
exit to keep the text (header lines are stripped, never stored); exit
without saving, or save empty, to abort — the console restores exactly as
it was and shows a one-line confirmation. The same helper backs the CLI:
`chr0nix case statement record` without `--body`/`--body-file` opens the
editor on an interactive terminal.

## Tiers and attestation

Every console action carries a legal-risk tier (`chr0nix/tiers.py`), and the
tier decides what "running it" means:

- **GREEN** — pure offline documentation. Runs immediately.
- **YELLOW** — lawful only under specific circumstances: identifier research
  tied to a person (h4ndl3 `worksheet` / `add`), associating a person across
  cases (casework `link ... subject`), attesting a case to third parties
  (casework `status ... submitted|referred`), claiming a signed statement
  exists (casework `statement-sign`), and person-focused research guidance
  (guide `hint` / `capture` on the identifier-research methods).
- **RED** — reserved; defined but currently assigned to nothing.

A YELLOW action does not execute on first invocation. It answers with a
challenge — the tier, the rationale, and what confirmation looks like — and
only runs after an explicit, reasoned acknowledgment:

```text
chr0nix:h4ndl3 > worksheet j.doe_91
YELLOW — lawful only under specific circumstances: h4ndl3 worksheet j.doe_91
why: researching an identifier tied to a person — lawful only for authorized casework
your reason is recorded with a timestamp in the workspace attestation log
confirm with: ack <reason...>
chr0nix:h4ndl3 > ack employer-authorized LP investigation, case-2026-014
```

Every ack is appended to the workspace's append-only `attest.csv` —
`timestamp_utc,actor,action,reason` — with the same header-validation and
control-character rules as the custody log, so the judgment call itself is
part of the case record. `show attestations` prints the log. YELLOW actions
require a workspace (nowhere to attest, no action) and a session actor
(attestations are signed). A challenge holds at most one pending action:
`ack` consumes it, and any other command clears it, so a stale challenge
can never be confirmed by accident later.

A command's tier can depend on its arguments — casework `status` is YELLOW
only for `submitted`/`referred`, `link` only for `subject` — so the friction
stays proportionate: internal statuses and vehicle/case links run GREEN.

## Notes

- The console never reimplements evidence logic: handlers call the module
  cores in-process, so every safety rule the CLIs enforce (append-only
  custody, manifest anchoring, evidence-tree write protection,
  control-character rejection) is inherited from the same code.
- Command handlers are pure `(session, args) -> text` functions with no
  curses import, which keeps the entire decision layer unit-testable
  in-process — that is how `tests/console/` drives it.
- Exit codes: `0` on clean exit; `2` when the terminal cannot host the UI
  (too small, or no curses), with a pointer to the module CLIs.

### Shell completions (for the CLI, not the console)

Static completion scripts for the `chr0nix` dispatcher ship under
`completions/` and are also printable on demand:

```bash
chr0nix completion bash > ~/.local/share/bash-completion/completions/chr0nix
chr0nix completion zsh > ~/.zfunc/_chr0nix   # any directory on $fpath
```

They complete the top-level commands and the second-level words of
`case` / `guide` / `timeline` and the passthrough groups. Regenerate the
shipped copies after changing the dispatch grammar:
`chr0nix completion bash > completions/chr0nix.bash` (and the same for
zsh) — the test suite pins shipped files against the generator.

