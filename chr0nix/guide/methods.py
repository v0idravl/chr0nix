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
CATEGORIES = ("identifier-research", "imagery", "infrastructure", "transport", "property", "environmental", "preservation")

#: Base URL of Bellingcat's Online Investigation Toolkit — the remote
#: pointer for tool suggestions. Printed for the operator's own browser;
#: the suite never fetches it.
TOOLKIT_BASE = "https://bellingcat.gitbook.io/toolkit"


@dataclass(frozen=True)
class ToolReference:
    """One external-tool pointer: a name, a URL, and a one-line caveat.

    References are printed by ``hint`` / ``guide show`` for the operator
    to open in their own browser — the suite contains no network code
    and never fetches them. The caveat carries the one thing that most
    often matters in court or compliance review (cost, account
    requirements, jurisdictional sensitivity).
    """

    name: str
    url: str
    caveat: str = ""


def toolkit_category(slug: str) -> ToolReference:
    """A reference to a whole toolkit category (e.g. ``transport``)."""
    return ToolReference(
        f"Bellingcat toolkit: {slug.replace('-', ' ')}",
        f"{TOOLKIT_BASE}/categories/{slug}",
        "curated category listing; inclusion is not endorsement",
    )


def toolkit_tool(name: str, slug: str, caveat: str = "") -> ToolReference:
    """A reference to one tool's toolkit entry."""
    return ToolReference(name, f"{TOOLKIT_BASE}/more/all-tools/{slug}", caveat)


