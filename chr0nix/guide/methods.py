"""The method catalogue: static, in-code knowledge, and its rendering.

Everything in this module is data plus pure functions over it — no I/O
except rendering strings. The catalogue is a tuple written out in
source for the same reason the console's tool registry is: in a tool
that may be scrutinized in court, the guidance the operator saw must be
exactly the guidance a reviewer can read here.

Handoff URL templates are real, current patterns. Those carrying a
``{query}`` placeholder are rendered with the operator's query when one
is given (``hint <method-id> <query...>``); those without one are base
URLs where the operator types the query into the page. Templates are
shown verbatim when no query is given, so the placeholder convention is
self-documenting.
"""

from dataclasses import dataclass

from .. import tiers
from ..errors import SuiteError

#: Display order for `methods` and `run`: categories are fixed, not
#: derived, so the listing is stable as the catalogue grows.
CATEGORIES = ("identifier-research", "imagery", "infrastructure", "property", "environmental", "preservation")


@dataclass(frozen=True)
class Method:
    """One investigative research method.

    Frozen because the catalogue is reference data: a method is a
    documented procedure, and procedures do not mutate at runtime.

    ``related`` names the natural next-tier methods — ``capture``
    prints them as follow-up suggestions, so a recorded finding leads
    the investigator to the next corroboration step.
    """

    id: str
    name: str
    tier: str  # tiers.GREEN or tiers.YELLOW
    category: str
    summary: str
    steps: tuple[str, ...]
    handoffs: tuple[str, ...]
    capture_fields: tuple[str, ...]
    tools: tuple[str, ...]
    related: tuple[str, ...]


