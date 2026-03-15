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
import os

INPUT_CSV = "projects.csv"
ZONING_CSV = "zoning_districts.csv"
TRANSIT_JSON = "transit_routes.json"
OUTPUT_HTML = "index.html"

# ---------------------------------------------------------------------------
# Zoning district -> color, based on City of Madison West Area Plan map
# ---------------------------------------------------------------------------

ZONING_COLORS = {
    # Single-family Residential (yellows)
    "SR-C1": "#fff9c4", "SR-C2": "#fff176", "SR-C3": "#ffee58",
    "SR-G1": "#fff59d", "SR-V1": "#fff9c4", "SR-V2": "#fff176",
    # Two-family / Multi-family Residential (oranges -> pinks)
    "TR-R": "#ffcdd2", "TR-C1": "#ffcc80", "TR-C2": "#ffa726",
    "TR-C3": "#f57c00", "TR-C4": "#e65100", "TR-P": "#f48fb1",
    "TR-V1": "#ffab91", "TR-V2": "#ff7043", "TR-U1": "#ff8a65",
    "TR-U2": "#f4511e",
    # Mixed-Use and Commercial (reds)
    "LMX": "#ef9a9a", "NMX": "#ff5722", "TSS": "#e91e63",
    "CC-T": "#d32f2f", "CC": "#c62828", "RMX": "#ff1744",
    "MXC": "#ad1457", "THV": "#e57373",
    # Downtown and Urban (deep reds / magentas)
    "DR1": "#ffb74d", "DR2": "#ff9800",
    "UOR": "#e040fb", "UMX": "#d500f9", "DC": "#aa00ff",
    # Employment (purples / blues)
    "SE": "#5c6bc0", "TE": "#7e57c2", "EC": "#ce93d8",
    "SEC": "#3949ab", "IL": "#9c27b0", "IG": "#6a1b9a",
    # Special (greens / grays)
    "A": "#81c784", "UA": "#a5d6a7", "CN": "#c8e6c9",
    "PR": "#2e7d32", "AP": "#90a4ae", "ME": "#78909c",
    "MC": "#bcaaa4", "CI": "#66bb6a",
    "PD": "#9e9e9e", "PMHP": "#bdbdbd",
}

DEFAULT_ZONING_COLOR = "#757575"

STATUS_STYLES = {
    "Issued": "#2563eb", "In Process": "#f59e0b", "Closed": "#6b7280",
    "Rejected": "#ef4444", "Inspections Complete": "#10b981",
}

USE_TYPE_COLORS = {
    "PERMITTED": "#16a34a",
    "CONDITIONAL": "#d97706",
    "NOT_ALLOWED": "#dc2626",
    "VARIES": "#7c3aed",
    "UNKNOWN": "#6b7280",
}

USE_TYPE_LABELS = {
    "PERMITTED": "Permitted Use",
    "CONDITIONAL": "Conditional Use",
    "NOT_ALLOWED": "Not Allowed",
    "VARIES": "Varies (PD)",
    "UNKNOWN": "Unknown",
}

def load_zoning_info():
    """Load zoning district info from zoning_districts.csv."""
    with open(ZONING_CSV, newline="") as f:
        return list(csv.DictReader(f))


def zoning_color(code):
    if not code:
        return DEFAULT_ZONING_COLOR
    code = code.strip()
    if code in ZONING_COLORS:
        return ZONING_COLORS[code]
    for key in sorted(ZONING_COLORS.keys(), key=len, reverse=True):
        if code.startswith(key):
            return ZONING_COLORS[key]
    return DEFAULT_ZONING_COLOR


def marker_base_radius(units):
    """Base radius (at zoom 12) from unit count, log scale.
    Range: ~4px (2 units) to ~18px (474 units). JS applies zoom scaling."""
    if not units:
        return 4
    u = max(int(units), 1)
    return max(3, int(3 + 3 * math.log2(u)))


