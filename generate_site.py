#!/usr/bin/env python3
"""Read projects.csv, compute marker colors/sizes in Python, generate index.html.

All logic (zoning color mapping, marker sizing, popup HTML) is computed here.
The generated HTML contains only a thin Leaflet initialization loop over
pre-computed marker data.
"""

import csv
import html
import json
import math

INPUT_CSV = "projects.csv"
OUTPUT_HTML = "index.html"

# ---------------------------------------------------------------------------
# Zoning district -> color, based on City of Madison West Area Plan map
# ---------------------------------------------------------------------------
# Residential: yellows -> oranges -> pinks
# Mixed-use / Commercial: reds
# Employment: purples
# Special: greens / grays

ZONING_COLORS = {
    # Single-family Residential (yellows)
    "SR-C1": "#fff9c4",
    "SR-C2": "#fff176",
    "SR-C3": "#ffee58",
    "SR-G1": "#fff59d",
    "SR-V1": "#fff9c4",
    "SR-V2": "#fff176",
    # Two-family / Multi-family Residential (oranges -> pinks)
    "TR-C1": "#ffcc80",
    "TR-C2": "#ffa726",
    "TR-C3": "#f57c00",
    "TR-C4": "#e65100",
    "TR-P":  "#f48fb1",
    "TR-R":  "#ec407a",
    "TR-U1": "#ffab91",
    "TR-U2": "#ff7043",
    "TR-V1": "#ffcdd2",
    "TR-V2": "#ef9a9a",
    # Mixed-Use and Commercial (reds)
    "CC":    "#c62828",
    "CC-T":  "#d32f2f",
    "NMX":   "#ff5722",
    "MXC":   "#ad1457",
    "TSS":   "#e91e63",
    "RMX":   "#ff1744",
    # Employment (purples / blues)
    "EC":    "#ce93d8",
    "IL":    "#9c27b0",
    "IG":    "#6a1b9a",
    "SE":    "#5c6bc0",
    "SEC":   "#3949ab",
    # Transitional / Employment edge
    "TE":    "#7e57c2",
    # Special District (greens / grays)
    "CI":    "#66bb6a",
    "CN":    "#a5d6a7",
    "PR":    "#2e7d32",
    "PD":    "#9e9e9e",
    "A":     "#81c784",
    "DR1":   "#ffb74d",
    "DR2":   "#ff9800",
}

DEFAULT_ZONING_COLOR = "#757575"  # gray for unknown

# Status badge colors (secondary, shown in popup)
STATUS_STYLES = {
    "Issued": "#2563eb",
    "In Process": "#f59e0b",
    "Closed": "#6b7280",
    "Rejected": "#ef4444",
    "Inspections Complete": "#10b981",
}


def zoning_color(code):
    """Map a zoning code to a hex color. Handles prefixed codes like 'PD'."""
    if not code:
        return DEFAULT_ZONING_COLOR
    code = code.strip()
    if code in ZONING_COLORS:
        return ZONING_COLORS[code]
    # Try prefix match (e.g., "SR-C1(xx)" -> "SR-C1")
    for key in sorted(ZONING_COLORS.keys(), key=len, reverse=True):
        if code.startswith(key):
            return ZONING_COLORS[key]
    return DEFAULT_ZONING_COLOR


def marker_radius(units):
    """Compute circle marker radius from unit count using log scale.
    Range: ~6px (2 units) to ~28px (474 units)."""
    if not units:
        return 6  # minimum for unknown
    u = max(int(units), 1)
    return int(4 + 4 * math.log2(u))


def build_popup_html(row):
    """Build popup HTML string for a marker, fully in Python."""
    name = row["project_name"] or row["address"].split(",")[0]
    units_str = f"{row['units']} units" if row["units"] else "unknown"
    zoning = row["zoning"] or "N/A"
    status = row["status"]
    status_color = STATUS_STYLES.get(status, "#6b7280")

    return (
        f'<div style="font:13px/1.5 system-ui,sans-serif;max-width:320px">'
        f'<div style="font-weight:600;font-size:14px;margin-bottom:4px">'
        f'{html.escape(name)}</div>'
        f'<div style="color:#475569">'
        f'<b>Address:</b> {html.escape(row["address"])}<br>'
        f'<b>Units:</b> {html.escape(units_str)}<br>'
        f'<b>Zoning:</b> {html.escape(zoning)}<br>'
        f'<b>Status:</b> <span style="color:{status_color}">'
        f'{html.escape(status)}</span><br>'
        f'<b>Date:</b> {html.escape(row["date"])}<br>'
        f'<b>Record:</b> {html.escape(row["record_number"])}'
        f'</div>'
        f'<div style="margin-top:6px;font-size:12px;color:#64748b;'
        f'border-top:1px solid #e2e8f0;padding-top:6px">'
        f'{html.escape(row["description"])}</div>'
        f'</div>'
    )


