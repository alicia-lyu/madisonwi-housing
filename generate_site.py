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
# Policy milestones — annotate date filter dropdowns
# ---------------------------------------------------------------------------

# Major milestones: shown in both year and month dropdowns
POLICY_MAJOR = [
    ("2018-08", "Imagine Madison Plan"),
    ("2023-01", "TOD Overlay District"),
    ("2024-04", "ADU Expansion"),
    ("2024-09", "BRT Launch"),
    ("2025-02", "Housing Forward Pkg 1"),
    ("2025-07", "Housing Forward Pkg 2"),
    ("2025-10", "Housing Forward Pkg 3"),
]

# Area plans: shown only in month dropdown
POLICY_AREA_PLANS = [
    ("2016-01", "Emerson East-Eken Park-Yahara"),
    ("2017-01", "High Point-Raymond"),
    ("2017-09", "Darbo Worthington Starkweather"),
    ("2017-10", "Cottage Grove Rd"),
    ("2018-01", "Elderberry, Junction, Pioneer"),
    ("2018-12", "Milwaukee St"),
    ("2019-01", "Triangle Monona Bay"),
    ("2019-11", "Mifflandia, Nelson"),
    ("2020-07", "Oscar Mayer"),
    ("2022-01", "South Madison, Yahara Hills"),
    ("2023-01", "Rattman, Reiner, Shady Wood"),
    ("2024-09", "Northeast, West Area Plan"),
    ("2025-01", "Lamp House Block"),
]

# ---------------------------------------------------------------------------
# Color maps
# ---------------------------------------------------------------------------

# Zoning district -> color, based on City of Madison West Area Plan map
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
    "REZONED": "#ef4444",
    "VARIES": "#ef4444",
    "UNKNOWN": "#6b7280",
}

USE_TYPE_LABELS = {
    "PERMITTED": "Permitted Use",
    "CONDITIONAL": "Conditional Use",
    "REZONED": "Rezoned",
    "VARIES": "Varies (PD)",
    "UNKNOWN": "Unknown",
}

HOUSING_COLORS = {
    "Mid-Rise":             "#f14e4e",
    "Mid-Rise Mixed-Use":   "#f17e4e",
    "High-Rise":            "#b04ef1",
    "High-Rise Mixed-Use":  "#d04ef1",
    "Townhouse":            "#f1c84e",
    "Multiplex":            "#4ef1a0",
    "Duplex/Triplex":       "#4e9af1",
}

OUTCOME_COLORS = {"BUILT": "#10b981", "ACTIVE": "#d97706", "DID_NOT_PROCEED": "#ef4444"}
OUTCOME_LABELS = {"BUILT": "Built", "ACTIVE": "Active", "DID_NOT_PROCEED": "Did Not Proceed"}

# ---------------------------------------------------------------------------
# Zoning color lookup
# ---------------------------------------------------------------------------

def zoning_color(code):
    if not code:
        return DEFAULT_ZONING_COLOR
    code = code.strip()
    if code in ZONING_COLORS:
        return ZONING_COLORS[code]
    # Prefix match: try longest keys first so "CC-T" matches before "CC"
    for key in sorted(ZONING_COLORS.keys(), key=len, reverse=True):
        if code.startswith(key):
            return ZONING_COLORS[key]
    return DEFAULT_ZONING_COLOR


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_zoning_info():
    """Load zoning district info from zoning_districts.csv."""
    with open(ZONING_CSV, newline="") as f:
        return list(csv.DictReader(f))


def load_transit_json():
    """Load transit route data, or return empty list if not available."""
    if os.path.exists(TRANSIT_JSON):
        with open(TRANSIT_JSON) as f:
            return f.read()
    return "[]"


# ---------------------------------------------------------------------------
# Marker sizing
# ---------------------------------------------------------------------------

def marker_base_radius(units):
    """Base radius (at zoom 12) from unit count, log scale.
    Range: ~4px (2 units) to ~18px (474 units). JS applies zoom scaling."""
    if not units:
        return 4
    u = max(int(units), 1)
    return max(3, int(3 + 3 * math.log2(u)))


# ---------------------------------------------------------------------------
# Popup HTML
# ---------------------------------------------------------------------------

def build_popup_html(row):
    name = row["project_name"] or row["address"].split(",")[0]
    units_str = f"{row['units']} units" if row["units"] else "unknown"
    zoning = row["zoning"] or "N/A"
    status = row["status"]
    status_color = STATUS_STYLES.get(status, "#6b7280")
    use_type = row.get("use_type", "UNKNOWN")
    use_color = USE_TYPE_COLORS.get(use_type, "#6b7280")
    use_label = USE_TYPE_LABELS.get(use_type, use_type)

    outcome = row.get("outcome", "BUILT")
    outcome_color = OUTCOME_COLORS.get(outcome, "#6b7280")
    outcome_label = OUTCOME_LABELS.get(outcome, outcome)

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
        f'<b>Outcome:</b> <span style="color:{outcome_color}">'
        f'{html.escape(outcome_label)}</span><br>'
        f'<b>Status:</b> <span style="color:{status_color}">'
        f'{html.escape(status)}</span><br>'
        f'<b>Date:</b> {html.escape(row["date"])}<br>'
        f'<b>Record:</b> {html.escape(row["record_number"])}'
        f'</div>'
        f'<div class="popup-desc">{html.escape(row["description"])}</div>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Stats table (housing type x use type cross-tab)
