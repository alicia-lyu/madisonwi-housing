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
    "REZONED": "#7c3aed",
    "VARIES": "#7c3aed",
    "UNKNOWN": "#6b7280",
}

USE_TYPE_LABELS = {
    "PERMITTED": "Permitted Use",
    "CONDITIONAL": "Conditional Use",
    "REZONED": "Rezoned",
    "VARIES": "Varies (PD)",
    "UNKNOWN": "Unknown",
}

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
        f'<th style="text-align:right;color:#7c3aed">Rezoned / PD</th>'
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
    """Build HTML for a single row (and optional detail row) in the zoning table."""
    code = z["code"]
    color = zoning_color(code)
    permitted = html.escape(z.get("residential_permitted", "") or "")
    conditional = html.escape(z.get("residential_conditional", "") or "")
    desc_text = (z.get("description") or "").strip()
    row_id = f'zd-{html.escape(code)}'

    if desc_text:
        name_td = (
            f'<td class="zp-name zp-toggle" onclick="'
            f"var r=document.getElementById('{row_id}');"
            f"r.style.display=r.style.display==='none'?'table-row':'none';"
            f"this.querySelector('.zp-arrow').textContent="
            f"r.style.display==='none'?'\\u25B8':'\\u25BE'"
            f'">'
            f'<span class="zp-arrow">&#x25B8;</span>'
            f'<b>{html.escape(z["name"])}</b></td>'
        )
        detail_row = (
            f'<tr id="{row_id}" class="zp-detail" style="display:none">'
            f'<td></td><td colspan="5" class="zp-desc-cell">'
            f'{html.escape(desc_text)}</td></tr>'
        )
    else:
        name_td = (
            f'<td class="zp-name">'
            f'<span class="zp-arrow-placeholder"></span>'
            f'<b>{html.escape(z["name"])}</b></td>'
        )
        detail_row = ""

    return (
        f'<tr class="zp-row">'
        f'<td class="zp-code">'
        f'<span class="zp-dot" style="background:{color}"></span>'
        f'{html.escape(code)}</td>'
        f'{name_td}'
        f'<td class="zp-cell">{permitted}</td>'
        f'<td class="zp-cell">{conditional}</td>'
        f'<td class="zp-cell zp-nowrap">{html.escape(z["max_stories"])}</td>'
        f'<td class="zp-cell zp-nowrap zp-last">{html.escape(z["max_density"])}</td>'
        f'</tr>'
        f'{detail_row}'
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
            f'<th>Code</th><th>District</th><th>Permitted</th>'
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
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# JavaScript template
# ---------------------------------------------------------------------------

def _build_map_js(markers_json, all_projects_json, transit_json):
    """Return the <script> block contents for the Leaflet map.

    This JS is intentionally compact — it only handles map init, marker placement,
    zoom scaling, date filtering, and dynamic stats rebuilding. All heavy computation
    (colors, sizes, popups) is done in Python.
    """
    # Double braces {{ }} are literal JS braces inside the f-string
    return f"""\
var m=L.map("map").setView([43.073,-89.401],12);
L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png",{{
  attribution:'&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom:19}}).addTo(m);
var tr={transit_json};
tr.forEach(function(rt){{
  var opts={{color:rt.color,weight:rt.weight,opacity:0.7}};
  if(rt.dash)opts.dashArray=rt.dash;
  L.polyline(rt.coords,opts).addTo(m).bindPopup(
    '<b>Route '+rt.name+'</b>'
  );
}});
var allProj={all_projects_json};
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
var gran="month";
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
    var o=document.createElement("option");o.value=v;o.text=fmtOpt(v);sel.appendChild(o);
  }});
  sel.selectedIndex=Math.min(idx,opts.length-1);
}}
var HT_ORDER=["Mid-Rise","Mid-Rise Mixed-Use","High-Rise","High-Rise Mixed-Use",
  "Townhouse","Multiplex","Duplex/Triplex"];
var COL_KEYS=["permitted","conditional","rezoned_pd","unknown"];
var COL_LABELS=[["Permitted","#16a34a"],["Conditional","#d97706"],["Rezoned / PD","#7c3aed"],["Unknown","#6b7280"]];
function buildStats(from,to){{
  var cross={{}};
  var fProj=allProj.filter(function(p){{
    var k=gran==="year"?p.d.slice(0,4):p.d.slice(0,7);
    return k&&k>=from&&k<=to;
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
  document.querySelectorAll('#filter-panel input[type=checkbox]:checked').forEach(function(cb){{
    s.add(cb.value);
  }});
  return s;
}}
function applyFilters(){{
  var from=document.getElementById("df-from").value;
  var to=document.getElementById("df-to").value;
  var useTypes=getCheckedUseTypes();
  var shown=0;
  markers.forEach(function(mk){{
    var k=mk._date?dateKey(mk._date):"";
    var dateOk=k&&k>=from&&k<=to;
    var typeOk=useTypes.has(mk._useType);
    if(dateOk&&typeOk){{
      if(!m.hasLayer(mk))mk.addTo(m);
      shown++;
    }}else{{
      if(m.hasLayer(mk))mk.remove();
    }}
  }});
  document.getElementById("df-count").textContent=shown+"/"+markers.length;
  buildStats(from,to);
}}
initDateFilter();"""


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
</div>"""


def _build_filter_panel_html():
    return """\
  <div id="filter-panel" class="map-overlay">
    <div class="df-row">
      <span class="df-label">Date</span>
      <span class="df-toggle">
        <button id="df-month" class="df-btn df-active" onclick="setGran('month')">Month</button>
        <button id="df-year" class="df-btn" onclick="setGran('year')">Year</button>
      </span>
      <select id="df-from" onchange="applyFilters()"></select>
      <span class="df-sep">to</span>
      <select id="df-to" onchange="applyFilters()"></select>
    </div>
    <div class="df-row">
      <span class="df-label">Use type</span>
      <label class="df-cb"><input type="checkbox" value="PERMITTED" checked onchange="applyFilters()"><span style="color:#16a34a">Permitted</span></label>
      <label class="df-cb"><input type="checkbox" value="CONDITIONAL" checked onchange="applyFilters()"><span style="color:#d97706">Conditional</span></label>
      <label class="df-cb"><input type="checkbox" value="REZONED" checked onchange="applyFilters()"><span style="color:#7c3aed">Rezoned</span></label>
      <label class="df-cb"><input type="checkbox" value="VARIES" checked onchange="applyFilters()"><span style="color:#7c3aed">PD</span></label>
      <label class="df-cb"><input type="checkbox" value="UNKNOWN" checked onchange="applyFilters()"><span style="color:#6b7280">Unknown</span></label>
      <span id="df-count" class="df-count"></span>
    </div>
  </div>"""


def _build_zoning_button_and_panel(zoning_panel_html):
    return f"""\
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
  </div>"""


def build_page_html(total, total_units, mapped, legend_html,
                    zoning_panel_html, map_js):
    """Assemble the full HTML page from pre-built components."""
    header = _build_header_html(total, total_units, mapped)
    filter_panel = _build_filter_panel_html()
    zoning_section = _build_zoning_button_and_panel(zoning_panel_html)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Madison WI Multi-Family Housing Permits (2015\u20132026)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="stylesheet" href="style.css"/>
</head>
<body style="display:flex;flex-direction:column;height:100vh">
{header}
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
{zoning_section}
  <div id="map"></div>
</div>
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
    transit_json = load_transit_json()

    # Build HTML fragments
    legend_html = build_legend_html(zoning_codes_used)
    zoning_info = load_zoning_info()
    zoning_panel_html = build_zoning_panel_html(zoning_info)

    # Build JS and assemble page
    markers_json = json.dumps(markers)
    all_projects_json = json.dumps(all_projects)
    map_js = _build_map_js(markers_json, all_projects_json, transit_json)
    page_html = build_page_html(
        total, total_units, mapped, legend_html, zoning_panel_html, map_js
    )

    with open(OUTPUT_HTML, "w") as f:
        f.write(page_html)

    print(f"Generated {OUTPUT_HTML}: {total} projects, {mapped} mapped, "
          f"{total_units:,} total units")


if __name__ == "__main__":
    main()
