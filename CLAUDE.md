# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Interactive Leaflet map of multi-family housing construction permits in Madison, WI (2025). The site visualizes projects as colored markers on a map, with zoning district colors, permitted/conditional use classification, and transit route overlays.

## Two-Stage Build Pipeline

The site is generated in two steps — data processing then HTML generation:

1. **`python generate_data.py`** — Parses the raw permits CSV (`RecordList20260314-2.csv`), filters for multi-family housing, geocodes addresses via Nominatim, fetches zoning from Madison's ArcGIS API, classifies permitted vs conditional use, processes GTFS transit data, and outputs `projects.json`, `projects.csv`, and `transit_routes.json`. Uses `geocode_cache.json` to avoid re-hitting APIs. Slow due to API rate limits — only re-run when input data changes.

2. **`python generate_site.py`** — Reads `projects.csv` and `transit_routes.json`, computes all marker properties (colors, sizes, popups) in Python, and writes a self-contained `index.html`. The generated HTML has minimal JS — just Leaflet map init, marker placement, and zoom scaling. Re-run this after any visual/UI changes.

Both scripts use only Python stdlib (no pip dependencies).

## Key Data Flow

```
RecordList CSV → generate_data.py → projects.csv + transit_routes.json
                                          ↓
zoning_districts.csv + style.css → generate_site.py → index.html
```

- `zoning_districts.csv` — Hand-curated reference of all Madison zoning codes with permitted/conditional residential use rules, max stories, and density. Used by both scripts.
- `geocode_cache.json` — Persisted cache keyed by `geo:{address}` and `zone:{lat,lng}`. Checked into .gitignore.
- `transit_routes.json` — Pre-processed GTFS route shapes with colors and service-level styling.
- GTFS source files live in `gtfs_tmp/` (extracted from `mmt_gtfs.zip`).

## Architecture Notes

- **Marker shapes encode use type**: circles = Permitted, squares = Conditional/Rezoned/PD/Unknown. Marker color = zoning district color. Marker size = log-scaled unit count.
- **Zoning classification** (`classify_use`): Matches project unit count against parsed ranges from `zoning_districts.csv`. PD zones always return VARIES. Falls back through townhouse → multifamily → generic building ranges.
- **Housing type taxonomy** follows Missing Middle Housing typology: Duplex/Triplex, Townhouse, Multiplex, Mid-Rise, High-Rise, with Mixed-Use variants.
- **Transit route styling**: Line weight/dash pattern reflects service level (Frequent > Standard > Peak > Supplemental), using route colors from GTFS data.
- All HTML generation uses Python f-strings with `html.escape()` — no template engine.
- `EXCLUDE_RECORDS` in `generate_data.py` lists manually-identified false positives to skip.

## .gitignore

JSON, CSV, PDF, HTML, TXT, and ZIP files are all gitignored. Only `.py`, `.css`, and `.md` files are tracked.