def build_popup_html(row):
    name = row["project_name"] or row["address"].split(",")[0]
    units_str = f"{row['units']} units" if row["units"] else "unknown"
    zoning = row["zoning"] or "N/A"
    status = row["status"]
    status_color = STATUS_STYLES.get(status, "#6b7280")
    use_type = row.get("use_type", "UNKNOWN")
    use_color = USE_TYPE_COLORS.get(use_type, "#6b7280")
    use_label = USE_TYPE_LABELS.get(use_type, use_type)

    return (
        f'<div class="popup">'
        f'<div class="popup-name">{html.escape(name)}</div>'
        f'<div class="popup-body">'
        f'<b>Address:</b> {html.escape(row["address"])}<br>'
        f'<b>Units:</b> {html.escape(units_str)}<br>'
        f'<b>Type:</b> {html.escape(row.get("housing_type", ""))}<br>'
        f'<b>Zoning:</b> {html.escape(zoning)}<br>'
        f'<b>Use Type:</b> <span style="color:{use_color}" class="popup-use">'
        f'{html.escape(use_label)}</span><br>'
        f'<b>Status:</b> <span style="color:{status_color}">'
        f'{html.escape(status)}</span><br>'
        f'<b>Date:</b> {html.escape(row["date"])}<br>'
        f'<b>Record:</b> {html.escape(row["record_number"])}'
        f'</div>'
        f'<div class="popup-desc">{html.escape(row["description"])}</div>'
        f'</div>'
    )


def build_stats_html(ht_counts, ht_units, use_type_counts):
    """Build HTML for housing type and use type stats panel."""
    # Housing type table
    ht_order = ["Mid-Rise", "Mid-Rise Mixed-Use", "High-Rise", "High-Rise Mixed-Use",
                "Townhouse", "Multiplex", "Duplex/Triplex"]
    ht_rows = []
    for ht in ht_order:
        if ht not in ht_counts:
            continue
        ht_rows.append(
            f'<tr class="zp-row">'
            f'<td class="zp-cell" style="font-weight:600">{html.escape(ht)}</td>'
            f'<td class="zp-cell" style="text-align:right">{ht_counts[ht]}</td>'
            f'<td class="zp-cell" style="text-align:right">{ht_units[ht]:,}</td>'
            f'</tr>'
        )
    # Use type table
    ut_order = [("PERMITTED", "Permitted"), ("CONDITIONAL", "Conditional"),
                ("NOT_ALLOWED", "Not Allowed"), ("VARIES", "Varies (PD)"),
                ("UNKNOWN", "Unknown")]
    ut_rows = []
    for code, label in ut_order:
        count = use_type_counts.get(code, 0)
        if count == 0:
            continue
        color = USE_TYPE_COLORS.get(code, "#6b7280")
        ut_rows.append(
            f'<tr class="zp-row">'
            f'<td class="zp-cell"><span style="color:{color};font-weight:600">'
            f'{html.escape(label)}</span></td>'
            f'<td class="zp-cell" style="text-align:right">{count}</td>'
            f'</tr>'
        )

    return (
        f'<div class="zp-section">'
        f'<div class="zp-cat">By Housing Type</div>'
        f'<table class="zp-table">'
        f'<tr class="zp-hdr"><th>Type</th><th style="text-align:right">Projects</th>'
        f'<th style="text-align:right">Units</th></tr>'
        f'{"".join(ht_rows)}</table></div>'
        f'<div class="zp-section">'
        f'<div class="zp-cat">By Use Classification</div>'
        f'<table class="zp-table">'
        f'<tr class="zp-hdr"><th>Use Type</th><th style="text-align:right">Projects</th></tr>'
        f'{"".join(ut_rows)}</table></div>'
    )


def build_legend_html(zoning_codes_used):
    categories = [
        ("Residential", ["SR-", "TR-", "DR"]),
        ("Mixed-Use / Commercial", ["CC", "NMX", "MXC", "TSS", "RMX", "LMX", "THV"]),
        ("Downtown / Urban", ["UOR", "UMX", "DC"]),
        ("Employment", ["EC", "IL", "IG", "SE", "TE", "SEC"]),
        ("Special", ["CI", "CN", "PR", "PD", "A", "UA", "AP", "PMHP"]),
    ]
    parts = []
    for cat_name, prefixes in categories:
        codes_in_cat = sorted(
            c for c in zoning_codes_used
            if c and any(c.startswith(p) for p in prefixes)
        )
        if not codes_in_cat:
            continue
        dots = "".join(
            f'<span class="leg-item">'
            f'<span class="leg-dot" style="background:{zoning_color(c)}"></span>'
            f'<span class="leg-code">{html.escape(c)}</span></span>'
            for c in codes_in_cat
        )
        parts.append(
            f'<div class="leg-row">'
            f'<span class="leg-cat">{cat_name}:</span>{dots}</div>'
        )
    if any(not c for c in zoning_codes_used):
        parts.append(
            f'<div><span class="leg-item">'
            f'<span class="leg-dot" style="background:{DEFAULT_ZONING_COLOR}"></span>'
            f'<span class="leg-code">Unknown</span></span></div>'
        )
    # Shape legend
    parts.append(
        '<div class="leg-shapes">'
        '&#9679; = Permitted use &nbsp; &#9632; = Conditional/Varies'
        '</div>'
    )
    return "\n".join(parts)


