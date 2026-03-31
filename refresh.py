#!/usr/bin/env python3
"""Check data freshness and re-run the pipeline when sources are stale.

Run manually or let generate_site.py trigger it automatically in the
background. Only does work when at least one source has exceeded its TTL.

Intervals:
  Nominatim geocoding retries  30d  (new streets appear ~monthly)
  Legistar CU / rezoning data   7d  (Plan Commission meets bi-weekly)
  MPO bike route data          90d  (infrastructure changes are slow)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

CACHE_FILE = "geocode_cache.json"

INTERVALS = {
    "meta:geocode_retry":            (30,  "Nominatim geocoding retries"),
    "meta:legistar:Conditional Use": (7,   "Legistar CU records"),
    "meta:legistar:Ordinance":       (7,   "Legistar rezoning ordinances"),
    "meta:bike_routes":              (90,  "MPO bike route data"),
}


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def age_str(ts):
    if not ts:
        return "never"
    age = datetime.now(timezone.utc) - datetime.fromisoformat(ts)
    return f"{age.days}d ago"


def main():
    cache = load_cache()
    now = datetime.now(timezone.utc)
    any_stale = False

    print(f"{'Source':<35} {'Last refresh':<15} {'Interval':<12} Status")
    print("-" * 72)
    for meta_key, (days, label) in INTERVALS.items():
        ts = cache.get(meta_key)
        stale = not ts or now - datetime.fromisoformat(ts) > timedelta(days=days)
        status = "STALE" if stale else "ok"
        print(f"{label:<35} {age_str(ts):<15} every {days}d{'':<5} {status}")
        if stale:
            any_stale = True
    print()

    if not any_stale:
        print("All sources fresh — nothing to do.")
        return

    print("Running generate_data.py...")
    subprocess.run([sys.executable, "generate_data.py"], check=True)
    print("\nRunning generate_site.py...")
    env = os.environ.copy()
    env["REFRESH_RUNNING"] = "1"  # prevent generate_site.py from re-spawning us
    subprocess.run([sys.executable, "generate_site.py"], env=env, check=True)
    print("\nRefresh complete.")


if __name__ == "__main__":
    main()