# ---------------------------------------------------------------------------

HOUSING_TYPE_ORDER = [
    "Mid-Rise", "Mid-Rise Mixed-Use", "High-Rise", "High-Rise Mixed-Use",
    "Townhouse", "Multiplex", "Duplex/Triplex",
]

USE_COLUMNS = ("permitted", "conditional", "rezoned_pd", "unknown")


def _use_type_to_column(use_type):
    """Map raw use_type string to cross-tab column key."""
    if use_type == "PERMITTED":
        return "permitted"
    if use_type == "CONDITIONAL":
        return "conditional"
    if use_type in ("REZONED", "VARIES"):
        return "rezoned_pd"
    return "unknown"


def _build_cross_tab(rows):
    """Build cross-tab dict: housing_type -> column -> {n, u}."""
    cross = {}
    for r in rows:
        ht = r.get("housing_type", "Unknown")
        col = _use_type_to_column(r.get("use_type", "UNKNOWN"))
        units = int(r["units"]) if r.get("units") else 0
        cross.setdefault(ht, {}).setdefault(col, {"n": 0, "u": 0})
        cross[ht][col]["n"] += 1
        cross[ht][col]["u"] += units
    return cross


def _stats_cell(cross, ht, col):
    """Render one cell of the stats cross-tab."""
    d = cross.get(ht, {}).get(col, {"n": 0, "u": 0})
    if d["n"] == 0:
        return '<td class="zp-cell" style="text-align:center;color:#cbd5e1">—</td>'
    return (f'<td class="zp-cell" style="text-align:right">'
            f'{d["n"]} <span class="zp-desc">({d["u"]:,} units)</span></td>')


def build_stats_html(rows):
    """Build cross-tab: housing type (rows) x permitted/conditional (columns)."""
    cross = _build_cross_tab(rows)

    table_rows = []
    for ht in HOUSING_TYPE_ORDER:
        if ht not in cross:
            continue
        total_n = sum(cross[ht].get(c, {}).get("n", 0) for c in USE_COLUMNS)
        total_u = sum(cross[ht].get(c, {}).get("u", 0) for c in USE_COLUMNS)
        cells = "".join(_stats_cell(cross, ht, c) for c in USE_COLUMNS)
        table_rows.append(
            f'<tr class="zp-row">'
            f'<td class="zp-cell" style="font-weight:600">{html.escape(ht)}</td>'
            f'{cells}'
            f'<td class="zp-cell" style="text-align:right;font-weight:600">'
            f'{total_n} <span class="zp-desc">({total_u:,})</span></td>'
            f'</tr>'
        )

    # Totals row
    tot = {}
    for col in USE_COLUMNS:
        tot[col] = {"n": 0, "u": 0}
        for ht in cross:
            d = cross[ht].get(col, {"n": 0, "u": 0})
            tot[col]["n"] += d["n"]
            tot[col]["u"] += d["u"]
    grand_n = sum(tot[c]["n"] for c in USE_COLUMNS)
    grand_u = sum(tot[c]["u"] for c in USE_COLUMNS)

    tot_cells = "".join(
        f'<td class="zp-cell" style="text-align:right;font-weight:700">'
        f'{tot[c]["n"]} <span class="zp-desc">({tot[c]["u"]:,})</span></td>'
        for c in USE_COLUMNS
    )
    table_rows.append(
        f'<tr style="border-top:2px solid #cbd5e1">'
        f'<td class="zp-cell" style="font-weight:700">Total</td>'
        f'{tot_cells}'
        f'<td class="zp-cell" style="text-align:right;font-weight:700">'
        f'{grand_n} <span class="zp-desc">({grand_u:,})</span></td>'
        f'</tr>'
    )

    return (
        f'<div class="zp-section">'
        f'<div class="zp-cat">Project Summary</div>'
        f'<table class="zp-table">'
        f'<tr class="zp-hdr"><th>Housing Type</th>'
        f'<th style="text-align:right;color:#16a34a">Permitted</th>'
        f'<th style="text-align:right;color:#d97706">Conditional</th>'
        f'<th style="text-align:right;color:#ef4444">Rezoned / PD</th>'
        f'<th style="text-align:right;color:#6b7280">Unknown</th>'
        f'<th style="text-align:right">Total</th></tr>'
        f'{"".join(table_rows)}</table></div>'
    )


# ---------------------------------------------------------------------------
# Legend HTML
# ---------------------------------------------------------------------------

LEGEND_CATEGORIES = [
    ("Residential", ["SR-", "TR-", "DR"]),
    ("Mixed-Use / Commercial", ["CC", "NMX", "MXC", "TSS", "RMX", "LMX", "THV"]),
    ("Downtown / Urban", ["UOR", "UMX", "DC"]),
    ("Employment", ["EC", "IL", "IG", "SE", "TE", "SEC"]),
    ("Special", ["CI", "CN", "PR", "PD", "A", "UA", "AP", "PMHP"]),
]


def build_legend_html(zoning_codes_used):
    parts = []
    for cat_name, prefixes in LEGEND_CATEGORIES:
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
        '&#9679; = Permitted &nbsp; &#9632; = Conditional / Rezoned / PD / Unknown'
        '</div>'
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Zoning reference panel
# ---------------------------------------------------------------------------