def build_zoning_panel_html(zoning_info):
    """Build the zoning reference panel HTML from zoning_districts.csv rows."""
    rows_by_cat = {}
    for z in zoning_info:
        cat = html.escape(z["category"])
        rows_by_cat.setdefault(cat, []).append(z)

    sections = []
    for cat, items in rows_by_cat.items():
        table_rows = []
        for z in items:
            code = z["code"]
            color = zoning_color(code)
            permitted = html.escape(z.get("residential_permitted", "") or "")
            conditional = html.escape(z.get("residential_conditional", "") or "")
            table_rows.append(
                f'<tr class="zp-row">'
                f'<td class="zp-code">'
                f'<span class="zp-dot" style="background:{color}"></span>'
                f'{html.escape(code)}</td>'
                f'<td class="zp-name">'
                f'<b>{html.escape(z["name"])}</b><br>'
                f'<span class="zp-desc">{html.escape(z["description"])}</span></td>'
                f'<td class="zp-cell">{permitted}</td>'
                f'<td class="zp-cell">{conditional}</td>'
                f'<td class="zp-cell zp-nowrap">{html.escape(z["max_stories"])}</td>'
                f'<td class="zp-cell zp-nowrap zp-last">{html.escape(z["max_density"])}</td>'
                f'</tr>'
            )
        sections.append(
            f'<div class="zp-section">'
            f'<div class="zp-cat">{cat}</div>'
            f'<table class="zp-table">'
            f'<tr class="zp-hdr">'
            f'<th>Code</th><th>District</th><th>Permitted</th>'
            f'<th>Conditional</th><th>Stories</th><th>Density</th></tr>'
            f'{"".join(table_rows)}</table></div>'
        )

    return "\n".join(sections)


def main():
    with open(INPUT_CSV, newline="") as f:
        rows = list(csv.DictReader(f))

    mappable = [r for r in rows if r.get("lat") and r.get("lng")]
    total = len(rows)
    mapped = len(mappable)
    total_units = sum(int(r["units"]) for r in rows if r.get("units"))
    zoning_codes_used = sorted(set(r.get("zoning", "") for r in rows))

    # Use type counts
    use_type_counts = {}
    for r in rows:
        ut = r.get("use_type", "UNKNOWN")
        use_type_counts[ut] = use_type_counts.get(ut, 0) + 1
    permitted_count = use_type_counts.get("PERMITTED", 0)
    conditional_count = (use_type_counts.get("CONDITIONAL", 0)
                        + use_type_counts.get("NOT_ALLOWED", 0)
                        + use_type_counts.get("VARIES", 0))

    markers = []
    for r in mappable:
        use_type = r.get("use_type", "UNKNOWN")
        markers.append({
            "lat": float(r["lat"]),
            "lng": float(r["lng"]),
            "r": marker_base_radius(r.get("units")),
            "c": zoning_color(r.get("zoning")),
            "p": build_popup_html(r),
            "t": use_type,
        })

    # Housing type counts (for stats panel)
    ht_counts = {}
    ht_units = {}
    for r in rows:
        ht = r.get("housing_type", "Unknown")
        units = int(r["units"]) if r.get("units") else 0
        ht_counts[ht] = ht_counts.get(ht, 0) + 1
        ht_units[ht] = ht_units.get(ht, 0) + units
    stats_html = build_stats_html(ht_counts, ht_units, use_type_counts)

    # Load transit routes
    transit_json = "[]"
    if os.path.exists(TRANSIT_JSON):
        with open(TRANSIT_JSON) as f:
            transit_json = f.read()

    legend_html = build_legend_html(zoning_codes_used)
    zoning_info = load_zoning_info()
    zoning_panel_html = build_zoning_panel_html(zoning_info)
    markers_json = json.dumps(markers)

    # The JS is minimal: init map, place markers, handle zoom scaling + panel toggle
    page_html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Madison WI Multi-Family Housing Permits (2025)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="stylesheet" href="style.css"/>