def build_legend_html(zoning_codes_used):
    """Build legend HTML showing zoning colors that appear in the data."""
    # Group zoning codes by category
    categories = [
        ("Residential", ["SR-", "TR-", "DR"]),
        ("Mixed-Use / Commercial", ["CC", "NMX", "MXC", "TSS", "RMX"]),
        ("Employment", ["EC", "IL", "IG", "SE", "TE"]),
        ("Special", ["CI", "CN", "PR", "PD", "A"]),
    ]

    parts = []
    for cat_name, prefixes in categories:
        codes_in_cat = sorted(
            c for c in zoning_codes_used
            if any(c.startswith(p) for p in prefixes)
        )
        if not codes_in_cat:
            continue
        dots = "".join(
            f'<span style="display:inline-flex;align-items:center;margin-right:8px">'
            f'<span style="width:12px;height:12px;border-radius:50%;'
            f'background:{zoning_color(c)};display:inline-block;margin-right:3px;'
            f'border:1px solid rgba(0,0,0,0.2)"></span>'
            f'<span style="font-size:11px">{html.escape(c)}</span></span>'
            for c in codes_in_cat
        )
        parts.append(
            f'<div style="margin-bottom:2px">'
            f'<span style="font-size:10px;color:#94a3b8;margin-right:6px">'
            f'{cat_name}:</span>{dots}</div>'
        )

    # Unknown
    if any(not c for c in zoning_codes_used):
        parts.append(
            f'<div><span style="display:inline-flex;align-items:center">'
            f'<span style="width:12px;height:12px;border-radius:50%;'
            f'background:{DEFAULT_ZONING_COLOR};display:inline-block;'
            f'margin-right:3px;border:1px solid rgba(0,0,0,0.2)"></span>'
            f'<span style="font-size:11px">Unknown</span></span></div>'
        )

    return "\n".join(parts)


def main():
    # Read CSV
    with open(INPUT_CSV, newline="") as f:
        rows = list(csv.DictReader(f))

    # Filter to rows with coordinates
    mappable = [r for r in rows if r.get("lat") and r.get("lng")]

    # Compute stats
    total = len(rows)
    mapped = len(mappable)
    total_units = sum(int(r["units"]) for r in rows if r.get("units"))

    # Collect unique zoning codes
    zoning_codes_used = sorted(set(r.get("zoning", "") for r in rows))

    # Build marker data array — all logic computed in Python
    markers = []
    for r in mappable:
        markers.append({
            "lat": float(r["lat"]),
            "lng": float(r["lng"]),
            "r": marker_radius(r.get("units")),
            "c": zoning_color(r.get("zoning")),
            "p": build_popup_html(r),
        })

    legend_html = build_legend_html(zoning_codes_used)

    # Minimal JS: just init map + loop over pre-computed markers
    markers_json = json.dumps(markers)

    page_html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Madison WI Multi-Family Housing Permits (2025)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif}}
#header{{background:#1e293b;color:#f8fafc;padding:12px 20px;
  display:flex;align-items:flex-start;justify-content:space-between;
  flex-wrap:wrap;gap:8px}}
#header h1{{font-size:18px;font-weight:600}}
.stats{{font-size:13px;color:#94a3b8;margin-top:4px}}
.stats span{{margin-right:14px}}
#legend{{display:flex;flex-direction:column;gap:2px}}
#map{{height:calc(100vh - 80px);width:100%}}
</style>
</head>
<body>
<div id="header">
  <div>
    <h1>Madison WI Multi-Family Housing Permits (2025)</h1>
    <div class="stats">
      <span>{total} projects</span>
      <span>{total_units:,} total units</span>
      <span>{mapped} mapped</span>
    </div>
  </div>
  <div id="legend">
    {legend_html}
  </div>
</div>
<div id="map"></div>
<script>
var m=L.map("map").setView([43.073,-89.401],12);
L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png",{{
  attribution:'&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom:19}}).addTo(m);
var d={markers_json};
d.forEach(function(x){{
  L.circleMarker([x.lat,x.lng],{{
    radius:x.r,fillColor:x.c,color:"#fff",weight:1.5,
    opacity:1,fillOpacity:0.85
  }}).addTo(m).bindPopup(x.p);
}});
</script>
</body>
</html>
"""

    with open(OUTPUT_HTML, "w") as f:
        f.write(page_html)

    print(f"Generated {OUTPUT_HTML}: {total} projects, {mapped} mapped, "
          f"{total_units:,} total units")


if __name__ == "__main__":
    main()