def _build_zoning_row(z):
    """Build HTML for a single zoning district row with inline collapsible description."""
    code = z["code"]
    color = zoning_color(code)
    permitted = html.escape(z.get("residential_permitted", "") or "")
    conditional = html.escape(z.get("residential_conditional", "") or "")
    desc_text = (z.get("description") or "").strip()
    desc_id = f'zd-{html.escape(code)}'

    if desc_text:
        toggle_td = (
            f'<td class="zp-expand" onclick="'
            f"var d=document.getElementById('{desc_id}');"
            f"var open=d.style.display==='none';"
            f"d.style.display=open?'block':'none';"
            f"this.textContent=open?'\\u25BE':'\\u25B8'"
            f'">&#x25B8;</td>'
        )
        desc_div = (
            f'<div id="{desc_id}" class="zp-desc-inline" style="display:none">'
            f'{html.escape(desc_text)}</div>'
        )
    else:
        toggle_td = '<td class="zp-expand-empty"></td>'
        desc_div = ""

    return (
        f'<tr class="zp-row">'
        f'{toggle_td}'
        f'<td class="zp-code">'
        f'<span class="zp-dot" style="background:{color}"></span>'
        f'{html.escape(code)}</td>'
        f'<td class="zp-name"><b>{html.escape(z["name"])}</b>{desc_div}</td>'
        f'<td class="zp-cell">{permitted}</td>'
        f'<td class="zp-cell">{conditional}</td>'
        f'<td class="zp-cell zp-nowrap">{html.escape(z["max_stories"])}</td>'
        f'<td class="zp-cell zp-nowrap zp-last">{html.escape(z["max_density"])}</td>'
        f'</tr>'
    )


def build_zoning_panel_html(zoning_info):
    """Build the zoning reference panel HTML from zoning_districts.csv rows."""
    rows_by_cat = {}
    for z in zoning_info:
        cat = html.escape(z["category"])
        rows_by_cat.setdefault(cat, []).append(z)

    sections = []
    for cat, items in rows_by_cat.items():
        table_rows = "".join(_build_zoning_row(z) for z in items)
        sections.append(
            f'<div class="zp-section">'
            f'<div class="zp-cat">{cat}</div>'
            f'<table class="zp-table">'
            f'<tr class="zp-hdr">'
            f'<th></th><th>Code</th><th>District</th><th>Permitted</th>'
            f'<th>Conditional</th><th>Stories</th><th>Density</th></tr>'
            f'{table_rows}</table></div>'
        )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Marker data preparation
# ---------------------------------------------------------------------------

def build_marker_data(mappable):
    """Build the JSON-serializable marker list for the Leaflet map."""
    markers = []
    for r in mappable:
        markers.append({
            "lat": float(r["lat"]),
            "lng": float(r["lng"]),
            "r": marker_base_radius(r.get("units")),
            "c": zoning_color(r.get("zoning")),
            "p": build_popup_html(r),
            "t": r.get("use_type", "UNKNOWN"),
            "d": r.get("date", ""),
            "o": r.get("outcome", "BUILT"),
        })
    return markers


def build_all_projects_data(rows):
    """Build the compact project list used by JS for date-filterable stats."""
    return [
        {
            "d": r.get("date", ""),
            "t": r.get("use_type", "UNKNOWN"),
            "h": r.get("housing_type", "Unknown"),
            "u": int(r["units"]) if r.get("units") else 0,
            "o": r.get("outcome", "BUILT"),
        }
        for r in rows
    ]


def build_all_rows_data(rows):
    """Build richer project list for the list view panel."""
    result = []
    for r in rows:
        name = r.get("project_name") or r.get("address", "").split(",")[0]
        lat = float(r["lat"]) if r.get("lat") else None
        lng = float(r["lng"]) if r.get("lng") else None
        result.append({
            "n": name,
            "a": r.get("address", ""),
            "d": r.get("date", ""),
            "u": int(r["units"]) if r.get("units") else 0,
            "t": r.get("use_type", "UNKNOWN"),
            "h": r.get("housing_type", "Unknown"),
            "z": r.get("zoning", ""),
            "s": r.get("status", ""),
            "o": r.get("outcome", "BUILT"),
            "lat": lat,
            "lng": lng,
        })
    return result


# ---------------------------------------------------------------------------
# JavaScript template
# ---------------------------------------------------------------------------

