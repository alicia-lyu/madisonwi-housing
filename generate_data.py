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
        "project_name", "units", "zoning", "lat", "lng",
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
