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
from datetime import date

CSV_FILE = "RecordList20260314-2.csv"
OUTPUT_JSON = "projects.json"
OUTPUT_CSV = "projects.csv"
CACHE_FILE = "geocode_cache.json"

# Records to exclude (false positives identified during manual review)
EXCLUDE_RECORDS = {
    "BLDNCC-2025-18873",  # Convert apartment building TO hotel (removing housing)
    "BLDNCC-2025-15946",  # Single condo layout alteration
    "BLDNCC-2025-15801",  # Garage repair at existing apartment complex
    "BLDNCC-2025-12728",  # "warehousing" false positive on "housing" regex
    "BLDNCC-2025-06508",  # Incomplete address (just "DR, Madison WI 53719")
    "BLDNCC-2025-06490",  # Hotel-to-apartment accessibility alteration (4 units)
}

# Regex to identify multi-family housing projects
MULTI_FAMILY_RE = re.compile(
    r"\d+.?unit|\d+.?dwelling|apartment|townhouse|townhome|duplex|triplex"
    r"|fourplex|mixed.use|multi.?family|housing|condo",
    re.IGNORECASE,
)

# Regex patterns to extract unit counts
UNIT_PATTERNS = [
    re.compile(r"(\d+)[- ]?(?:dwelling )?units?", re.IGNORECASE),
    re.compile(r"(\d+)[- ]?dwelling", re.IGNORECASE),
    re.compile(r"(\d+)[- ]?apartments?", re.IGNORECASE),
    re.compile(r"(\d+) unit", re.IGNORECASE),
]

ZONING_CSV = "zoning_districts.csv"
GTFS_DIR = "gtfs_tmp"
TRANSIT_JSON = "transit_routes.json"

# Service level classification for line weight/style (from Dec 2025 system map)
FREQUENT_ROUTES = {"A", "B", "C", "D", "F"}
STANDARD_ROUTES = {"E", "G", "H", "J", "O", "P", "R", "28", "38", "80"}
PEAK_ROUTES = {"55", "65", "75"}
SUPPLEMENTAL_ROUTES = {"60", "61", "62", "63", "64"}

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ZONING_URL = "https://maps.cityofmadison.com/arcgis/rest/services/Planning/Zoning/MapServer/2/query"
USER_AGENT = "MadisonWI-HousingPermits/1.0"


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


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

            projects.append({
                "record_number": record,
                "date": row.get("Date", "").strip(),
                "address": row.get("Address", "").strip(),
                "status": row.get("Status", "").strip(),
                "description": desc.strip(),
                "project_name": (row.get("Project Name", "") or "").strip(),
            })
    return projects


def extract_units(description):
    """Extract unit count from description text."""
    for pattern in UNIT_PATTERNS:
        m = pattern.search(description)
        if m:
            count = int(m.group(1))
            if count >= 2:
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


def clean_address(address):
    """Clean address for geocoding — remove unit numbers and 'United States'."""
    # Remove ", United States" suffix
    address = re.sub(r",?\s*United States\s*$", "", address)
    # Remove unit/suite numbers like ", 204," or ", 803,"
    address = re.sub(r",\s*\d+,", ",", address)
    return address.strip()


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


def parse_unit_ranges(text, building_type):
    """Parse semi-structured zoning text to extract (min, max) unit ranges for a type.

    building_type: "multifamily" or "townhom" (matches townhome/townhouse).
    Returns list of (min, max) tuples. max=float('inf') for unbounded ranges.
    """
    if not text:
        return []
    ranges = []
    INF = float("inf")
    # Split on commas to get individual clauses
    for clause in text.split(","):
        clause = clause.strip()
        # Check if this clause mentions the building type
        if building_type.lower() not in clause.lower():
            continue
        # Pattern: "4-24 unit multifamily" -> (4, 24)
        m = re.search(r"(\d+)\s*-\s*(\d+)\s+(?:unit\s+)?" + building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)), int(m.group(2))))
            continue
        # Pattern: ">24 unit multifamily" or ">8 unit townhome" -> (25, inf)
        m = re.search(r">\s*(\d+)\s+(?:unit\s+)?" + building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)) + 1, INF))
            continue
        # Pattern: "4 or > multifamily" or "4 or > unit multifamily" -> (4, inf)
        m = re.search(r"(\d+)\s+or\s*>\s*(?:unit\s+)?" + building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)), INF))
            continue
        # Pattern: "4 unit multifamily" (single number) -> (4, 4)
        m = re.search(r"(\d+)\s+(?:unit\s+)?" + building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((int(m.group(1)), int(m.group(1))))
            continue
        # Pattern: "Multifamily building" (no number) -> (1, inf)
        m = re.search(building_type, clause, re.IGNORECASE)
        if m:
            ranges.append((1, INF))
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
                "conditional_mf": parse_unit_ranges(conditional, "multifamily"),
                "conditional_th": parse_unit_ranges(conditional, "townhom"),
            }
    return rules