def _build_map_js(markers_json, all_projects_json, all_rows_json, transit_json):
    """Return the <script> block contents for the Leaflet map.

    This JS is intentionally compact — it only handles map init, marker placement,
    zoom scaling, date filtering, and dynamic stats rebuilding. All heavy computation
    (colors, sizes, popups) is done in Python.
    """
    # Build milestone lookup objects for date dropdown annotations
    year_map = {}
    for date, label in POLICY_MAJOR:
        y = date[:4]
        year_map.setdefault(y, []).append(label)
    milestones_year_js = json.dumps({k: ", ".join(v) for k, v in year_map.items()})

    month_map = {}
    for date, label in POLICY_MAJOR + POLICY_AREA_PLANS:
        month_map.setdefault(date, []).append(label)
    milestones_month_js = json.dumps({k: ", ".join(v) for k, v in month_map.items()})

    chart_colors_use_js = json.dumps(USE_TYPE_COLORS)
    chart_colors_housing_js = json.dumps(HOUSING_COLORS)
    chart_colors_zone_js = json.dumps(ZONING_COLORS)

    # Double braces {{ }} are literal JS braces inside the f-string
    return f"""\
var ML_Y={milestones_year_js},ML_M={milestones_month_js};
var CHART_COLORS_USE={chart_colors_use_js};
var CHART_COLORS_HOUSING={chart_colors_housing_js};
var CHART_COLORS_ZONE={chart_colors_zone_js};
var m=L.map("map").setView([43.073,-89.401],12);
L.tileLayer("https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager_labels_under/{{z}}/{{x}}/{{y}}@2x.png",{{
  attribution:'&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
  subdomains:'abcd',maxZoom:20}}).addTo(m);
var tr={transit_json};
tr.forEach(function(rt){{
  var opts={{color:rt.color,weight:rt.weight,opacity:0.7}};
  if(rt.dash)opts.dashArray=rt.dash;
  L.polyline(rt.coords,opts).addTo(m).bindPopup(
    '<b>Route '+rt.name+'</b>'
  );
}});
var allProj={all_projects_json};
var allRows={all_rows_json};
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
var SQ_TYPES={{"CONDITIONAL":1,"REZONED":1,"VARIES":1,"UNKNOWN":1}};
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
  mk._date=x.d||"";
  mk._useType=x.t||"";
  mk._outcome=x.o||"";
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
var MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
var gran="year";
function dateKey(d){{return gran==="year"?d.slice(0,4):d.slice(0,7)}}
function fmtOpt(v){{
  if(gran==="year")return v;
  var p=v.split("-");return MONTHS[parseInt(p[1])-1]+" "+p[0];
}}
function allKeys(){{
  var s=new Set();
  markers.forEach(function(mk){{if(mk._date)s.add(dateKey(mk._date))}});
  return Array.from(s).sort();
}}
function fillSel(sel,opts,idx){{
  sel.innerHTML="";
  opts.forEach(function(v){{
    var o=document.createElement("option");o.value=v;
    var ml=gran==="year"?ML_Y:ML_M;
    if(ml[v]){{o.text=fmtOpt(v)+" \u25c6";o.title=fmtOpt(v)+" \u00b7 "+ml[v]}}else{{o.text=fmtOpt(v)}}
    sel.appendChild(o);
  }});
  sel.selectedIndex=Math.min(idx,opts.length-1);
}}
var HT_ORDER=["Mid-Rise","Mid-Rise Mixed-Use","High-Rise","High-Rise Mixed-Use",
  "Townhouse","Multiplex","Duplex/Triplex"];
var COL_KEYS=["permitted","conditional","rezoned_pd","unknown"];
var COL_LABELS=[["Permitted","#16a34a"],["Conditional","#d97706"],["Rezoned / PD","#ef4444"],["Unknown","#6b7280"]];
function buildStats(from,to,useTypes,outcomes){{
  var cross={{}};
  var fProj=allProj.filter(function(p){{
    var k=gran==="year"?p.d.slice(0,4):p.d.slice(0,7);
    return k&&k>=from&&k<=to&&useTypes.has(p.t)&&outcomes.has(p.o||"BUILT");
  }});
  fProj.forEach(function(p){{
    var col=p.t==="PERMITTED"?"permitted":p.t==="CONDITIONAL"?"conditional":
      (p.t==="REZONED"||p.t==="VARIES")?"rezoned_pd":"unknown";
    if(!cross[p.h])cross[p.h]={{}};
    if(!cross[p.h][col])cross[p.h][col]={{n:0,u:0}};
    cross[p.h][col].n++;cross[p.h][col].u+=p.u;
  }});
  function cell(ht,col){{
    var d=(cross[ht]&&cross[ht][col])||{{n:0,u:0}};
    if(d.n===0)return '<td class="zp-cell" style="text-align:center;color:#cbd5e1">\u2014</td>';
    return '<td class="zp-cell" style="text-align:right">'+d.n+' <span class="zp-desc">('+d.u.toLocaleString()+' units)</span></td>';
  }}
  var html='<div class="zp-section"><div class="zp-cat">Project Summary</div>';
  html+='<table class="zp-table"><tr class="zp-hdr"><th>Housing Type</th>';
  COL_LABELS.forEach(function(c){{html+='<th style="text-align:right;color:'+c[1]+'">'+c[0]+'</th>'}});
  html+='<th style="text-align:right">Total</th></tr>';
  HT_ORDER.forEach(function(ht){{
    if(!cross[ht])return;
    var tn=0,tu=0;
    COL_KEYS.forEach(function(c){{var d=(cross[ht]&&cross[ht][c])||{{n:0,u:0}};tn+=d.n;tu+=d.u}});
    html+='<tr class="zp-row"><td class="zp-cell" style="font-weight:600">'+ht+'</td>';
    COL_KEYS.forEach(function(c){{html+=cell(ht,c)}});
    html+='<td class="zp-cell" style="text-align:right;font-weight:600">'+tn+' <span class="zp-desc">('+tu.toLocaleString()+')</span></td></tr>';
  }});
  var tot={{}};COL_KEYS.forEach(function(c){{tot[c]={{n:0,u:0}};
    for(var ht in cross){{var d=(cross[ht][c])||{{n:0,u:0}};tot[c].n+=d.n;tot[c].u+=d.u}}
  }});
  var gn=0,gu=0;COL_KEYS.forEach(function(c){{gn+=tot[c].n;gu+=tot[c].u}});
  html+='<tr style="border-top:2px solid #cbd5e1"><td class="zp-cell" style="font-weight:700">Total</td>';
  COL_KEYS.forEach(function(c){{
    html+='<td class="zp-cell" style="text-align:right;font-weight:700">'+tot[c].n+' <span class="zp-desc">('+tot[c].u.toLocaleString()+')</span></td>';
  }});
  html+='<td class="zp-cell" style="text-align:right;font-weight:700">'+gn+' <span class="zp-desc">('+gu.toLocaleString()+')</span></td></tr>';
  html+='</table></div>';
  document.getElementById("stats-body").innerHTML=html;
}}
function initDateFilter(){{
  var keys=allKeys();
  if(keys.length===0)return;
  fillSel(document.getElementById("df-from"),keys,0);
  fillSel(document.getElementById("df-to"),keys,keys.length-1);
  applyFilters();
}}
function setGran(g){{
  gran=g;
  document.getElementById("df-month").className="df-btn"+(g==="month"?" df-active":"");
  document.getElementById("df-year").className="df-btn"+(g==="year"?" df-active":"");
  initDateFilter();
}}
function getCheckedUseTypes(){{
  var s=new Set();
  document.querySelectorAll('input[name=usetype]:checked').forEach(function(cb){{
    s.add(cb.value);
  }});
  return s;
}}
function getCheckedOutcomes(){{
  var s=new Set();
  document.querySelectorAll('input[name=outcome]:checked').forEach(function(cb){{
    s.add(cb.value);
  }});
  return s;
}}
function applyFilters(){{
  var from=document.getElementById("df-from").value;
  var to=document.getElementById("df-to").value;
  var useTypes=getCheckedUseTypes();
  var outcomes=getCheckedOutcomes();
  var shown=0;
  markers.forEach(function(mk){{
    var k=mk._date?dateKey(mk._date):"";
    var dateOk=k&&k>=from&&k<=to;
    var typeOk=useTypes.has(mk._useType);
    var outcomeOk=outcomes.has(mk._outcome);
    if(dateOk&&typeOk&&outcomeOk){{
      if(!m.hasLayer(mk))mk.addTo(m);
      shown++;
    }}else{{
      if(m.hasLayer(mk))mk.remove();
    }}
  }});
  document.getElementById("df-count").textContent=shown+"/"+markers.length;
  buildStats(from,to,useTypes,outcomes);
  buildList();
  pushHash();
}}
var USE_LABELS={{"PERMITTED":"Permitted","CONDITIONAL":"Conditional","REZONED":"Rezoned","VARIES":"Varies (PD)","UNKNOWN":"Unknown"}};
function buildList(){{
  var body=document.getElementById("list-body");
  if(!body)return;
  var from=document.getElementById("df-from").value;
  var to=document.getElementById("df-to").value;
  var useTypes=getCheckedUseTypes();
  var outcomes=getCheckedOutcomes();
  var filtered=allRows.filter(function(r){{
    var k=r.d?(gran==="year"?r.d.slice(0,4):r.d.slice(0,7)):"";
    return k&&k>=from&&k<=to&&useTypes.has(r.t)&&outcomes.has(r.o||"BUILT");
  }});
  var sortKey=document.getElementById("list-sort").value;
  if(sortKey==="date")filtered.sort(function(a,b){{return b.d.localeCompare(a.d)}});
  else if(sortKey==="units")filtered.sort(function(a,b){{return b.u-a.u}});
  else filtered.sort(function(a,b){{return a.n.localeCompare(b.n)}});
  document.getElementById("list-count").textContent=filtered.length+" projects";
  var h='<table class="list-table"><tr><th>Date</th><th>Name</th><th>Units</th><th>Type</th><th>Zoning</th><th>Use</th></tr>';
  filtered.forEach(function(r,i){{
    var cls=r.lat!==null?' class="list-clickable"':' class="list-nomap"';
    var data=r.lat!==null?' data-lat="'+r.lat+'" data-lng="'+r.lng+'"':'';
    h+='<tr'+cls+data+'><td>'+r.d+'</td><td>'+r.n+'</td><td>'+r.u+'</td><td>'+r.h+'</td><td>'+r.z+'</td><td>'+(USE_LABELS[r.t]||r.t)+'</td></tr>';
  }});
  h+='</table>';
  body.innerHTML=h;
  body.querySelectorAll("tr.list-clickable").forEach(function(tr){{
    tr.onclick=function(){{
      var lat=parseFloat(this.dataset.lat);
      var lng=parseFloat(this.dataset.lng);
      m.flyTo([lat,lng],16);
      markers.forEach(function(mk){{
        var ll=mk.getLatLng();
        if(Math.abs(ll.lat-lat)<0.0001&&Math.abs(ll.lng-lng)<0.0001)mk.openPopup();
      }});
    }};
  }});
}}
function openListPanel(){{
  document.getElementById("list-panel").classList.add("open");
  document.getElementById("zoning-panel").classList.remove("open");
  document.getElementById("list-btn").style.display="none";
  document.getElementById("zoning-btn").style.display="none";
  buildList();
}}
function closeListPanel(){{
  document.getElementById("list-panel").classList.remove("open");
  document.getElementById("list-btn").style.display="";
  document.getElementById("zoning-btn").style.display="";
}}
function openZoningPanel(){{
  document.getElementById("zoning-panel").classList.add("open");
  document.getElementById("list-panel").classList.remove("open");
  document.getElementById("list-btn").style.display="none";
  document.getElementById("zoning-btn").style.display="none";
}}
function closeZoningPanel(){{
  document.getElementById("zoning-panel").classList.remove("open");
  document.getElementById("list-btn").style.display="";
  document.getElementById("zoning-btn").style.display="";
}}
function pushHash(){{
  var from=document.getElementById("df-from").value;
  var to=document.getElementById("df-to").value;
  var use=Array.from(getCheckedUseTypes()).sort().join(",");
  var outc=Array.from(getCheckedOutcomes()).sort().join(",");
  var sort=document.getElementById("list-sort").value;
  var h="g="+gran+"&from="+encodeURIComponent(from)+"&to="+encodeURIComponent(to)+"&use="+encodeURIComponent(use)+"&outc="+encodeURIComponent(outc)+"&sort="+sort;
  history.replaceState(null,null,"#"+h);
}}
function loadHash(){{
  var h=location.hash.slice(1);
  if(!h)return false;
  var p={{}};
  h.split("&").forEach(function(kv){{var s=kv.split("=");if(s.length===2)p[s[0]]=decodeURIComponent(s[1])}});
  if(p.g&&(p.g==="year"||p.g==="month")){{
    gran=p.g;
    document.getElementById("df-month").className="df-btn"+(gran==="month"?" df-active":"");
    document.getElementById("df-year").className="df-btn"+(gran==="year"?" df-active":"");
  }}
  var keys=allKeys();
  if(keys.length===0)return false;
  fillSel(document.getElementById("df-from"),keys,0);
  fillSel(document.getElementById("df-to"),keys,keys.length-1);
  if(p.from){{var fi=keys.indexOf(p.from);if(fi>=0)document.getElementById("df-from").selectedIndex=fi}}
  if(p.to){{var ti=keys.indexOf(p.to);if(ti>=0)document.getElementById("df-to").selectedIndex=ti}}
  if(p.use){{
    var enabled=new Set(p.use.split(","));
    document.querySelectorAll('input[name=usetype]').forEach(function(cb){{
      cb.checked=enabled.has(cb.value);
    }});
  }}
  if(p.outc){{
    var oe=new Set(p.outc.split(","));
    document.querySelectorAll('input[name=outcome]').forEach(function(cb){{
      cb.checked=oe.has(cb.value);
    }});
  }}
  if(p.sort){{
    var sel=document.getElementById("list-sort");
    if(sel){{for(var i=0;i<sel.options.length;i++){{if(sel.options[i].value===p.sort){{sel.selectedIndex=i;break}}}}}}
  }}
  applyFilters();
  return true;
}}
if(!loadHash())initDateFilter();
var _tCat="use",_tMetric="buildings",_tChart=null;
function openTrends(){{
  document.getElementById("trends-overlay").classList.add("open");
  if(!_tChart)buildTrendsChart();
}}
function closeTrends(){{
  document.getElementById("trends-overlay").classList.remove("open");
}}
function setTrendCat(cat,btn){{
  _tCat=cat;
  document.querySelectorAll(".tr-cat").forEach(function(b){{b.classList.remove("tr-active");}});
  btn.classList.add("tr-active");
  buildTrendsChart();
}}
function setTrendMetric(m,btn){{
  _tMetric=m;
  document.querySelectorAll(".tr-metric").forEach(function(b){{b.classList.remove("tr-active");}});
  btn.classList.add("tr-active");
  buildTrendsChart();
}}
function buildTrendsChart(){{
  var src=_tCat==="zoning"?allRows:allProj;
  var catKey={{use:"t",housing:"h",zoning:"z"}}[_tCat];
  var colorMap={{use:CHART_COLORS_USE,housing:CHART_COLORS_HOUSING,zoning:CHART_COLORS_ZONE}}[_tCat];
  var yearSet=new Set(allProj.map(function(p){{return p.d.slice(0,4);}}));
  var years=Array.from(yearSet).sort();
  var valSet=new Set(src.map(function(p){{return p[catKey];}}).filter(Boolean));
  var catVals=Array.from(valSet).sort();
  var agg={{}};
  catVals.forEach(function(cv){{
    agg[cv]={{}};
    years.forEach(function(y){{agg[cv][y]={{b:0,u:0}};}});
  }});
  src.forEach(function(p){{
    var yr=p.d.slice(0,4),cv=p[catKey];
    if(!cv||!agg[cv]||!agg[cv][yr])return;
    agg[cv][yr].b++;
    agg[cv][yr].u+=(p.u||0);
  }});
  var mk=_tMetric==="units"?"u":"b";
  var datasets=catVals.map(function(cv){{
    return {{
      label:cv,
      data:years.map(function(y){{return agg[cv][y][mk];}}),
      backgroundColor:colorMap[cv]||"#888",
    }};
  }});
  if(_tChart)_tChart.destroy();
  _tChart=new Chart(document.getElementById("trends-canvas"),{{
    type:"bar",
    data:{{labels:years,datasets:datasets}},
    options:{{
      responsive:true,maintainAspectRatio:true,
      plugins:{{
        legend:{{position:"bottom",labels:{{color:"#ccc",padding:16}}}},
        tooltip:{{callbacks:{{label:function(ctx){{return " "+ctx.dataset.label+": "+ctx.raw;}}}}}},
      }},
      scales:{{
        x:{{stacked:true,ticks:{{color:"#aaa"}},grid:{{color:"#2a2a2a"}}}},
        y:{{stacked:true,ticks:{{color:"#aaa"}},grid:{{color:"#2a2a2a"}},
           title:{{display:true,color:"#aaa",text:_tMetric==="units"?"Total Units":"Building Count"}}}},
      }},
    }},
  }});
}}
if(window.innerWidth<=768){{
  ['legend','stats-panel','filter-panel'].forEach(function(id){{
    var el=document.getElementById(id);
    if(el)el.classList.add('collapsed');
    var tog=document.getElementById(id.replace('-panel','')+'-toggle');
    if(!tog)tog=document.getElementById(id+'-toggle');
    if(tog)tog.style.display='block';
  }});
  document.getElementById('legend-toggle').style.display='block';
  document.getElementById('stats-toggle').style.display='block';
  document.getElementById('filter-toggle').style.display='block';
}}"""


