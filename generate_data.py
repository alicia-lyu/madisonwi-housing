#!/usr/bin/env python3
"""Parse Madison WI commercial construction permits CSV, filter for multi-family
housing projects, geocode addresses, fetch zoning info, and output projects.json."""

import csv
import json
import os
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, datetime

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

CSV_FILE = "01012015-03152026.csv"
OUTPUT_JSON = "projects.json"
OUTPUT_CSV = "projects.csv"
CACHE_FILE = "geocode_cache.json"
ZONING_CSV = "zoning_districts.csv"
GTFS_DIR = "gtfs_tmp"
TRANSIT_JSON = "transit_routes.json"
OUTCOME_OVERRIDES_CSV = "outcome_overrides.csv"
LOW_QUALITY_CSV = "projects_low_quality.csv"

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ZONING_URL = "https://maps.cityofmadison.com/arcgis/rest/services/Planning/Zoning/MapServer/2/query"
USER_AGENT = "MadisonWI-HousingPermits/1.0"

LEGISTAR_BASE = "https://webapi.legistar.com/v1/madison"
LEGISTAR_STREET_SUFFIXES = (
    "Drive", "Street", "Avenue", "Road", "Lane", "Court", "Place", "Boulevard",
    "Parkway", "Way", "Circle", "Trail", "Run", "Terrace", "Walk", "Alley", "Pass",
)
LEGISTAR_ADDR_RE = re.compile(
    r'\bat\s+(\d+\s+\S.+?(?:' + '|'.join(LEGISTAR_STREET_SUFFIXES) + r')\w*)',
    re.I
)
LEGISTAR_REZONE_KEYWORDS = ("change the zoning",)

# ---------------------------------------------------------------------------
# Records to exclude (false positives identified during manual review)
# ---------------------------------------------------------------------------

EXCLUDE_RECORDS = {
    "BLDNCC-2025-18873",  # Convert apartment building TO hotel (removing housing)
    "BLDNCC-2025-15801",  # Garage repair at existing apartment complex
    "BLDNCC-2025-06508",  # Incomplete address (just "DR, Madison WI 53719")
    "BLDNCC-2025-06490",  # Hotel-to-apartment accessibility alteration (4 units)
    "BLDNCC-2017-11036",  # SpringHill Suites hotel in mixed-use building
}

# ---------------------------------------------------------------------------
# Multi-family detection patterns
# ---------------------------------------------------------------------------

MULTI_FAMILY_RE = re.compile(
    r"\d+.?unit|\d+\s+residential\s+unit"
    r"|\d+.?dwelling|apartment|townhouse|townhome|duplex|triplex"
    r"|fourplex|mixed.use|multi.?family|housing|condo",
    re.IGNORECASE,
)

# Patterns that indicate false positives (single-unit condo alterations)
_CONDO_ALTER_RE = re.compile(
    r"alter|remodel|repair|replace|kitchen|bathroom|basement|layout"
    r"|finish|closet|stair|deck|window|door|floor|paint|roof",
    re.IGNORECASE,
)