@dataclass(frozen=True)
class Method:
    """One investigative research method.

    Frozen because the catalogue is reference data: a method is a
    documented procedure, and procedures do not mutate at runtime.

    ``related`` names the natural next-tier methods — ``capture``
    prints them as follow-up suggestions, so a recorded finding leads
    the investigator to the next corroboration step.

    ``tool_references`` are printable pointers to current external
    tooling (grounded in Bellingcat's toolkit); ``tools`` stays the
    bare name list for quick scanning.
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
    tool_references: tuple[ToolReference, ...] = ()


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
        tools=("Sherlock", "Maigret", "WhatsMyName", "Blackbird"),
        related=("reverse-image", "email-research", "web-archive"),
        tool_references=(
            toolkit_tool("Sherlock", "sherlock", "runs locally; check its per-site list before trusting a 'not found'"),
            toolkit_tool("Maigret", "maigret", "richer per-site metadata than most name checkers"),
            toolkit_tool("WhatsMyName", "whats-my-name", "browser-based; no install"),
            toolkit_tool("Blackbird", "blackbird", "also checks email addresses"),
            toolkit_category("people"),
            toolkit_category("social-media"),
        ),
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
        tools=("holehe", "Ghunt (Google accounts)"),
        related=("username-search", "breach-corpus", "web-archive"),
        tool_references=(
            toolkit_tool("Have I Been Pwned", "have-i-been-pwned", "breach appearances only; never enter credentials anywhere"),
            toolkit_tool("Ghunt", "ghunt", "Google-account signals; use only where authorized"),
            toolkit_category("people"),
        ),
    ),
    Method(
        id="breach-corpus",
        name="Breach-corpus checking",
        tier=tiers.YELLOW,
        category="identifier-research",
        summary=(
            "Check whether an identifier appears in known data breaches — "
            "lawful framing: establish exposure, never touch the leaked data."
        ),
        steps=(
            "Define the purpose before you search: breach checking establishes "
            "that an address, number, or handle is real, active, and roughly "
            "how old it is. That is the lawful use. Downloading, purchasing, "
            "or replaying leaked credentials is not — never test a password, "
            "never log in, never redistribute corpus content.",
            "Start with Have I Been Pwned (handoff below): breach names and "
            "dates for an email address, no payload data.",
            "Aggregators (DeHashed, Leak-Lookup, Intelligence X) index the "
            "corpus itself, including partial payloads. Where your "
            "jurisdiction and authorization allow looking, record *that* an "
            "entry exists and its breach/date — not the leaked values.",
            "A breach appearance is corroboration, not identity: shared and "
            "recycled addresses are common. Cross-check with username-search "
            "before attributing anything.",
            "Capture the breach name, breach date, and the source you checked "
            "— never passwords, hashes, or personal payload fields.",
        ),
        handoffs=(
            "https://haveibeenpwned.com/account/{query}",
        ),
        capture_fields=("breach_name", "breach_date", "source", "notes"),
        tools=("DeHashed", "Leak-Lookup", "Intelligence X"),
        related=("email-research", "username-search"),
        tool_references=(
            toolkit_tool("Have I Been Pwned", "have-i-been-pwned", "breach metadata only; the safe first stop"),
            toolkit_tool("DeHashed", "dehashed", "indexes payload fields — check your legal basis before viewing"),
            toolkit_tool("Leak-Lookup", "leak-lookup", "same caveat: exposure yes, payloads no"),
            toolkit_tool("Intelx.io", "intelx.io", "broad breach index; some features paywalled"),
        ),
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
        tools=("phoneinfoga", "Truecaller (reverse lookup, jurisdiction-dependent)"),
        related=("username-search",),
        tool_references=(
            toolkit_tool("TrueCaller", "truecaller", "crowdsourced caller-ID; accuracy and legality vary by jurisdiction"),
            toolkit_category("people"),
        ),
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
        tool_references=(
            toolkit_tool("Google Earth Pro", "google-earth-pro", "historical imagery timeline; free desktop install"),
            toolkit_tool("Sentinel Hub Playground", "sentinal-hub-playground", "dated ESA imagery, free tier"),
            toolkit_tool("Apollo Image Hunter", "apollo-mapping", "commercial imagery search/purchase without subscription"),
            toolkit_category("maps-and-satellites"),
        ),
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
        tool_references=(
            toolkit_tool("GeoHints", "geohints", "region-specific street furniture reference (poles, signs, bollards)"),
            toolkit_tool("SunCalc", "suncalc", "sun position/shadow modeling for a date and place"),
            toolkit_tool("ShadeMap", "shademap", "global building/mountain shadow simulation"),
            toolkit_tool("Mapillary", "mapillary", "crowdsourced street-level imagery beyond the big two"),
            toolkit_tool("KartaView", "kartaview", "another crowdsourced street-level source"),
            toolkit_category("geolocation"),
        ),
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
        tool_references=(
            toolkit_tool("DomainTools Whois Lookup", "domaintools-whois-lookup", "deep history; paid tiers"),
            toolkit_tool("Whoxy", "whoxy", "whois history with a usable free tier"),
            toolkit_tool("ICANN Lookup", "icann-lookup", "current registration data, authoritative-ish"),
            toolkit_tool("Urlscan.io", "urlscan.io", "live site analysis; scans are public by default — do not submit sensitive URLs"),
            toolkit_tool("Shodan", "shodan", "device/service exposure; passive search only"),
            toolkit_category("websites"),
        ),
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
        tool_references=(
            toolkit_tool("Osint Tools Map", "osint-tools-map", "country-specific cadastral/property registry pointers"),
        ),
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
        tool_references=(
            toolkit_tool("SunCalc", "suncalc", "exact sun position and shadow direction for a date and place"),
            toolkit_tool("RAMMB SLIDER", "rammb-slider", "near-real-time global weather satellite loops"),
        ),
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
            "outlives the page. For social-media profiles and posts — the "
            "things that vanish fastest — an archiving browser extension "
            "(Hunchly) or an archiver pipeline (Bellingcat's Auto Archiver) "
            "captures the page as you viewed it, with timestamps.",
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
        tools=("Hunchly", "Auto Archiver", "Web Archives (browser extension)"),
        related=(),
        tool_references=(
            toolkit_tool("Wayback Machine", "internet-archive", "the canonical first stop; excludes robots.txt-blocked captures"),
            toolkit_tool("Archive.today", "archive.today", "independent second archive; strong on social media"),
            toolkit_tool("Hunchly", "hunchly", "captures pages as you browse; paid, offline store"),
            toolkit_tool("Auto Archiver", "auto-archiver", "Bellingcat's batch archiver for posts/videos; runs locally"),
            toolkit_tool("Web Archives", "web-archives", "one right-click to every archive at once"),
            toolkit_category("archiving"),
        ),
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
            "matches with earliest-found dates. RootAbout adds the Internet "
            "Archive's own image index, which the general engines miss.",
            "Crop to the distinctive region and retry: background clutter "
            "defeats matching more often than the image being unknown.",
            "Facial-recognition search (PimEyes, FaceCheck.ID) is a separate "
            "legal category in many jurisdictions — check your authorization "
            "before uploading a person's face, and note that both are paid "
            "for useful results.",
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
        tool_references=(
            toolkit_tool("TinEye", "tineye", "exact matches with earliest-found dates"),
            toolkit_tool("Google Lens", "google-lens", "strongest general index"),
            toolkit_tool("RootAbout", "rootabout", "reverse search against the Internet Archive's index"),
            toolkit_tool("PimEyes", "pimeyes", "facial recognition — legally sensitive; paid for useful results"),
            toolkit_tool("FaceCheck.ID", "facecheck.id", "facial recognition — same caveat as PimEyes"),
            toolkit_tool("Search by Image", "search-by-image", "browser extension hitting several engines at once"),
            toolkit_category("image-video"),
        ),
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
        tool_references=(
            toolkit_tool("ExifTool", "exiftool", "the reference EXIF reader; m3talex covers the common cases offline"),
            toolkit_tool("Forensically", "forensically", "web-based error-level analysis; a copy leaves your drive if used online"),
            toolkit_tool("xIFr", "xifr", "Firefox add-on for quick EXIF reads"),
        ),
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
        tool_references=(
            toolkit_tool("InVID", "invid", "keyframe extraction and video verification, on copies only"),
        ),
    ),
    Method(
        id="transport-tracking",
        name="Flight, vessel, and rail tracking",
        tier=tiers.GREEN,
        category="transport",
        summary=(
            "Place an aircraft, vessel, or route at a time: public ADS-B and "
            "AIS tracking data, historical positions, and fleet records."
        ),
        steps=(
            "Identify what you actually have: a flight number or tail "
            "number, a vessel name or MMSI/IMO, or a route and a time "
            "window. Trackers key off different identifiers — get the "
            "strongest one first.",
            "Flights: Flightradar24 and FlightAware give live and "
            "historical positions by flight or tail number; ADS-B exchange "
            "data (adsb.fi / adsbexchange) covers aircraft that ask the "
            "commercial trackers to hide them. GPSJam maps GPS interference "
            "days, which explains gaps in a track.",
            "Vessels: MarineTraffic and VesselFinder give live and "
            "historical AIS positions; Equasis adds ownership and safety "
            "records (free registration). Global Fishing Watch covers "
            "fishing-vessel effort.",
            "Correlate a track with the case timeline (`use timeline`): a "
            "position report is an event row like any other, with a source.",
            "Capture the mode, the identifier you tracked, the observation "
            "time (UTC), the position or route, and the source — a track "
            "without its observation time is an anecdote.",
        ),
        handoffs=(
            "https://www.flightradar24.com/{query}",
            "https://www.flightaware.com/live/flight/{query}",
            "https://www.marinetraffic.com/en/ais/index/search/all?keyword={query}",
            "https://www.vesselfinder.com/?search={query}",
        ),
        capture_fields=("mode", "identifier", "observation_time_utc", "position", "source", "notes"),
        tools=(),
        related=("maps-geolocation", "web-archive"),
        tool_references=(
            toolkit_tool("Flightradar24", "flightradar24", "historical data beyond 7 days needs a paid tier"),
            toolkit_tool("FlightAware", "flightaware", "strong on US flight history; free"),
            toolkit_tool("GPSJam", "gpsjam", "GPS interference maps — explains track gaps"),
            toolkit_tool("MarineTraffic", "marinetraffic", "AIS positions; history depth varies by tier"),
            toolkit_tool("VesselFinder", "vesselfinder", "free AIS live positions"),
            toolkit_tool("Equasis", "equasis", "vessel ownership/safety records; free registration"),
            toolkit_tool("Global Fishing Watch", "global-fishing-watch-map", "fishing-vessel activity from AIS + satellite"),
            toolkit_category("transport"),
        ),
    ),
    Method(
        id="vehicle-records",
        name="Vehicle and plate records",
        tier=tiers.YELLOW,
        category="transport",
        summary=(
            "Check a plate or VIN against lawful public sources: theft and "
            "salvage records, VIN decoding, plate-format reference."
        ),
        steps=(
            "Decode the VIN first (NHTSA vPIC handoff): make, model, year, "
            "plant, and engine — free, authoritative, and a fast way to "
            "catch a cloned or swapped plate when the decode contradicts "
            "the observed vehicle.",
            "In the US, NICB VINCheck reports theft and total-loss/salvage "
            "records from insurers — lawful, free, and designed for the "
            "public.",
            "Plate lookups that name the registered *owner* are restricted "
            "nearly everywhere (DPPA in the US, equivalents elsewhere): use "
            "only channels your authorization covers, and record the lawful "
            "basis in the notes.",
            "Confirm the plate format is real for its jurisdiction (License "
            "Plate Maps reference) — a malformed plate is itself a finding.",
            "Tie the result to the transportation profile: `vehicle set "
            "<id> ...` in the console, or `chr0nix case entity set vehicle`, "
            "keeps the registry current with what the records showed.",
            "Capture plate, VIN, jurisdiction, the record type, the detail, "
            "and the source for each fact.",
        ),
        handoffs=(
            "https://vpic.nhtsa.dot.gov/decoder/Decoder?VIN={query}",
            "https://www.nicb.org/vincheck",
        ),
        capture_fields=("plate", "vin", "jurisdiction", "record_type", "detail", "source", "notes"),
        tools=(),
        related=("transport-tracking",),
        tool_references=(
            toolkit_tool("License Plate Maps", "license-plate-maps", "plate formats by country — validity checks, not owner data"),
            toolkit_category("transport"),
        ),
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


def parse_capture_pairs(method: Method, tokens: list[str]) -> list[tuple[str, str]]:
    """Validate ``field=value`` tokens against a method's capture vocabulary.

    Shared by the console's ``capture`` command and the guide CLI so a
    structured finding is validated identically no matter which front end
    recorded it. At least one pair is required; unknown fields fail with
    the method's full vocabulary listed.
    """
    if not tokens:
        raise SuiteError(
            f"capture needs at least one <field>=<value> pair for {method.id} "
            f"(fields: {', '.join(method.capture_fields)})"
        )
    pairs: list[tuple[str, str]] = []
    for token in tokens:
        field, separator, value = token.partition("=")
        if not separator:
            raise SuiteError(
                f"expected <field>=<value>, got {token!r} "
                f"(fields: {', '.join(method.capture_fields)})"
            )
        if field not in method.capture_fields:
            raise SuiteError(
                f"unknown field {field!r} for {method.id}; "
                f"capture fields: {', '.join(method.capture_fields)}"
            )
        pairs.append((field, value.strip()))
    return pairs


def capture_detail(method: Method, pairs: list[tuple[str, str]]) -> str:
    """The one-line event detail for a capture: ``method: field=value; ...``."""
    return f"{method.id}: " + "; ".join(f"{field}={value}" for field, value in pairs)


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
    if method.tool_references:
        lines.append("")
        lines.append(
            "Toolkit references (Bellingcat's Online Investigation Toolkit — "
            "printed for your browser, never opened by the suite):"
        )
        for reference in method.tool_references:
            lines.append(f"  {reference.name} — {reference.url}")
            if reference.caveat:
                lines.append(f"    caveat: {reference.caveat}")
    lines.append("")
    lines.append("Capture fields: " + ", ".join(method.capture_fields))
    lines.append(
        f"record findings with: capture {method.id} "
        + " ".join(f"{field}=..." for field in method.capture_fields[:2])
    )
    return "\n".join(lines)