# ---------------------------------------------------------------------------
# HTML template assembly
# ---------------------------------------------------------------------------

def _build_header_html(total, total_units, mapped):
    return f"""\
<div id="header">
  <div>
    <h1>Madison WI Multi-Family Housing Permits (2015\u20132026)</h1>
    <div class="stats">
      <span>{total} projects</span>
      <span>{total_units:,} total units</span>
      <span>{mapped} mapped</span>
      <span>Size = unit count (log scale)</span>
    </div>
  </div>
  <button id="trends-btn" onclick="openTrends()">Trends \u2197</button>
</div>"""


def _build_filter_panel_html():
    return """\
  <button id="filter-toggle" class="map-overlay-btn" onclick="document.getElementById('filter-panel').classList.remove('collapsed');this.style.display='none'">Filters</button>
  <div id="filter-panel" class="map-overlay">
    <button class="map-overlay-close" onclick="this.parentElement.classList.add('collapsed');document.getElementById('filter-toggle').style.display='block'">&times;</button>
    <div class="df-row">
      <span class="df-label">Date</span>
      <span class="df-toggle">
        <button id="df-month" class="df-btn" onclick="setGran('month')">Month</button>
        <button id="df-year" class="df-btn df-active" onclick="setGran('year')">Year</button>
      </span>
      <select id="df-from" onchange="applyFilters()"></select>
      <span class="df-sep">to</span>
      <select id="df-to" onchange="applyFilters()"></select>
    </div>
    <div class="df-row">
      <span class="df-label">Use type</span>
      <label class="df-cb"><input type="checkbox" name="usetype" value="PERMITTED" checked onchange="applyFilters()"><span style="color:#16a34a">Permitted</span></label>
      <label class="df-cb"><input type="checkbox" name="usetype" value="CONDITIONAL" checked onchange="applyFilters()"><span style="color:#d97706">Conditional</span></label>
      <label class="df-cb"><input type="checkbox" name="usetype" value="REZONED" checked onchange="applyFilters()"><span style="color:#ef4444">Rezoned</span></label>
      <label class="df-cb"><input type="checkbox" name="usetype" value="VARIES" checked onchange="applyFilters()"><span style="color:#ef4444">PD</span></label>
      <label class="df-cb"><input type="checkbox" name="usetype" value="UNKNOWN" checked onchange="applyFilters()"><span style="color:#6b7280">Unknown</span></label>
      <span id="df-count" class="df-count"></span>
    </div>
    <div class="df-row">
      <span class="df-label">Outcome</span>
      <label class="df-cb"><input type="checkbox" name="outcome" value="BUILT" checked onchange="applyFilters()"><span style="color:#10b981">Built</span></label>
      <label class="df-cb"><input type="checkbox" name="outcome" value="ACTIVE" checked onchange="applyFilters()"><span style="color:#d97706">Active</span></label>
      <label class="df-cb"><input type="checkbox" name="outcome" value="DID_NOT_PROCEED" checked onchange="applyFilters()"><span style="color:#ef4444">Did Not Proceed</span></label>
    </div>
  </div>"""