# Positive indicators that a "condo" or "mixed-use" match is truly residential
_RESIDENTIAL_INDICATOR_RE = re.compile(
    r"\d+.?unit|\d+\s+residential\s+unit|\d+.?dwelling"
    r"|apartment|\bapt\b|new\b.*\bcondo|housing|multi.?family",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Unit count extraction patterns
# ---------------------------------------------------------------------------

UNIT_PATTERNS = [
    re.compile(r"(\d+)[- ]?(?:dwelling )?units?", re.IGNORECASE),
    re.compile(r"(\d+)\s+residential\s+units?", re.IGNORECASE),
    re.compile(r"(\d+)[- ]?dwelling", re.IGNORECASE),
    re.compile(r"(\d+)[- ]?apartments?", re.IGNORECASE),
    re.compile(r"(\d+) unit", re.IGNORECASE),
]

WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
_WORD_PAT = "|".join(WORD_TO_NUM.keys())

WORD_UNIT_PATTERNS = [
    re.compile(rf"({_WORD_PAT})[- ]?(?:dwelling )?units?", re.IGNORECASE),
    re.compile(rf"({_WORD_PAT})\s+(?:new\s+)?residential\s+units?", re.IGNORECASE),
    re.compile(rf"({_WORD_PAT})[- ]?(?:apartment)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Transit service level classification (from Dec 2025 system map)
# ---------------------------------------------------------------------------

FREQUENT_ROUTES = {"A", "B", "C", "D", "80"}
STANDARD_ROUTES = {"E", "F", "G", "H", "J", "O", "P", "R", "28", "38"}
PEAK_ROUTES = {"55", "65", "75"}
SUPPLEMENTAL_ROUTES = {"60", "61", "62", "63", "64"}

# Cutoff for classifying old "Issued" permits as stale (did not proceed)
STALE_ISSUED_CUTOFF = "2024-01-01"

# ---------------------------------------------------------------------------
# CSV output field order
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "record_number", "date", "address", "status", "description",
    "project_name", "units", "zoning", "lat", "lng", "use_type", "housing_type",
    "outcome",
]


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


# ---------------------------------------------------------------------------
# CSV parsing and filtering
# ---------------------------------------------------------------------------

def is_likely_multifamily(desc):
    """Post-filter to weed out false positives from the broad regex match."""
    dl = desc.lower()

    # Exclude warehousing
    if "warehous" in dl:
        return False

    # Condo alterations: matched only via "condo" keyword, looks like single-unit work
    if re.search(r"\bcondo", dl, re.IGNORECASE):
        if not _RESIDENTIAL_INDICATOR_RE.search(desc):
            if _CONDO_ALTER_RE.search(desc):
                return False

    # Mixed-use without residential evidence (shell buildings, hotels, tenant buildouts)
    if re.search(r"mixed.?use", dl):
        if not _RESIDENTIAL_INDICATOR_RE.search(desc):
            return False

    return True


def parse_csv():
    """Read CSV and filter for multi-family housing rows."""
    projects = []
    with open(CSV_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record = row.get("Record Number", "").strip()
            desc = row.get("Description", "") or ""

            if record in EXCLUDE_RECORDS:
                continue
            if not MULTI_FAMILY_RE.search(desc):
                continue
            if not is_likely_multifamily(desc):
                continue

            raw_date = row.get("Date", "").strip()
            try:
                iso_date = datetime.strptime(raw_date, "%m/%d/%Y").strftime("%Y-%m-%d")
            except ValueError:
                iso_date = raw_date
            projects.append({
                "record_number": record,
                "date": iso_date,
                "address": row.get("Address", "").strip(),
                "status": row.get("Status", "").strip(),
                "description": desc.strip(),
                "project_name": (row.get("Project Name", "") or "").strip(),
            })
    return projects


# ---------------------------------------------------------------------------
# Unit and housing type extraction
# ---------------------------------------------------------------------------

def extract_units(description):
    """Extract unit count from description text."""
    for pattern in UNIT_PATTERNS:
        m = pattern.search(description)
        if m:
            count = int(m.group(1))
            if count >= 2:
                return count
    # Fallback: spelled-out numbers ("two apartment units")
    for pattern in WORD_UNIT_PATTERNS:
        m = pattern.search(description)
        if m:
            count = WORD_TO_NUM.get(m.group(1).lower())
            if count and count >= 2:
                return count
    return None


def extract_stories(description):
    """Extract story count from description text."""
    m = re.search(r"(\d+)\s*stor(?:y|ies)", description, re.IGNORECASE)
    return int(m.group(1)) if m else None


def classify_housing_type(description, units):
    """Classify housing type using Missing Middle Housing typology.

    Categories (from Daniel Parolek's Missing Middle framework):
    - Duplex/Triplex: 2-3 unit buildings
    - Townhouse: attached rowhouses with individual entries
    - Multiplex: small 4-8 unit buildings
    - Mixed-Use: ground-floor commercial + upper residential
    - Mid-Rise: multi-story apartment, typically 4-7 stories
    - High-Rise: 8+ story apartment tower
    """
    desc = description.lower()
    stories = extract_stories(description)

    # Townhouse/rowhouse — explicit in description
    if re.search(r"townho(?:me|use)|row\s?house", desc):
        return "Townhouse"

    # Mixed-use — has commercial/retail component
    if re.search(r"mixed.?use|multiuse|shell commercial|commercial space", desc):
        if stories and stories >= 8:
            return "High-Rise Mixed-Use"
        return "Mid-Rise Mixed-Use"

    # By unit count and stories
    if units and units <= 3:
        return "Duplex/Triplex"

    if units and units <= 8:
        return "Multiplex"

    if stories and stories >= 8:
        return "High-Rise"

    return "Mid-Rise"


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

def clean_address(address):
    """Clean address for geocoding — remove unit numbers and 'United States'."""
    address = re.sub(r",?\s*United States\s*$", "", address)
    address = re.sub(r",\s*\d+,", ",", address)
    return address.strip()


def _api_request(url):
    """Make an HTTP GET request with our User-Agent. Returns parsed JSON or None."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError):
        return None


def geocode(address, cache):
    """Geocode an address using Nominatim. Returns (lat, lng) or (None, None)."""
    cache_key = f"geo:{address}"
    if cache_key in cache:
        cached = cache[cache_key]
        return cached.get("lat"), cached.get("lng")

    cleaned = clean_address(address)
    params = urllib.parse.urlencode({
        "q": cleaned,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    })
    url = f"{NOMINATIM_URL}?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    data = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                wait = (attempt + 1) * 5
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            print(f"  Geocode error for {cleaned}: {e}")
            cache[cache_key] = {"lat": None, "lng": None}
            return None, None
        except (urllib.error.URLError, OSError) as e:
            print(f"  Geocode error for {cleaned}: {e}")
            cache[cache_key] = {"lat": None, "lng": None}
            return None, None

    if data:
        lat = float(data[0]["lat"])
        lng = float(data[0]["lon"])
        cache[cache_key] = {"lat": lat, "lng": lng}
        print(f"  Geocoded: {cleaned} -> ({lat}, {lng})")
        return lat, lng
    else:
        print(f"  No results for: {cleaned}")
        cache[cache_key] = {"lat": None, "lng": None}
        return None, None


# ---------------------------------------------------------------------------
# Zoning lookup
# ---------------------------------------------------------------------------

def get_zoning(lat, lng, cache):
    """Query Madison ArcGIS zoning layer for a point. Returns zoning code or None."""
    if lat is None or lng is None:
        return None

    cache_key = f"zone:{lat},{lng}"
    if cache_key in cache:
        return cache[cache_key]

    params = urllib.parse.urlencode({
        "geometry": f"{lng},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "ZONING_CODE",
        "f": "json",
    })
    url = f"{ZONING_URL}?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError) as e:
        print(f"  Zoning error for ({lat}, {lng}): {e}")
        cache[cache_key] = None
        return None

    features = data.get("features", [])
    if features:
        zoning = features[0].get("attributes", {}).get("ZONING_CODE")
        cache[cache_key] = zoning
        print(f"  Zoning: ({lat:.4f}, {lng:.4f}) -> {zoning}")
        return zoning
    else:
        print(f"  No zoning data for ({lat:.4f}, {lng:.4f})")
        cache[cache_key] = None
        return None


# ---------------------------------------------------------------------------
# Zoning rules (permitted vs conditional use classification)
# ---------------------------------------------------------------------------

def parse_unit_ranges(text, building_type):
    """Parse semi-structured zoning text to extract (min, max) unit ranges for a type.

    building_type: "multifamily" or "townhom" (matches townhome/townhouse).
    Returns list of (min, max) tuples. max=float('inf') for unbounded ranges.
    """
    if not text:
        return []
    ranges = []
    INF = float("inf")
    for clause in text.split(","):
        clause = clause.strip()
        if building_type.lower() not in clause.lower():
            continue
        # "4-24 unit multifamily" -> (4, 24)
        m = re.search(r"(\d+)\s*-\s*(\d+)[\s-]+(?:unit[\s-]+)?" + building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)), int(m.group(2))))
            continue
        # ">24 unit multifamily" -> (25, inf)
        m = re.search(r">\s*(\d+)\s+(?:unit\s+)?" + building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)) + 1, INF))
            continue
        # "4 or > multifamily" -> (4, inf)
        m = re.search(r"(\d+)\s+or\s*>\s*(?:unit\s+)?" + building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)), INF))
            continue
        # "4 unit multifamily" (single number) -> (4, 4)
        m = re.search(r"(\d+)\s+(?:unit\s+)?" + building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)), int(m.group(1))))
            continue
        # "Multifamily building" (no number) -> (1, inf)
        m = re.search(building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((1, INF))
    return ranges


def parse_small_building_ranges(text):
    """Parse 'X-Y unit building' and 'X unit building' patterns.

    Only matches clauses like '2-3-unit building' or '2 unit building',
    NOT 'Single family building' or 'Mixed-use building'.
    """
    if not text:
        return []
    ranges = []
    for clause in text.split(","):
        clause = clause.strip()
        # "2-3-unit building" or "2-3 unit building"
        m = re.search(r"(\d+)\s*-\s*(\d+)[\s-]+unit[\s-]+building", clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)), int(m.group(2))))
            continue
        # "2 unit building"
        m = re.search(r"(\d+)[\s-]+unit[\s-]+building", clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)), int(m.group(1))))
    return ranges


def load_zoning_rules():
    """Read zoning_districts.csv and build classification rules.

    Returns dict keyed by zoning code with parsed permitted/conditional
    ranges for both multifamily and townhouse types.
    """
    rules = {}
    with open(ZONING_CSV, newline="") as f:
        for row in csv.DictReader(f):
            code = row["code"].strip()
            permitted = row.get("residential_permitted", "") or ""
            conditional = row.get("residential_conditional", "") or ""
            rules[code] = {
                "permitted_mf": parse_unit_ranges(permitted, "multifamily"),
                "permitted_th": parse_unit_ranges(permitted, "townhom"),
                "permitted_bldg": parse_small_building_ranges(permitted),
                "conditional_mf": parse_unit_ranges(conditional, "multifamily"),
                "conditional_th": parse_unit_ranges(conditional, "townhom"),
                "conditional_bldg": parse_small_building_ranges(conditional),
            }
    return rules


def _in_any_range(ranges, count):
    """Check whether count falls within any (min, max) range."""
    return any(lo <= count <= hi for lo, hi in ranges)


def classify_use(zoning, units, description, rules):
    """Classify a project as PERMITTED, CONDITIONAL, VARIES, REZONED, or UNKNOWN."""
    if not zoning or not units:
        return "UNKNOWN"
    if zoning.startswith("PD"):
        return "VARIES"

    rule = rules.get(zoning)
    if not rule:
        return "UNKNOWN"

    is_townhouse = bool(re.search(r"townho(?:me|use)", description, re.IGNORECASE))

    if is_townhouse:
        if _in_any_range(rule["permitted_th"], units):
            return "PERMITTED"
        if _in_any_range(rule["conditional_th"], units):
            return "CONDITIONAL"

    # Check multifamily ranges (also fallback for townhouses not matched above)
    if _in_any_range(rule["permitted_mf"], units):
        return "PERMITTED"
    if _in_any_range(rule["conditional_mf"], units):
        return "CONDITIONAL"

    # Check generic "X unit building" ranges (e.g. "2-3 unit building")
    if _in_any_range(rule["permitted_bldg"], units):
        return "PERMITTED"
    if _in_any_range(rule["conditional_bldg"], units):
        return "CONDITIONAL"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# GTFS transit processing
# ---------------------------------------------------------------------------

def _route_service_style(route_name):
    """Return (weight, dash_pattern) based on service frequency tier."""
    if route_name in FREQUENT_ROUTES:
        return 4, None
    if route_name in STANDARD_ROUTES:
        return 3, None
    if route_name in PEAK_ROUTES:
        return 2, "8 6"
    if route_name in SUPPLEMENTAL_ROUTES:
        return 2, "4 4"
    return 2, None


def _load_gtfs_routes():
    """Load route info from GTFS routes.txt."""
    route_info = {}
    with open(os.path.join(GTFS_DIR, "routes.txt"), newline="") as f:
        for r in csv.DictReader(f):
            route_info[r["route_id"]] = {
                "name": r["route_short_name"],
                "color": "#" + r["route_color"],
                "long_name": r["route_long_name"],
            }
    return route_info


def _load_gtfs_trip_shapes():
    """Map route_id -> set of shape_ids via trips.txt."""
    route_shapes = {}
    with open(os.path.join(GTFS_DIR, "trips.txt"), newline="") as f:
        for r in csv.DictReader(f):
            route_shapes.setdefault(r["route_id"], set()).add(r["shape_id"])
    return route_shapes


def _load_gtfs_shapes():
    """Load all shape points from shapes.txt, sorted by sequence."""
    shapes = {}
    with open(os.path.join(GTFS_DIR, "shapes.txt"), newline="") as f:
        for r in csv.DictReader(f):
            sid = r["shape_id"]
            shapes.setdefault(sid, []).append((
                int(r["shape_pt_sequence"]),
                float(r["shape_pt_lat"]),
                float(r["shape_pt_lon"]),
            ))
    for sid in shapes:
        shapes[sid].sort(key=lambda x: x[0])
    return shapes


def _simplify_shape(pts):
    """Downsample shape points to ~200 and round coordinates."""
    step = max(1, len(pts) // 200)
    coords = [[round(p[1], 5), round(p[2], 5)] for p in pts[::step]]
    last = [round(pts[-1][1], 5), round(pts[-1][2], 5)]
    if coords[-1] != last:
        coords.append(last)
    return coords


def process_gtfs():
    """Process GTFS data into transit route lines with colors and service levels."""
    gtfs_files = [
        os.path.join(GTFS_DIR, f) for f in ("routes.txt", "trips.txt", "shapes.txt")
    ]
    if not all(os.path.exists(f) for f in gtfs_files):
        print("  GTFS files not found, skipping transit overlay")
        return None

    route_info = _load_gtfs_routes()
    route_shapes = _load_gtfs_trip_shapes()
    shapes = _load_gtfs_shapes()

    # For each route, pick the two longest shapes (one per direction typically)
    transit_routes = []
    for rid, info in sorted(route_info.items(), key=lambda x: x[1]["name"]):
        sids = route_shapes.get(rid, set())
        if not sids:
            continue

        # Pick shapes with most points (covers full route)
        shape_lengths = [(sid, len(shapes.get(sid, []))) for sid in sids]
        shape_lengths.sort(key=lambda x: -x[1])

        # Take up to 2 longest shapes (typically 2 directions)
        seen_coords = set()
        for sid, _ in shape_lengths[:2]:
            pts = shapes.get(sid, [])
            if not pts:
                continue

            coords = _simplify_shape(pts)

            # Skip near-duplicate shapes (same start/end points)
            key = (coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])
            if key in seen_coords:
                continue
            seen_coords.add(key)

            name = info["name"]
            weight, dash = _route_service_style(name)

            transit_routes.append({
                "name": name,
                "color": info["color"],
                "weight": weight,
                "dash": dash,
                "coords": coords,
            })

    return transit_routes


# ---------------------------------------------------------------------------
# Pipeline steps (called from main)
# ---------------------------------------------------------------------------

def _step_parse(projects):
    """Step 1 log: show project count."""
    print(f"  Found {len(projects)} multi-family housing projects\n")


def _step_extract_units(projects):
    """Step 2: extract unit counts and log each project."""
    print("Step 2: Extracting unit counts...")
    for p in projects:
        p["units"] = extract_units(p["description"])
        units_str = str(p["units"]) if p["units"] else "?"
        print(f"  {p['record_number']}: {units_str} units — {p['description'][:80]}")
    print()


def _step_classify_types(projects):
    """Step 2b: classify housing types and print summary."""
    print("Step 2b: Classifying housing type...")
    type_counts = {}
    for p in projects:
        p["housing_type"] = classify_housing_type(p["description"], p["units"])
        type_counts[p["housing_type"]] = type_counts.get(p["housing_type"], 0) + 1
        print(f"  {p['record_number']}: {p['housing_type']}")
    for ht, count in sorted(type_counts.items()):
        print(f"  {ht}: {count}")
    print()


def _step_geocode(projects, cache):
    """Step 3: geocode all project addresses."""
    print("Step 3: Geocoding addresses...")
    geocoded_count = 0
    for p in projects:
        cache_key = f"geo:{p['address']}"
        was_cached = cache_key in cache
        lat, lng = geocode(p["address"], cache)
        p["lat"] = lat
        p["lng"] = lng
        if lat is not None:
            geocoded_count += 1
        save_cache(cache)
        # Respect Nominatim rate limit: 1 req/sec (only sleep if we made a request)
        if not was_cached:
            time.sleep(1.5)
    print(f"  Geocoded {geocoded_count}/{len(projects)} addresses\n")


def _step_fetch_zoning(projects, cache):
    """Step 4: fetch zoning district for each geocoded project."""
    print("Step 4: Fetching zoning districts...")
    zoned_count = 0
    for p in projects:
        p["zoning"] = get_zoning(p["lat"], p["lng"], cache)
        if p["zoning"]:
            zoned_count += 1
        save_cache(cache)
    print(f"  Got zoning for {zoned_count}/{len(projects)} projects\n")


def _step_classify_use(projects):
    """Step 5: classify each project as permitted/conditional/etc."""
    print("Step 5: Classifying permitted vs conditional use...")
    zoning_rules = load_zoning_rules()
    use_counts = {}
    for p in projects:
        p["use_type"] = classify_use(
            p["zoning"], p["units"], p["description"], zoning_rules
        )
        use_counts[p["use_type"]] = use_counts.get(p["use_type"], 0) + 1
        print(f"  {p['record_number']}: {p['zoning'] or '?'} / "
              f"{p['units'] or '?'} units -> {p['use_type']}")
    for use_type, count in sorted(use_counts.items()):
        print(f"  {use_type}: {count}")
    print()


def _normalize_addr(addr):
    """Normalize an address string for fuzzy matching against Legistar titles."""
    addr = addr.lower()
    addr = re.sub(r'\b\d{5}\b.*', '', addr)          # strip zip code and everything after
    addr = re.sub(r'\bunited states\b', '', addr)
    addr = re.sub(r'\b(madison|wi|wisconsin)\b', '', addr)
    addr = re.sub(r'\s+', ' ', addr).strip().rstrip(',.')
    for abbr, full in [
        (r'\bdr\b', 'drive'), (r'\bst\b', 'street'), (r'\bave\b', 'avenue'),
        (r'\bblvd\b', 'boulevard'), (r'\brd\b', 'road'), (r'\bln\b', 'lane'),
        (r'\bct\b', 'court'), (r'\bpl\b', 'place'), (r'\bpkwy\b', 'parkway'),
    ]:
        addr = re.sub(abbr, full, addr)
    return addr


def _fetch_legistar_matters(type_name, cache):
    """Fetch all Legistar matters of a given type, using cache to avoid re-fetching."""
    cache_key = f"legistar:{type_name}"
    if cache_key in cache:
        return cache[cache_key]

    matters = []
    skip = 0
    while True:
        params = urllib.parse.urlencode({
            "$filter": f"MatterTypeName eq '{type_name}'",
            "$top": 1000,
            "$skip": skip,
            "$select": "MatterTitle,MatterStatusName,MatterIntroDate,MatterPassedDate",
        })
        url = f"{LEGISTAR_BASE}/matters?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                page = json.loads(resp.read().decode())
        except Exception as e:
            print(f"  Legistar fetch error ({type_name}, skip={skip}): {e}")
            break
        if not page:
            break
        for m in page:
            matters.append({
                "title": m.get("MatterTitle") or "",
                "status": m.get("MatterStatusName") or "",
                "intro": m.get("MatterIntroDate") or "",
                "passed": m.get("MatterPassedDate") or "",
            })
        skip += len(page)
        if len(page) < 1000:
            break

    cache[cache_key] = matters
    return matters


def _build_legistar_index(matters):
    """Build a normalized-address -> matter dict from Legistar matter list."""
    index = {}
    matched = 0
    for m in matters:
        hit = LEGISTAR_ADDR_RE.search(m["title"])
        if hit:
            norm = _normalize_addr(hit.group(1))
            index[norm] = m
            matched += 1
    print(f"  Address index: {matched}/{len(matters)} titles had extractable addresses")
    return index


def _step_legistar_classify(projects, cache):
    """Step 5c: override use_type using authoritative Legistar CU / rezoning records."""
    print("Step 5c: Fetching Legistar conditional use and rezoning records...")

    cu_matters = _fetch_legistar_matters("Conditional Use", cache)
    print(f"  Conditional Use matters: {len(cu_matters)}")
    cu_index = _build_legistar_index(cu_matters)

    ord_matters = _fetch_legistar_matters("Ordinance", cache)
    rezone_matters = [m for m in ord_matters
                      if any(kw in m["title"].lower() for kw in LEGISTAR_REZONE_KEYWORDS)]
    print(f"  Rezoning ordinances: {len(rezone_matters)} of {len(ord_matters)} ordinances")
    rezone_index = _build_legistar_index(rezone_matters)

    save_cache(cache)

    overrides = 0
    for p in projects:
        if p.get("use_type") == "VARIES":
            continue
        norm = _normalize_addr(p.get("address", ""))
        if norm in cu_index:
            p["use_type"] = "CONDITIONAL"
            overrides += 1
        elif norm in rezone_index:
            p["use_type"] = "REZONED"
            overrides += 1
    print(f"  Legistar overrides applied: {overrides}\n")


def classify_outcome(status, date_str):
    """Classify project outcome based on permit status and date.

    BUILT: Certificate of Occupancy issued (Closed, Inspections Complete, Ready for CoO)
    DID_NOT_PROCEED: Rejected, or Issued but stale (before cutoff date)
    ACTIVE: Currently in progress (Issued recent, In Process, or fallback)
    """
    if status in ("Closed", "Inspections Complete", "Ready for CoO"):
        return "BUILT"
    if status == "Rejected":
        return "DID_NOT_PROCEED"
    if status == "Issued" and date_str < STALE_ISSUED_CUTOFF:
        return "DID_NOT_PROCEED"
    return "ACTIVE"


def load_outcome_overrides():
    """Load manual outcome overrides from CSV. Returns dict of record_number -> outcome."""
    if not os.path.exists(OUTCOME_OVERRIDES_CSV):
        return {}
    overrides = {}
    with open(OUTCOME_OVERRIDES_CSV, newline="") as f:
        for row in csv.DictReader(f):
            overrides[row["record_number"].strip()] = row["outcome"].strip()
    return overrides


def _step_classify_outcome(projects):
    """Step 5b: classify project outcome (built / active / did not proceed)."""
    print("Step 5b: Classifying project outcomes...")
    overrides = load_outcome_overrides()
    override_count = 0
    outcome_counts = {}
    for p in projects:
        rec = p["record_number"]
        if rec in overrides:
            p["outcome"] = overrides[rec]
            override_count += 1
            print(f"  {rec}: {p['outcome']} (manual override)")
        else:
            p["outcome"] = classify_outcome(p["status"], p["date"])
    for p in projects:
        outcome_counts[p["outcome"]] = outcome_counts.get(p["outcome"], 0) + 1
    for outcome, count in sorted(outcome_counts.items()):
        print(f"  {outcome}: {count}")
    if override_count:
        print(f"  ({override_count} manual override(s) applied)")
    print()


def _step_transit():
    """Step 6: process GTFS transit routes."""
    print("Step 6: Processing GTFS transit routes...")
    transit_routes = process_gtfs()
    if transit_routes:
        with open(TRANSIT_JSON, "w") as f:
            json.dump(transit_routes, f)
        total_pts = sum(len(r["coords"]) for r in transit_routes)
        print(f"  Wrote {len(transit_routes)} route shapes ({total_pts} points) "
              f"to {TRANSIT_JSON}\n")
    else:
        print("  No transit data generated\n")


def _step_filter_low_quality(projects):
    """Step 7: separate 0-unit records into low-quality store; return only unit-bearing projects."""
    low_quality = [p for p in projects if not p["units"]]
    main = [p for p in projects if p["units"]]
    if low_quality:
        with open(LOW_QUALITY_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(low_quality)
        print(f"Step 7: Segregated {len(low_quality)} 0-unit records → {LOW_QUALITY_CSV}")
        print(f"  Main dataset: {len(main)} records with unit counts\n")
    return main


def _write_outputs(projects):
    """Write projects.json and projects.csv, print summary."""
    output = {
        "generated": str(date.today()),
        "projects": projects,
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(projects)

    print(f"Done! Wrote {len(projects)} projects to {OUTPUT_JSON} and {OUTPUT_CSV}")

    has_coords = sum(1 for p in projects if p["lat"] is not None)
    has_units = sum(1 for p in projects if p["units"] is not None)
    has_zoning = sum(1 for p in projects if p["zoning"])
    print(f"  With coordinates: {has_coords}")
    print(f"  With unit count:  {has_units}")
    print(f"  With zoning:      {has_zoning}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cache = load_cache()

    print("Step 1: Parsing CSV and filtering multi-family projects...")
    projects = parse_csv()
    _step_parse(projects)

    _step_extract_units(projects)
    _step_classify_types(projects)
    _step_geocode(projects, cache)
    _step_fetch_zoning(projects, cache)
    _step_classify_use(projects)
    _step_legistar_classify(projects, cache)
    _step_classify_outcome(projects)
    _step_transit()
    projects = _step_filter_low_quality(projects)
    _write_outputs(projects)


if __name__ == "__main__":
    main()
