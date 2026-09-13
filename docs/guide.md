# chr0nix guide — offline research guidance

guide is the suite's offline knowledge base of investigative research
methods: what you *could* do with tools like Sherlock, Maigret, or
phoneinfoga, encoded as documented procedure instead of executed automation.
The suite never runs external tools and never opens URLs — guide tells the
investigator *what* to check, *where* (browser handoffs printed for a human
to paste), and in *what order* (high-ROI first), then provides a tiered
capture flow to record what came back into the case's event log.

The catalogue is static, in-code data (`chr0nix/guide/methods.py`): no
runtime loading, so the guidance a reviewer reads in source is exactly the
guidance the operator saw.

Two front ends over the same code:

- the **CLI** — `chr0nix guide list | show | capture` (or
  `python -m chr0nix.guide`);
- the **console** — `use gu1d3`, with `methods` / `hint` / `capture`.

> ⚠️ **Authorized use only.** Person-focused research is lawful only for
> authorized casework; the YELLOW-tier gate exists to make that judgment
> call explicit and recorded.

---

## The catalogue

16 methods across seven categories. Person-focused identifier research is
YELLOW; passive, public-records methods are GREEN.

| Category | Methods |
| --- | --- |
| identifier-research | `username-search` [yellow], `email-research` [yellow], `breach-corpus` [yellow], `phone-research` [yellow] |
| imagery | `satellite-imagery`, `maps-geolocation`, `offline-maps`, `reverse-image`, `image-metadata` |
| infrastructure | `domain-infrastructure` |
| transport | `transport-tracking`, `vehicle-records` [yellow] |
| property | `property-history` |
| environmental | `weather-history` |
| preservation | `web-archive`, `video-cctv` |

Each method carries ordered steps (high-ROI first), **browser handoffs** —
URL templates with `{query}` placeholders, printed verbatim or rendered with
your query, never opened — **capture fields** (the vocabulary `capture`
accepts), tool references by name only, and **related methods** printed as
follow-up suggestions after a capture.

Most methods also carry **toolkit references**: pointers to current external
tooling grounded in [Bellingcat's Online Investigation
Toolkit](https://bellingcat.gitbook.io/toolkit) (categories: Maps &
Satellites, Geolocation, Image/Video, Social Media, People, Websites,
Companies & Finance, Conflict, Transport, Environment & Wildlife, Archiving,
Data Org & Analysis). Each reference is a name, a URL, and a one-line caveat
(cost, account requirement, legal sensitivity) — printed for your own
browser, never fetched by the suite.

## CLI usage

```bash
chr0nix guide list                          # the catalogue, tier-marked
chr0nix guide show satellite-imagery        # full guidance for one method
chr0nix guide show username-search j.doe_91 # handoff URLs rendered with the query
```

`show` prints the method's summary, its numbered steps, the handoff URLs,
any external tools referenced (by name only — the suite never runs them),
and the capture-field vocabulary.

### capture

```bash
chr0nix guide capture satellite-imagery \
  coordinates=34.05,-118.24 imagery_date=2026-07-12 source=google-earth \
  --workspace /cases/2026 --case case-2026-014 --actor "A. Rivera"
```

`capture` records what came back as an `osint-finding` event in the case's
append-only `events.csv` (`chr0nix/casework`), so what the investigator
learned sits in the same record as how the case moved. Field names are
validated against the method's capture vocabulary — an unknown field fails
with the vocabulary listed, so structured findings stay reviewable.

Capture writes into the casework record, so it needs what a console session
would hold:

- `--workspace PATH` (or `CHR0NIX_WORKSPACE`) — an initialized casework
  workspace (see [docs/casework.md](casework.md));
- `--case ID` — the case to record into (there is no "active case" outside
  the console);
- `--actor NAME` (or `CHR0NIX_ACTOR`) — recorded in the event row.

## Tier interaction

Every method carries a legal-risk tier (see `chr0nix/tiers.py`), and
capturing a **YELLOW** method — the person-focused identifier-research
methods, plus `vehicle-records` (plate/VIN lookups that can name an owner)
— is gated:

- **Console:** the first attempt answers with a challenge naming the action
  and why it is yellow; the action runs only after `ack <reason>`.
- **CLI:** the run refuses without `--ack "<reason>"`:

```bash
chr0nix guide capture username-search platform=instagram \
  profile_url=https://instagram.com/jdoe confidence=medium \
  --workspace /cases/2026 --case case-2026-014 --actor "A. Rivera" \
  --ack "employer-authorized LP investigation, case-2026-014"
```

Either way, the reason is appended — timestamped and attributed to the
actor — to the workspace's append-only `attest.csv`, so the judgment call
itself is part of the case record. `list` and `show` are always GREEN:
reading guidance attests nothing.

## Why the capture flow is shaped this way

The design answers the four questions courts and compliance teams ask of
OSINT work:

1. *Where did this information come from?* — every method's capture
   vocabulary includes its source fields (`source_url`, `source`,
   `archive`, ...); a finding without provenance cannot be recorded.
2. *When was it accessed?* — captures land in `events.csv`, timestamped UTC
   at write time.
3. *Was it publicly available?* — the catalogue only documents passive,
   public sources; person-focused research is YELLOW-gated and the steps
   state the line explicitly.
4. *Can the collection process be documented?* — the process is the
   artefact: attestations in `attest.csv`, findings in `events.csv`, and
   the method guidance itself readable in source.

## Console usage

```text
chr0nix:guide > methods                            # catalogue, tier-marked
chr0nix:guide > hint satellite-imagery 123 Main St # steps + browser handoffs
chr0nix:guide > hint username-search j.doe_91      # YELLOW — challenges first
chr0nix:guide > capture satellite-imagery coordinates=34.05,-118.24 imagery_date=2026-07-12 source=google-earth
```

Console `hint` is the CLI's `show`, and `methods` is `list`. Console
`capture` records into the session's *active case* (set with casework's
`open`) rather than a `--case` flag; everything else — field validation,
event type, related-method suggestions, the YELLOW gate — is identical.

## Notes

- Exit codes: `0` success; `2` operational error (unknown method, unknown
  capture field, missing workspace/case/actor). Usage errors exit `2` via
  argparse.
- guide contains no network code: handoff URLs are printed for the operator
  to paste into a browser — the suite never opens them.
- The catalogue is a fixed tuple in `chr0nix/guide/methods.py`; adding a
  method is an explicit, reviewable commit, same rule as the console's tool
  registry.
