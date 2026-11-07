# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Interactive Leaflet map of multi-family housing construction permits in Madison, WI (2025). The site visualizes projects as colored markers on a map, with zoning district colors, permitted/conditional use classification, and transit route overlays.

## Two-Stage Build Pipeline

The site is generated in two steps — data processing then HTML generation:

1. **`python generate_data.py`** — Runs `merge_permits.py` to merge manually-downloaded ELAM permit exports (`MMDDYYYY-MMDDYYYY.csv`, latest end date wins per record) into `permits_merged.csv`, then parses it, filters for multi-family housing, drops renovation-only alterations, geocodes addresses via Nominatim (falling back to Madison's tax parcel layer), fetches zoning from Madison's ArcGIS API, classifies permitted vs conditional use, processes GTFS transit data, and outputs `projects.json`, `projects.csv`, and `transit_routes.json`. Uses `geocode_cache.json` to avoid re-hitting APIs. Slow due to API rate limits — only re-run when input data changes.

2. **`python generate_site.py`** — Reads `projects.csv` and `transit_routes.json`, computes all marker properties (colors, sizes, popups) in Python, and writes a self-contained `index.html`. The generated HTML has minimal JS — just Leaflet map init, marker placement, and zoom scaling. Re-run this after any visual/UI changes.

Both scripts use only Python stdlib (no pip dependencies).

## Key Data Flow

```
ELAM CSVs → merge_permits.py → permits_merged.csv → generate_data.py → projects.csv + transit_routes.json
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
- **Geocoding** (`_step_geocode`): Nominatim first, and results outside the Madison area are rejected. On a miss, `geocode_parcel` checks the city TaxParcels layer: an exact house number gives `parcel`, otherwise the closest number on the same street within `PARCEL_NEAREST_MAX_DIFF` (50) gives `parcel_nearest`. The `projects.csv` column `geocode_source` records the method, and `parcel_nearest` pins say "Location approximate" in their popup.
- **Legistar overrides** (`_step_legistar_classify`, Step 5c): Conditional Use and rezoning Ordinance titles are parsed by `legistar_address_ranges`, which handles house-number ranges ("6502-6602 Grand Teton Plaza") and lists ("6501, 6601-6637 and 6701 Mineral Point Road"). A permit matches if its street matches, its number falls in a range, and the item was introduced no more than `LEGISTAR_DATE_SLACK_DAYS` (180) after the permit date. REZONED beats CONDITIONAL when both match, and VARIES (PD) projects are never overridden.
- **Basemap**: Esri `World_Light_Gray_Base` plus `World_Light_Gray_Reference` labels in a pane above route lines and below markers. It's keyless; CARTO basemaps started requiring an API key in late 2026.
- All HTML generation uses Python f-strings with `html.escape()` — no template engine.
- `EXCLUDE_RECORDS` in `generate_data.py` lists manually-identified false positives to skip.
- **Alteration filter** (`_step_filter_alterations`, Step 2c): Alteration-classified permits are kept only if the description signals a housing-stock change (`_STOCK_CHANGE_RE`: convert, split, add units). `alteration_overrides.csv` (`record_number,action,reason` with `include`/`exclude`) overrides the rule in either direction.
- `outcome_overrides.csv` and `use_type_overrides.csv` hand-correct project outcome and use type.
- `refresh.py` re-runs both stages when any cached source (geocode retries, Legistar, bike routes) exceeds its TTL.

## Tests

Stdlib `unittest`, no dependencies: `python3 -m unittest` (tests live in `test_generate_data.py` and `test_generate_site.py`).

## .gitignore

JSON, CSV, PDF, HTML, TXT, and ZIP files are gitignored, except whitelisted inputs/outputs: `projects.csv`, `zoning_districts.csv`, `transit_routes.json`, `bike_routes.json`, `outcome_overrides.csv`, `alteration_overrides.csv`. Cache temp files (`*.tmp`, `*.writing`, `*.corrupt`, `*.verify`) are ignored too.

## SESSION DISCIPLINE

Commit early and often. Don't wait for user's specific request. If a commit is in a worktree, merge it with the main directory and sync it back to the worktree immediately after every commit. After merging, regenerate the site in the main directory and check for errors.