#: The catalogue, in display order within each category. Person-focused
#: identifier research is YELLOW (lawful only for authorized casework);
#: passive, public-records methods are GREEN.
METHODS: tuple[Method, ...] = (
    Method(
        id="username-search",
        name="Username search across platforms",
        tier=tiers.YELLOW,
        category="identifier-research",
        summary=(
            "Check whether a handle exists across platforms and whether the "
            "accounts plausibly belong to the same person."
        ),
        steps=(
            "Start from the exact handle and its obvious variants (dots, "
            "underscores, trailing digits); write down each variant you check "
            "so the search is reproducible.",
            "Run the handle through a multi-platform name checker in the "
            "browser (handoffs below) and note every platform where the name "
            "is registered, taken, or free.",
            "Open each candidate profile in the browser and compare bios, "
            "photos, locations, and posting history against what the case "
            "already knows — a name match alone is not an identity match.",
            "Cross-check profile photos with reverse-image, and any exposed "
            "email or phone with email-research / phone-research.",
            "Record an identity claim only when at least two independent "
            "sources corroborate it — the standard h4ndl3's findings store "
            "enforces. Capture platform, profile URL, and confidence.",
        ),
        handoffs=(
            "https://whatsmyname.app/?q={query}",
            "https://namechk.com/{query}",
            "https://www.google.com/search?q=%22{query}%22",
        ),
        capture_fields=("platform", "profile_url", "confidence", "notes"),
        tools=("Sherlock", "Maigret"),
        related=("reverse-image", "email-research", "web-archive"),
    ),
    Method(
        id="email-research",
        name="Email address research",
        tier=tiers.YELLOW,
        category="identifier-research",
        summary=(
            "Assess what an email address exposes: breach appearances, "
            "account registrations, and public profiles."
        ),
        steps=(
            "Check the address against the breach corpus in the browser "
            "(HIBP handoff): breach appearances establish the address is "
            "real, in use, and roughly how old it is.",
            "The holehe concept: many platforms' signup or password-reset "
            "flows reveal whether an address is registered. Check the "
            "highest-value platforms manually rather than automating.",
            "Look up the Gravatar avatar: MD5-hash the lowercased, trimmed "
            "address and open the avatar URL with that hash — a set avatar "
            "often links to a public profile.",
            "Search the address in quoted form for forum posts, pastes, and "
            "archived pages; preserve anything found with web-archive before "
            "recording it.",
            "Capture each service, the result, and the source URL. Never "
            "attempt to access any account — observing public signals is "
            "the line.",
        ),
        handoffs=(
            "https://haveibeenpwned.com/account/{query}",
            "https://www.gravatar.com/avatar/{query}",
            "https://www.google.com/search?q=%22{query}%22",
        ),
        capture_fields=("service", "result", "source_url", "notes"),
        tools=("holehe",),
        related=("username-search", "web-archive"),
    ),
    Method(
        id="phone-research",
        name="Phone number research",
        tier=tiers.YELLOW,
        category="identifier-research",
        summary=(
            "Resolve a number's carrier, line type, and region, and check "
            "for public exposure."
        ),
        steps=(
            "Normalize the number to international format (+country-code...) "
            "before anything else — every downstream check keys off it.",
            "The phoneinfoga concept: the national numbering plan alone "
            "yields country, carrier, and line type (mobile / landline / "
            "VoIP) for most numbers. A browser carrier lookup gives the same "
            "result without running anything.",
            "Search the number in quoted form in several formats "
            "(international, national, grouped differently) — classifieds "
            "and business listings are the usual hits.",
            "Where lawful and authorized, messaging-app profile signals "
            "(photo, about text) can corroborate that the number is in use; "
            "document only what is publicly visible to any user.",
            "Capture carrier, line type, and country; treat VoIP results as "
            "lower-confidence attribution.",
        ),
        handoffs=(
            "https://freecarrierlookup.com/",
            "https://www.google.com/search?q=%22{query}%22",
        ),
        capture_fields=("carrier", "line_type", "country", "notes"),
        tools=("phoneinfoga",),
        related=("username-search",),
    ),
    Method(
        id="satellite-imagery",
        name="Satellite and aerial imagery",
        tier=tiers.GREEN,
        category="imagery",
        summary=(
            "Study a location from above: current and historical satellite "
            "and aerial imagery, entirely in the browser."
        ),
        steps=(
            "Start with Google Maps/Earth for the highest-resolution "
            "commercial view and its historical-imagery timeline.",
            "Cross-check Bing Maps — its aerial and bird's-eye coverage is "
            "shot on different dates and angles, and sometimes resolves what "
            "Google does not.",
            "For dated, citable imagery use USGS EarthExplorer and Sentinel "
            "Hub EO Browser: both filter by exact acquisition date, cloud "
            "cover, and sensor.",
            "Compare acquisition dates, not just content — knowing which "
            "image is newest matters more than which looks best.",
            "Capture coordinates, imagery acquisition date, zoom level, and "
            "source. An image without its date is an anecdote.",
        ),
        handoffs=(
            "https://www.google.com/maps/search/{query}",
            "https://earth.google.com/web/",
            "https://www.bing.com/maps?q={query}",
            "https://earthexplorer.usgs.gov/",
            "https://apps.sentinel-hub.com/eo-browser/",
        ),
        capture_fields=("coordinates", "imagery_date", "zoom", "source", "notes"),
        tools=(),
        related=("maps-geolocation", "web-archive"),
    ),
    Method(
        id="maps-geolocation",
        name="Geolocation corroboration",
        tier=tiers.GREEN,
        category="imagery",
        summary=(
            "Corroborate where a photo or video was taken by matching "
            "visible features against map and street-level imagery."
        ),
        steps=(
            "Extract every anchor the image offers: road layout, building "
            "outlines, signage, terrain, shadows, vegetation.",
            "Form a candidate area first (from case knowledge or "
            "satellite-imagery), then try to disprove it — a geolocation "
            "holds when the anchors survive attempts to falsify them.",
            "Confirm with street-level imagery: facades, street furniture, "
            "and sign text are the strongest single anchors.",
            "Check shadow direction against the claimed time of day as a "
            "consistency test, not proof.",
            "Capture the location, your confidence, and the evidence "
            "anchors; two independent anchors is the working minimum.",
        ),
        handoffs=(
            "https://www.google.com/maps/search/{query}",
            "https://www.bing.com/maps?q={query}",
        ),
        capture_fields=("location", "confidence", "evidence", "notes"),
        tools=(),
        related=("satellite-imagery", "reverse-image"),
    ),
    Method(
        id="domain-infrastructure",
        name="Domain infrastructure mapping",
        tier=tiers.GREEN,
        category="infrastructure",
        summary=(
            "Map a domain's public footprint passively: certificates, DNS, "
            "and registration history."
        ),
        steps=(
            "Start with certificate-transparency logs (crt.sh): every "
            "publicly trusted certificate ever issued for the domain and its "
            "subdomains, often revealing hosts the owner never linked.",
            "Resolve current DNS records in the browser (dns.google): "
            "A/AAAA for hosting, MX for the mail provider, TXT for "
            "verification strings that leak third-party services in use.",
            "Check registration and IP history (viewdns.info): registrar, "
            "creation date, and historical IPs date the infrastructure and "
            "sometimes unmask earlier hosting.",
            "Everything here is passive — public records only. Do not probe "
            "the infrastructure itself.",
            "Capture the domain, record type, value, and source.",
        ),
        handoffs=(
            "https://crt.sh/?q={query}",
            "https://dns.google/query?name={query}",
            "https://viewdns.info/whois/?domain={query}",
        ),
        capture_fields=("domain", "record_type", "value", "source", "notes"),
        tools=(),
        related=("web-archive",),
    ),
    Method(
        id="offline-maps",
        name="Offline map orientation",
        tier=tiers.GREEN,
        category="imagery",
        summary=(
            "Orient around a location with OpenStreetMap data held entirely "
            "on your own drive — no network, no query leakage."
        ),
        steps=(
            "Every browser map search is a query you hand to a third party: "
            "it places an investigator at a location at a time. For "
            "sensitive cases, do orientation offline first and go online "
            "only for what genuinely needs live data.",
            "The pattern: vector OSM tiles in PMTiles archives on local "
            "storage, drawn by MapLibre in a network-isolated browser "
            "profile — 'offline' enforced by a namespace with no route out, "
            "not by intention. (One working implementation: the map-view "
            "stack in the operator's dotfiles.)",
            "Use it for street layout, drive routes, line-of-sight, and "
            "distances — the questions base-map geometry answers without "
            "anyone knowing you asked.",
            "Record the tile archive's build date alongside any observation: "
            "OSM drifts slowly, and a map's vintage matters to what it can "
            "attest.",
            "Capture coordinates and the observation; switch to "
            "satellite-imagery when you need dated photographic coverage.",
        ),
        handoffs=(),
        capture_fields=("coordinates", "observation", "map_vintage", "notes"),
        tools=("PMTiles + MapLibre offline stack (e.g. map-view)",),
        related=("satellite-imagery", "maps-geolocation"),
    ),
    Method(
        id="property-history",
        name="Property records and history",
        tier=tiers.GREEN,
        category="property",
        summary=(
            "Pull a property's public record: ownership history, sales, "
            "parcel data, and listing history overlays."
        ),
        steps=(
            "Start with the county assessor / recorder: ownership, parcel "
            "boundaries, assessed value, and transfer history are public "
            "records in most US jurisdictions — the authoritative source "
            "everything else repackages.",
            "Cross-check listing portals (Zillow/Redfin/Realtor) for sale "
            "and price history, listing photos, and days-on-market — photos "
            "of interiors and yards persist long after a sale closes.",
            "Overlay parcel viewers where the county offers GIS maps: lot "
            "lines, structures, and sometimes historical aerials layered "
            "on the parcel.",
            "Everything here is a passive public record — do not contact "
            "owners or occupants.",
            "Capture the address, the record type, the detail, and which "
            "source each fact came from; assessor records outrank portals.",
        ),
        handoffs=(
            "https://www.zillow.com/homes/{query}",
            "https://www.redfin.com/stingray/do/location-autocomplete?location={query}",
            "https://www.google.com/search?q={query}+county+assessor",
        ),
        capture_fields=("address", "record_type", "detail", "source", "notes"),
        tools=(),
        related=("satellite-imagery", "web-archive"),
    ),
    Method(
        id="weather-history",
        name="Historical weather and conditions",
        tier=tiers.GREEN,
        category="environmental",
        summary=(
            "Reconstruct conditions at a place and time: weather, sunrise "
            "and sunset, visibility — for timeline corroboration."
        ),
        steps=(
            "Weather is a cross-examination tool: a statement that it was "
            "pouring, pitch dark, or clear at a time and place is checkable "
            "against records.",
            "Pull the hourly history for the nearest station (Weather "
            "Underground history, NOAA/NWS records): precipitation, "
            "temperature, wind, visibility.",
            "Fix the light: timeanddate gives sunrise, sunset, and civil "
            "twilight for any date and coordinates — 'I saw him clearly at "
            "9 pm' means different things in June and December.",
            "Tie conditions back into the case timeline (`use timeline`): "
            "weather and light are event rows like any other, with sources.",
            "Capture location, the date/time window, conditions, and the "
            "station or source the reading came from.",
        ),
        handoffs=(
            "https://www.wunderground.com/history/daily/{query}",
            "https://www.weather.gov/wrh/climate?wfo={query}",
            "https://www.timeanddate.com/sun/{query}",
        ),
        capture_fields=("location", "datetime_window", "conditions", "source", "notes"),
        tools=(),
        related=("satellite-imagery",),
    ),
    Method(
        id="web-archive",
        name="Web archiving and preservation",
        tier=tiers.GREEN,
        category="preservation",
        summary=(
            "Find and preserve past versions of web pages before they "
            "change or disappear."
        ),
        steps=(
            "Check the Wayback Machine first: the '*' URL form lists every "
            "capture of a page; the calendar view shows them over time.",
            "Check archive.today (archive.ph) as a second, independent "
            "archive — its captures often include pages Wayback excludes "
            "via robots.txt.",
            "Preserve what you rely on the moment you find it: submit the "
            "live URL to both archives (save handoffs) so the record "
            "outlives the page.",
            "Quote snapshots by their exact timestamped URL — 'the page "
            "said X' is hearsay; a snapshot is a citable record.",
            "Capture the original URL, the snapshot timestamp, and the "
            "archive; note a hash of any downloaded copy in the notes.",
        ),
        handoffs=(
            "https://web.archive.org/web/*/{query}",
            "https://web.archive.org/save/{query}",
            "https://archive.ph/newest/{query}",
            "https://archive.ph/submit/?url={query}",
        ),
        capture_fields=("url", "snapshot_timestamp", "archive", "notes"),
        tools=(),
        related=(),
    ),
    Method(
        id="reverse-image",
        name="Reverse image search",
        tier=tiers.GREEN,
        category="imagery",
        summary=(
            "Find where an image appears elsewhere: earlier postings, other "
            "sizes, other contexts."
        ),
        steps=(
            "Run the image through Google Lens, TinEye, and Yandex — their "
            "indexes differ enough that checking only one is a coin flip. "
            "Yandex is often strongest on faces and places, TinEye on exact "
            "matches with earliest-found dates.",
            "Crop to the distinctive region and retry: background clutter "
            "defeats matching more often than the image being unknown.",
            "Read matches by date, not by count: the earliest posting is "
            "usually closest to the source.",
            "Preserve each significant match page with web-archive "
            "immediately — matched pages are exactly the ones that vanish.",
            "Capture the match URL, the search engine, and the earliest "
            "date found.",
        ),
        handoffs=(
            "https://lens.google.com/uploadbyurl?url={query}",
            "https://tineye.com/search?url={query}",
            "https://yandex.com/images/search?rpt=imageview&url={query}",
        ),
        capture_fields=("match_url", "source", "first_seen", "notes"),
        tools=(),
        related=("web-archive", "username-search"),
    ),
    Method(
        id="image-metadata",
        name="Image metadata examination",
        tier=tiers.GREEN,
        category="imagery",
        summary=(
            "Extract what an image file itself records — camera, "
            "timestamps, GPS, anomalies — offline, with m3talex."
        ),
        steps=(
            "This is an internal workflow, not a browser one: `use m3talex`, "
            "then `scan <image-or-directory>` against the exhibit.",
            "Hash the image into the cust0dia manifest first, so the "
            "examined bytes are the recorded bytes.",
            "Read EXIF critically: timestamps are camera-clock claims, GPS "
            "can be stripped or spoofed, and editing software leaves "
            "signatures — m3talex flags the common anomalies.",
            "Annotate a copy (never the exhibit) to mark regions of "
            "interest — the swappy workflow, documented in "
            "docs/image-annotation.md.",
            "Capture the exhibit path and each finding.",
        ),
        handoffs=(),
        capture_fields=("exhibit", "finding", "notes"),
        tools=("swappy (see docs/image-annotation.md)",),
        related=("reverse-image",),
    ),
    Method(
        id="video-cctv",
        name="CCTV and video export handling",
        tier=tiers.GREEN,
        category="preservation",
        summary=(
            "Handle CCTV and video exports as evidence: hash first, then "
            "build the timeline."
        ),
        steps=(
            "Hash before you watch: `use cust0dia`, set the export "
            "directory as evidence, and `run` — the manifest fixes the "
            "bytes before any player or converter touches them.",
            "Never convert the original export; work on copies. Proprietary "
            "players and codecs are documented in the case notes, not "
            "'fixed'.",
            "Normalize event times with `use timeline`: CCTV exports are "
            "notorious for clock drift and local-time timestamps — record "
            "the drift you observe, with evidence.",
            "Log every transfer of the export in the custody log as it "
            "moves between media.",
            "Capture the exhibit path and each observation.",
        ),
        handoffs=(),
        capture_fields=("exhibit", "observation", "timestamp_utc", "notes"),
        tools=(),
        related=(),
    ),
)


