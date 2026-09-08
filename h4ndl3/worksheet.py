"""Worksheet generation: identifier type -> checklist of lawful public checks.

This module is the heart of the tool's philosophy. h4ndl3 performs *no*
lookups itself. Instead, it produces a structured worksheet that tells the
analyst which public sources to check — manually, in a browser, logged
out, under employer authorization — and exactly what to record from each
one. Automation is limited by design; the worksheet is where rigor lives.

Every checklist entry carries three things:

- ``title`` — what to check;
- ``why`` — the lawful basis and investigative value, so the worksheet
  doubles as documentation of *why each step was defensible*;
- ``record`` — precisely what to paste into the findings store, so a
  finding captured at 02:00 reads the same as one captured at 14:00.

Checklists are plain data (tuples, not code) so a reviewer can audit the
entire methodology by reading one data structure per identifier type.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import identifiers


@dataclass(frozen=True)
class Check:
    """One lawful public check on a worksheet.

    ``frozen=True`` because checklists are shared constants — a worksheet
    render must never be able to mutate the methodology it renders.
    """

    title: str
    why: str
    record: str


# The corroboration rule, stated once and referenced everywhere, so the
# worksheet, the findings store, and the report can never drift apart.
CORROBORATION_RULE = (
    "A claim is CORROBORATED only when two independent sources are "
    "recorded in its corroborated_by field."
)

USERNAME_CHECKS: tuple[Check, ...] = (
    Check(
        title="Direct profile-URL existence checks on major platforms",
        why=(
            "Viewing a public profile page in a browser, logged out, is "
            "ordinary public access — no scraping, no login bypass, no ToS "
            "conflict."
        ),
        record=(
            "For each platform where the handle resolves, one finding per "
            "platform: the profile URL as source_url, the profile's "
            "self-asserted attributes (display name, photo, bio) as the claim."
        ),
    ),
    Check(
        title="Quoted-handle search-engine queries",
        why=(
            "Public web search surfaces forum posts, marketplaces, and "
            "comments where the handle appears in a public index."
        ),
        record=(
            "Each distinct public page where the handle appears, with the "
            "page URL — not the search-results URL — as source_url."
        ),
    ),
    Check(
        title="Cross-platform handle-reuse comparison",
        why=(
            "Handle reuse is only a lead. Comparing profile photos, bios, "
            "and account ages across platforms is what turns 'same string' "
            "into 'plausibly same person' — and the comparison itself must "
            "be documented to be defensible."
        ),
        record=(
            "A claim of identity linkage only after at least two platforms "
            "show matching non-handle signals; list each platform URL in "
            "corroborated_by."
        ),
    ),
    Check(
        title="Public web-archive snapshots of located profiles",
        why=(
            "Archive snapshots document what a public profile said at a "
            "point in time, which matters if the subject later edits or "
            "deletes it."
        ),
        record=(
            "The snapshot URL as source_url and the snapshot's capture time "
            "as retrieved_at context in notes; retrieved_at_utc remains the "
            "time *you* viewed it."
        ),
    ),
    Check(
        title="Public breach-notification services (manual lookup)",
        why=(
            "Checking whether an identifier appears in a known public "
            "breach corpus via the service's own web form is a permitted, "
            "attributed lookup — it never involves possessing or "
            "redistributing breach data."
        ),
        record=(
            "The service's result page URL as source_url; the claim limited "
            "to presence/absence of the identifier, never breach contents."
        ),
    ),
)

EMAIL_CHECKS: tuple[Check, ...] = (
    Check(
        title="Offline format and disposable-domain review",
        why=(
            "Structure, domain age signals, and disposable-provider "
            "membership are assessable without contacting anything — and "
            "assessing them first prevents wasted manual lookups."
        ),
        record=(
            "The claim (e.g. 'address uses a known disposable provider') "
            "with the provider's public documentation page as source_url."
        ),
    ),
    Check(
        title="Public avatar/profile services keyed by email hash",
        why=(
            "Services that publish a profile against an email hash expose "
            "only what the address owner chose to publish; viewing it in a "
            "browser is public access."
        ),
        record=(
            "The public profile URL as source_url; the displayed name or "
            "avatar description as the claim."
        ),
    ),
    Check(
        title="Quoted-address search-engine queries",
        why=(
            "Public indexes reveal where the address was posted publicly — "
            "mailing lists, forums, pastes of public documents — which are "
            "the lawful pivots from address to activity."
        ),
        record=(
            "Each distinct public page URL as source_url; quote only what "
            "is publicly visible in the claim text."
        ),
    ),
    Check(
        title="Public mailing-list and forum archives",
        why=(
            "Archives published for public reading carry no access barrier; "
            "they often hold the oldest attributable uses of an address."
        ),
        record=(
            "The archived message URL as source_url and the message date "
            "in notes; retrieved_at_utc is when you viewed the archive."
        ),
    ),
    Check(
        title="Local-part pivot into the username checklist",
        why=(
            "People reuse the part before the '@' as a handle. Treating "
            "that as a *hypothesis* and running the username checks on it "
            "keeps the pivot documented rather than assumed."
        ),
        record=(
            "Generate a second worksheet for the local part as a username; "
            "cross-reference any linkage claims between the two stores with "
            "mutual corroborated_by entries."
        ),
    ),
)

DOMAIN_CHECKS: tuple[Check, ...] = (
    Check(
        title="Public WHOIS / RDAP registration record",
        why=(
            "Registration data is published by design for accountability; "
            "querying the registrar's or registry's public RDAP web "
            "interface is an explicitly permitted lookup."
        ),
        record=(
            "The RDAP/WHOIS result URL as source_url; registration dates "
            "and registrar as the claim. Never record proxy-shielded "
            "registrant guesses as fact."
        ),
    ),
    Check(
        title="Certificate-transparency logs",
        why=(
            "CT logs exist to be publicly audited; they reveal subdomains "
            "and issuance history that the site itself does not advertise."
        ),
        record=(
            "The CT-log query URL as source_url; each observed hostname as "
            "its own claim so each can be corroborated independently."
        ),
    ),
    Check(
        title="Public DNS records via a web-based DNS viewer",
        why=(
            "DNS is public infrastructure data; a browser-based viewer "
            "keeps the lookup attributed and rate-respecting."
        ),
        record=(
            "The viewer's result URL as source_url; record types and "
            "values as the claim, with TTL anomalies in notes."
        ),
    ),
    Check(
        title="Public web-archive history of the site",
        why=(
            "Historical snapshots establish how long content has been "
            "public and what changed — critical when a site is scrubbed "
            "mid-investigation."
        ),
        record=(
            "Earliest and most recent relevant snapshot URLs; the "
            "continuity (or gap) claim must cite both in corroborated_by."
        ),
    ),
    Check(
        title="Direct content review of the live public site",
        why=(
            "Reading publicly served pages in a browser is the baseline "
            "lawful check; it grounds every other claim about the domain "
            "in what a visitor would actually see."
        ),
        record=(
            "The exact page URL as source_url; describe content in the "
            "claim, quote sparingly, and note anything requiring legal "
            "review before use."
        ),
    ),
)

#: Identifier type -> its checklist of lawful public checks.
CHECKLISTS: dict[str, tuple[Check, ...]] = {
    "username": USERNAME_CHECKS,
    "email": EMAIL_CHECKS,
    "domain": DOMAIN_CHECKS,
}


def render_worksheet(
    identifier: str,
    id_type: str,
    *,
    generated_at_utc: str,
    store_path: str = "findings.jsonl",
) -> str:
    """Render a Markdown research worksheet for one identifier.

    The output is deterministic: the same identifier, type, timestamp, and
    store path always produce byte-identical Markdown. That determinism is
    what lets two analysts — or one analyst and a reviewer months later —
    diff worksheets and see *only* meaningful changes.

    Args:
        identifier: The already-validated identifier under investigation.
        id_type: One of ``username``, ``email``, ``domain``.
        generated_at_utc: Injection point for the clock so tests and
            reproducible runs can pin the timestamp.
        store_path: The findings store path embedded in the ready-to-use
            ``h4ndl3 add`` command template on the worksheet.
    """
    checklist = CHECKLISTS[id_type]  # KeyError here means validation was skipped upstream.
    normalized = identifiers.validate(identifier, id_type)

    lines = [
        f"# Research Worksheet — {id_type}: `{normalized}`",
        "",
        f"- Generated (UTC): {generated_at_utc}",
        f"- Identifier type: {id_type}",
        f"- Findings store: `{store_path}`",
        "",
        "## Method",
        "",
        "Every check below is performed **manually, in a browser, logged "
        "out**, using only public sources, under employer authorization. "
        "This tool performs no lookups itself. For each finding, record: "
        "the source URL, the UTC time you retrieved it, your confidence, "
        "and the independent sources that corroborate it.",
        "",
        f"> {CORROBORATION_RULE}",
        "",
        "## Checks",
        "",
    ]
    for index, check in enumerate(checklist, start=1):
        lines += [
            f"### {index}. [ ] {check.title}",
            "",
            f"- **Why this check is lawful:** {check.why}",
            f"- **What to record:** {check.record}",
            "",
        ]

    lines += [
        "## Recording a finding",
        "",
        "Append each finding to the store with full provenance:",
        "",
        "```bash",
        "python -m h4ndl3 add \\",
        f"    --store {store_path} \\",
        '    --claim "<what you found, stated as an observation>" \\',
        '    --source-url "<exact public URL>" \\',
        f'    --retrieved-at "{generated_at_utc}" \\',
        "    --confidence low|medium|high \\",
        '    --corroborated-by "<url1>" "<url2>" \\',
        '    --notes "<optional context>"',
        "```",
        "",
        "The store rejects any finding missing a required field — the "
        "fast way is the compliant way.",
        "",
    ]
    return "\n".join(lines)