def _build_list_button_and_panel():
    return """\
  <button id="list-btn" onclick="openListPanel()">Project List</button>
  <div id="list-panel">
    <button id="list-close" onclick="closeListPanel()">&times;</button>
    <div id="list-header">
      <span id="list-title">Project List</span>
      <select id="list-sort" onchange="buildList()">
        <option value="date">Date (newest)</option>
        <option value="units">Units (most)</option>
        <option value="name">Name (A-Z)</option>
      </select>
      <span id="list-count"></span>
    </div>
    <div id="list-body"></div>
  </div>"""


def _build_zoning_button_and_panel(zoning_panel_html):
    return f"""\
  <button id="zoning-btn" onclick="openZoningPanel()">Zoning Reference</button>
  <div id="zoning-panel">
    <button id="panel-close" onclick="closeZoningPanel()">&times;</button>
    <div id="panel-title">City of Madison Zoning District Summary</div>
    <div id="panel-note">
      Source: Zoning District Summary, October 17, 2025. Density = max dwelling units/acre.
      Stories marked * allow additional with Conditional Use approval.
      "Height Map" = determined by Downtown Height Map. "By plan" = determined by Master Plan / PD.
      Contact: zoning@cityofmadison.com | 608-266-4551
    </div>
    {zoning_panel_html}
  </div>"""