def lookup_method(method_id: str) -> Method:
    """Return the method called ``method_id`` or raise."""
    for method in METHODS:
        if method.id == method_id:
            return method
    known = ", ".join(method.id for method in METHODS)
    raise SuiteError(f"unknown method {method_id!r}; known methods: {known}")


def is_yellow(method_id: str) -> bool:
    """True if ``method_id`` names a YELLOW method.

    Unknown ids return False so the console's tier check passes them
    through GREEN and they fail with the clean ``unknown method`` error
    from :func:`lookup_method` rather than a spurious challenge — the
    same malformed-invocation convention as the casework tiers.
    """
    return any(method.id == method_id and method.tier == tiers.YELLOW for method in METHODS)


def render_listing() -> str:
    """The `methods` view: the catalogue grouped by category, tier-marked."""
    lines: list[str] = []
    for category in CATEGORIES:
        lines.append(f"{category}:")
        for method in METHODS:
            if method.category == category:
                marker = " [yellow]" if method.tier == tiers.YELLOW else ""
                lines.append(f"  {method.id:<24}{method.name}{marker}")
    return "\n".join(lines)


def render_hint(method: Method, query: str | None) -> str:
    """The full guidance for one method, with handoffs rendered for ``query``.

    Templates are shown verbatim when no query is given; with a query,
    every ``{query}`` placeholder is substituted. URLs are printed for
    the operator to paste into a browser — the suite never opens them.
    """
    lines = [
        f"{method.id} — {method.name}{' [yellow]' if method.tier == tiers.YELLOW else ''}",
        f"category: {method.category}",
        "",
        method.summary,
        "",
        "Steps (high-ROI first):",
    ]
    lines += [f"  {index}. {step}" for index, step in enumerate(method.steps, start=1)]
    lines.append("")
    if method.handoffs:
        lines.append(
            "Browser handoffs (paste into your browser — the suite never opens URLs):"
        )
        for template in method.handoffs:
            if query is not None:
                lines.append(f"  {template.replace('{query}', query)}")
            else:
                lines.append(f"  {template}")
    else:
        lines.append("Browser handoffs: (none — internal workflow)")
    if method.tools:
        lines.append("")
        lines.append(
            "External tools referenced (by name only — the suite never runs them): "
            + ", ".join(method.tools)
        )
    lines.append("")
    lines.append("Capture fields: " + ", ".join(method.capture_fields))
    lines.append(
        f"record findings with: capture {method.id} "
        + " ".join(f"{field}=..." for field in method.capture_fields[:2])
    )
    return "\n".join(lines)
