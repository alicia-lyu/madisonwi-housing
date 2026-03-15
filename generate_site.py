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
ZONING_CSV = "zoning_districts.csv"
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
        '&#9679; = Permitted use &nbsp; &#9650; = Conditional use'
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
    conditional_count = use_type_counts.get("CONDITIONAL", 0) + use_type_counts.get("NOT_ALLOWED", 0)

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
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,sans-serif}}
#header{{background:#1e293b;color:#f8fafc;padding:10px 20px;
  display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:8px}}
#header h1{{font-size:18px;font-weight:600}}
.stats{{font-size:13px;color:#94a3b8;margin-top:3px}}
.stats span{{margin-right:14px}}
#legend{{display:flex;flex-direction:column;gap:2px}}
#map-wrap{{position:relative;height:calc(100vh - 56px)}}
#map{{height:100%;width:100%}}
#zoning-btn{{position:absolute;top:10px;right:10px;z-index:1000;
  background:#1e293b;color:#f8fafc;border:none;padding:7px 14px;
  border-radius:6px;cursor:pointer;font-size:13px;font-family:inherit;
  box-shadow:0 2px 6px rgba(0,0,0,0.3)}}
#zoning-btn:hover{{background:#334155}}
#zoning-panel{{position:absolute;top:10px;right:10px;z-index:1001;
  background:#fff;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.25);
  width:900px;max-width:calc(100vw - 30px);max-height:calc(100vh - 100px);
  overflow-y:auto;padding:16px;display:none}}
#zoning-panel.open{{display:block}}
#panel-close{{float:right;background:none;border:none;font-size:20px;
  cursor:pointer;color:#64748b;line-height:1}}
#panel-close:hover{{color:#1e293b}}
#panel-title{{font-size:15px;font-weight:600;margin-bottom:10px;color:#1e293b}}
#panel-note{{font-size:11px;color:#94a3b8;margin-bottom:12px;line-height:1.4}}
/* Popup */
.popup{{font:13px/1.5 system-ui,sans-serif;max-width:320px}}
.popup-name{{font-weight:600;font-size:14px;margin-bottom:4px}}
.popup-body{{color:#475569}}
.popup-use{{font-weight:600}}
.popup-desc{{margin-top:6px;font-size:12px;color:#64748b;border-top:1px solid #e2e8f0;padding-top:6px}}
/* Legend */
.leg-item{{display:inline-flex;align-items:center;margin-right:8px}}
.leg-dot{{width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:3px;border:1px solid rgba(0,0,0,0.2)}}
.leg-code{{font-size:11px}}
.leg-row{{margin-bottom:2px}}
.leg-cat{{font-size:10px;color:#94a3b8;margin-right:6px}}
.leg-shapes{{margin-top:2px;font-size:11px;color:#cbd5e1}}
/* Stats color highlights */
.stat-permitted{{color:#16a34a}}
.stat-conditional{{color:#d97706}}
/* Zoning panel table */
.zp-section{{margin-bottom:12px}}
.zp-cat{{font-weight:600;font-size:13px;color:#3b82f6;margin-bottom:4px;border-bottom:1px solid #e2e8f0;padding-bottom:3px}}
.zp-table{{font-size:12px;border-collapse:collapse;width:100%}}
.zp-hdr{{color:#94a3b8;font-size:10px;text-transform:uppercase}}
.zp-hdr th{{text-align:left;padding:2px 6px}}
.zp-row{{border-bottom:1px solid #f1f5f9}}
.zp-code{{white-space:nowrap;font-weight:600;vertical-align:top;padding:4px 8px 4px 0}}
.zp-dot{{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:middle;margin-right:4px;border:1px solid rgba(0,0,0,0.15)}}
.zp-name{{vertical-align:top;padding:4px 8px 4px 0;min-width:120px}}
.zp-desc{{font-size:11px;color:#64748b}}
.zp-cell{{vertical-align:top;padding:4px 6px;font-size:11px;color:#475569}}
.zp-nowrap{{white-space:nowrap;font-size:12px}}
.zp-last{{padding-left:6px;padding-right:0}}
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
      <span class="stat-permitted">&#9679; {permitted_count} permitted</span>
      <span class="stat-conditional">&#9650; {conditional_count} conditional</span>
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
    {zoning_panel_html}
  </div>
  <div id="map"></div>
</div>
<script>
var m=L.map("map").setView([43.073,-89.401],12);
L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png",{{
  attribution:'&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom:19}}).addTo(m);
var d={markers_json};
var markers=[];
function triSvg(sz,fill){{
  var h=sz*1.73;
  var pts=(sz/2)+",0 "+sz+","+h+" 0,"+h;
  return '<svg width="'+sz+'" height="'+h+'" style="display:block">'
    +'<polygon points="'+pts+'" fill="'+fill+'" stroke="#fff" stroke-width="1.5" opacity="0.85"/></svg>';
}}
function makeTri(r,fill){{
  var sz=r*2;
  var h=sz*1.73;
  return L.divIcon({{
    html:triSvg(sz,fill),
    className:"",
    iconSize:[sz,h],
    iconAnchor:[sz/2,h/2],
    popupAnchor:[0,-h/2]
  }});
}}
d.forEach(function(x){{
  var mk;
  if(x.t==="CONDITIONAL"||x.t==="NOT_ALLOWED"){{
    mk=L.marker([x.lat,x.lng],{{icon:makeTri(x.r,x.c)}});
    mk._isTri=true;
  }}else{{
    mk=L.circleMarker([x.lat,x.lng],{{
      radius:x.r,fillColor:x.c,color:"#fff",weight:1.5,
      opacity:1,fillOpacity:0.85
    }});
    mk._isTri=false;
  }}
  mk.addTo(m).bindPopup(x.p);
  mk._baseR=x.r;
  mk._fill=x.c;
  markers.push(mk);
}});
function scaleMarkers(){{
  var z=m.getZoom();
  var s=Math.pow(2,(z-12)*1.5)*0.6;
  s=Math.max(0.15,Math.min(s,3));
  markers.forEach(function(mk){{
    var r=Math.max(2,mk._baseR*s);
    if(mk._isTri){{
      var sz=r*2,h=sz*1.73;
      mk.setIcon(L.divIcon({{
        html:triSvg(sz,mk._fill),
        className:"",
        iconSize:[sz,h],
        iconAnchor:[sz/2,h/2],
        popupAnchor:[0,-h/2]
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