def _build_trends_html():
    return """\
<div id="trends-overlay">
  <div id="trends-hdr">
    <span class="trends-title">Annual Trends</span>
    <div class="trends-ctrl-group">
      <button class="tr-cat tr-active" onclick="setTrendCat('use',this)">Use Type</button>
      <button class="tr-cat" onclick="setTrendCat('housing',this)">Housing</button>
      <button class="tr-cat" onclick="setTrendCat('zoning',this)">Zoning</button>
    </div>
    <div class="trends-ctrl-group">
      <button class="tr-metric tr-active" onclick="setTrendMetric('buildings',this)">Buildings</button>
      <button class="tr-metric" onclick="setTrendMetric('units',this)">Units</button>
    </div>
    <button id="trends-close" onclick="closeTrends()">&times; Close</button>
  </div>
  <div id="trends-body">
    <canvas id="trends-canvas"></canvas>
  </div>
</div>"""


def build_page_html(total, total_units, mapped, legend_html,
                    zoning_panel_html, map_js):
    """Assemble the full HTML page from pre-built components."""
    header = _build_header_html(total, total_units, mapped)
    filter_panel = _build_filter_panel_html()
    list_section = _build_list_button_and_panel()
    zoning_section = _build_zoning_button_and_panel(zoning_panel_html)
    trends_overlay = _build_trends_html()

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Madison WI Multi-Family Housing Permits (2015\u20132026)</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect x='8' y='20' width='48' height='40' rx='2' fill='%234a90d9'/%3E%3Crect x='4' y='16' width='56' height='8' rx='2' fill='%23356bad'/%3E%3Crect x='14' y='28' width='8' height='8' rx='1' fill='%23ffe066'/%3E%3Crect x='28' y='28' width='8' height='8' rx='1' fill='%23ffe066'/%3E%3Crect x='42' y='28' width='8' height='8' rx='1' fill='%23ffe066'/%3E%3Crect x='14' y='42' width='8' height='8' rx='1' fill='%23ffe066'/%3E%3Crect x='28' y='42' width='8' height='8' rx='1' fill='%23ffe066'/%3E%3Crect x='42' y='42' width='8' height='8' rx='1' fill='%23ffe066'/%3E%3C/svg%3E">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<link rel="stylesheet" href="style.css"/>
</head>
<body style="display:flex;flex-direction:column;min-height:100vh">
{header}
{trends_overlay}
<div id="map-wrap">
  <button id="legend-toggle" class="map-overlay-btn" onclick="document.getElementById('legend').classList.remove('collapsed');this.style.display='none'">Legend</button>
  <div id="legend" class="map-overlay">
    <button class="map-overlay-close" onclick="this.parentElement.classList.add('collapsed');document.getElementById('legend-toggle').style.display='block'">&times;</button>
    {legend_html}
  </div>
  <button id="stats-toggle" class="map-overlay-btn" onclick="document.getElementById('stats-panel').classList.remove('collapsed');this.style.display='none'">Project Summary</button>
  <div id="stats-panel" class="map-overlay">
    <button class="map-overlay-close" onclick="this.parentElement.classList.add('collapsed');document.getElementById('stats-toggle').style.display='block'">&times;</button>
    <div id="stats-body"></div>
  </div>
{filter_panel}
{list_section}
{zoning_section}
  <div id="map"></div>
