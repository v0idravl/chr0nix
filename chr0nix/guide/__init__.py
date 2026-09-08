"""chr0nix.guide — an offline knowledge base of investigative research methods.

guide encodes "what you could do with tools like Sherlock, Maigret, or
phoneinfoga" as documented guidance, in the same spirit as h4ndl3: the
professional skill is a defensible, documented process, not firing
scrapers. The suite never executes external tools and never makes
network calls — guide tells the investigator *what* to check, *where*
(as printed URLs the operator pastes into a browser themselves), and in
*what order* (high-ROI first), then provides a tiered capture flow to
record what came back into the active case's event log.

The knowledge base is static, in-code data — no runtime loading, so
the guidance a reviewer reads in source is exactly the guidance the
console prints. Each method carries:

- a legal-risk **tier** (see :mod:`chr0nix.tiers`): person-focused
  identifier research is YELLOW and goes through the challenge/ack
  attestation flow; passive documentation methods are GREEN;
- ordered **steps**, high-ROI first;
- **handoffs**: URL templates with ``{query}`` placeholders, printed
  verbatim (or rendered with the operator's query) — the suite prints,
  the human browses;
- **capture fields**: the vocabulary ``capture`` accepts when recording
  what the method turned up, so findings are structured and reviewable;
- **tool references by name only** (e.g. "Sherlock", "phoneinfoga"):
  documented context for what the automated equivalents do, never an
  invocation of them.

The capture design answers the four questions courts and compliance
teams routinely ask of OSINT work:

1. *Where did this information come from?* — every method's capture
   vocabulary includes its source fields (``source_url``, ``source``,
   ``archive``, ...); a finding without provenance cannot be recorded.
2. *When was it accessed?* — captures land in the case's append-only
   ``events.csv``, timestamped UTC at write time.
3. *Was it publicly available?* — the catalogue only documents passive,
   public sources; person-focused research is YELLOW-tiered and the
   steps state the line explicitly.
4. *Can the collection process be documented?* — the process is the
   artefact: tier attestations in ``attest.csv``, findings in
   ``events.csv``, and the method guidance itself readable in source.
"""