def classify_use(zoning, units, description, rules):
    """Classify a project as PERMITTED, CONDITIONAL, VARIES, NOT_ALLOWED, or UNKNOWN."""
    if not zoning or not units:
        return "UNKNOWN"
    if zoning.startswith("PD"):
        return "VARIES"

    rule = rules.get(zoning)
    if not rule:
        return "UNKNOWN"

    # Detect townhouse/townhome projects
    is_townhouse = bool(re.search(r"townho(?:me|use)", description, re.IGNORECASE))

    def in_any_range(ranges, count):
        return any(lo <= count <= hi for lo, hi in ranges)

    if is_townhouse:
        if in_any_range(rule["permitted_th"], units):
            return "PERMITTED"
        if in_any_range(rule["conditional_th"], units):
            return "CONDITIONAL"
    # Check multifamily ranges (also fallback for townhouses not matched above)
    if in_any_range(rule["permitted_mf"], units):
        return "PERMITTED"
    if in_any_range(rule["conditional_mf"], units):
        return "CONDITIONAL"

    return "NOT_ALLOWED"


def process_gtfs():
    """Process GTFS data into transit route lines with colors and service levels."""
    routes_file = os.path.join(GTFS_DIR, "routes.txt")
    trips_file = os.path.join(GTFS_DIR, "trips.txt")
    shapes_file = os.path.join(GTFS_DIR, "shapes.txt")

    if not all(os.path.exists(f) for f in [routes_file, trips_file, shapes_file]):
        print("  GTFS files not found, skipping transit overlay")
        return None

    # Load routes
    route_info = {}
    with open(routes_file, newline="") as f:
        for r in csv.DictReader(f):
            route_info[r["route_id"]] = {
                "name": r["route_short_name"],
                "color": "#" + r["route_color"],
                "long_name": r["route_long_name"],
            }

    # Map route_id -> set of shape_ids via trips
    route_shapes = {}
    with open(trips_file, newline="") as f:
        for r in csv.DictReader(f):
            route_shapes.setdefault(r["route_id"], set()).add(r["shape_id"])

    # Load all shape points
    shapes = {}
    with open(shapes_file, newline="") as f:
        for r in csv.DictReader(f):
            sid = r["shape_id"]
            shapes.setdefault(sid, []).append((
                int(r["shape_pt_sequence"]),
                float(r["shape_pt_lat"]),
                float(r["shape_pt_lon"]),
            ))

    # Sort each shape by sequence
    for sid in shapes:
        shapes[sid].sort(key=lambda x: x[0])

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
            # Simplify: take every Nth point to reduce size
            step = max(1, len(pts) // 200)
            coords = [[round(p[1], 5), round(p[2], 5)] for p in pts[::step]]
            # Always include last point
            last = [round(pts[-1][1], 5), round(pts[-1][2], 5)]
            if coords[-1] != last:
                coords.append(last)

            # Skip near-duplicate shapes
            key = (coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])
            if key in seen_coords:
                continue
            seen_coords.add(key)

            # Service level -> weight and dash
            name = info["name"]
            if name in FREQUENT_ROUTES:
                weight, dash = 4, None
            elif name in STANDARD_ROUTES:
                weight, dash = 3, None
            elif name in PEAK_ROUTES:
                weight, dash = 2, "8 6"
            elif name in SUPPLEMENTAL_ROUTES:
                weight, dash = 2, "4 4"
            else:
                weight, dash = 2, None

            transit_routes.append({
                "name": name,
                "color": info["color"],
                "weight": weight,
                "dash": dash,
                "coords": coords,
            })

    return transit_routes


def main():
    cache = load_cache()

    print("Step 1: Parsing CSV and filtering multi-family projects...")
    projects = parse_csv()
    print(f"  Found {len(projects)} multi-family housing projects\n")

    print("Step 2: Extracting unit counts...")
    for p in projects:
        p["units"] = extract_units(p["description"])
        units_str = str(p["units"]) if p["units"] else "?"
        print(f"  {p['record_number']}: {units_str} units — {p['description'][:80]}")
    print()

    print("Step 2b: Classifying housing type...")
    type_counts = {}
    for p in projects:
        p["housing_type"] = classify_housing_type(p["description"], p["units"])
        type_counts[p["housing_type"]] = type_counts.get(p["housing_type"], 0) + 1
        print(f"  {p['record_number']}: {p['housing_type']}")
    for ht, count in sorted(type_counts.items()):
        print(f"  {ht}: {count}")
    print()

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

    print("Step 4: Fetching zoning districts...")
    zoned_count = 0
    for p in projects:
        p["zoning"] = get_zoning(p["lat"], p["lng"], cache)
        if p["zoning"]:
            zoned_count += 1
        save_cache(cache)
    print(f"  Got zoning for {zoned_count}/{len(projects)} projects\n")

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

    # Build JSON output
    output = {
        "generated": str(date.today()),
        "projects": projects,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    # Build CSV output (canonical data source for generate_site.py)
    csv_fields = [
        "record_number", "date", "address", "status", "description",
        "project_name", "units", "zoning", "lat", "lng", "use_type", "housing_type",
    ]
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(projects)

    print(f"Done! Wrote {len(projects)} projects to {OUTPUT_JSON} and {OUTPUT_CSV}")

    # Summary
    has_coords = sum(1 for p in projects if p["lat"] is not None)
    has_units = sum(1 for p in projects if p["units"] is not None)
    has_zoning = sum(1 for p in projects if p["zoning"])
    print(f"  With coordinates: {has_coords}")
    print(f"  With unit count:  {has_units}")
    print(f"  With zoning:      {has_zoning}")


if __name__ == "__main__":
    main()