</div>
<footer id="site-footer">
  <div class="footer-inner">
    <p class="footer-license">Released under the <a href="https://opensource.org/licenses/MIT" target="_blank">MIT License</a>.</p>
    <p class="footer-disclaimer"><strong>Data sources:</strong> Permit records from the <a href="https://www.cityofmadison.com/dpced/bi/" target="_blank">City of Madison Building Inspection Division</a>. Zoning data from <a href="https://geodata.wisc.edu/" target="_blank">Madison/Dane County GIS</a>. Transit routes from <a href="https://www.cityofmadison.com/metro" target="_blank">Metro Transit GTFS</a>. Geocoding via <a href="https://nominatim.openstreetmap.org/" target="_blank">OpenStreetMap Nominatim</a>.</p>
    <p class="footer-disclaimer"><strong>Classification logic:</strong> Permitted vs. Conditional Use is determined by rule-based matching of each project's unit count against the density ranges defined in Madison's zoning code for its district. Project outcomes (Built, Active, Did Not Proceed) are inferred from permit status and date. Some projects could not be geocoded to a map location and are excluded from the map but included in summary statistics. These classifications are automated approximations and may contain errors. This site is not an official City of Madison resource.</p>
  </div>
</footer>
<script>
{map_js}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open(INPUT_CSV, newline="") as f:
        rows = list(csv.DictReader(f))

    mappable = [r for r in rows if r.get("lat") and r.get("lng")]
    total = len(rows)
    mapped = len(mappable)
    total_units = sum(int(r["units"]) for r in rows if r.get("units"))
    zoning_codes_used = sorted(set(r.get("zoning", "") for r in rows))

    # Build data payloads
    markers = build_marker_data(mappable)
    all_projects = build_all_projects_data(rows)
    all_rows = build_all_rows_data(rows)
    transit_json = load_transit_json()

    # Build HTML fragments
    legend_html = build_legend_html(zoning_codes_used)
    zoning_info = load_zoning_info()
    zoning_panel_html = build_zoning_panel_html(zoning_info)

    # Build JS and assemble page
    markers_json = json.dumps(markers)
    all_projects_json = json.dumps(all_projects)
    all_rows_json = json.dumps(all_rows)
    map_js = _build_map_js(markers_json, all_projects_json, all_rows_json, transit_json)
    page_html = build_page_html(
        total, total_units, mapped, legend_html, zoning_panel_html, map_js
    )

    with open(OUTPUT_HTML, "w") as f:
        f.write(page_html)

    print(f"Generated {OUTPUT_HTML}: {total} projects, {mapped} mapped, "
          f"{total_units:,} total units")


if __name__ == "__main__":
    main()