</head>
<body>
<div id="header">
  <div>
    <h1>Madison WI Multi-Family Housing Permits (2025)</h1>
    <div class="stats">
      <span>{total} projects</span>
      <span>{total_units:,} total units</span>
      <span>{mapped} mapped</span>
      <span class="stat-permitted">&#9679; {permitted_count} permitted</span>
      <span class="stat-conditional">&#9632; {conditional_count} conditional</span>
      <span>Size = unit count (log scale)</span>
    </div>
  </div>
  <div id="legend">
    {legend_html}
  </div>
</div>
<div id="map-wrap">
  <button id="zoning-btn" onclick="document.getElementById('zoning-panel').classList.add('open');this.style.display='none'">Zoning Reference</button>
  <div id="zoning-panel">
    <button id="panel-close" onclick="this.parentElement.classList.remove('open');document.getElementById('zoning-btn').style.display=''">&times;</button>
    <div id="panel-title">City of Madison Zoning District Summary</div>
    <div id="panel-note">
      Source: Zoning District Summary, October 17, 2025. Density = max dwelling units/acre.
      Stories marked * allow additional with Conditional Use approval.
      "Height Map" = determined by Downtown Height Map. "By plan" = determined by Master Plan / PD.
      Contact: zoning@cityofmadison.com | 608-266-4551
    </div>
    {stats_html}
    {zoning_panel_html}
  </div>
  <div id="map"></div>
</div>
<script>
var m=L.map("map").setView([43.073,-89.401],12);
L.tileLayer("https://tileserver.memomaps.de/tilegen/{{z}}/{{x}}/{{y}}.png",{{
  attribution:'Map <a href="https://memomaps.de/">memomaps.de</a> <a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, map data &copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom:19}}).addTo(m);
var tr={transit_json};
tr.forEach(function(rt){{
  var opts={{color:rt.color,weight:rt.weight,opacity:0.7}};
  if(rt.dash)opts.dashArray=rt.dash;
  L.polyline(rt.coords,opts).addTo(m).bindPopup(
    '<b>Route '+rt.name+'</b>'
  );
}});
var d={markers_json};
var markers=[];
function sqSvg(sz,fill){{
  return '<svg width="'+sz+'" height="'+sz+'" style="display:block">'
    +'<rect width="'+sz+'" height="'+sz+'" fill="'+fill+'" stroke="#fff" stroke-width="1.5" opacity="0.85"/></svg>';
}}
function makeSq(r,fill){{
  var sz=r*2;
  return L.divIcon({{
    html:sqSvg(sz,fill),
    className:"",
    iconSize:[sz,sz],
    iconAnchor:[sz/2,sz/2],
    popupAnchor:[0,-sz/2]
  }});
}}
var SQ_TYPES={{"CONDITIONAL":1,"NOT_ALLOWED":1,"VARIES":1}};
d.forEach(function(x){{
  var mk;
  if(SQ_TYPES[x.t]){{
    mk=L.marker([x.lat,x.lng],{{icon:makeSq(x.r,x.c)}});
    mk._isSq=true;
  }}else{{
    mk=L.circleMarker([x.lat,x.lng],{{
      radius:x.r,fillColor:x.c,color:"#fff",weight:1.5,
      opacity:1,fillOpacity:0.85
    }});
    mk._isSq=false;
  }}
  mk.addTo(m).bindPopup(x.p);
  mk._baseR=x.r;
  mk._fill=x.c;
  markers.push(mk);
}});
function scaleMarkers(){{
  var z=m.getZoom();
  var s=Math.max(0.15,0.05+0.35*Math.log2(Math.max(1,z-10)));
  markers.forEach(function(mk){{
    var r=Math.max(2,mk._baseR*s);
    if(mk._isSq){{
      var sz=r*2;
      mk.setIcon(L.divIcon({{
        html:sqSvg(sz,mk._fill),
        className:"",
        iconSize:[sz,sz],
        iconAnchor:[sz/2,sz/2],
        popupAnchor:[0,-sz/2]
      }}));
    }}else{{
      mk.setRadius(r);
    }}
  }});
}}
m.on("zoomend",scaleMarkers);
scaleMarkers();
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
