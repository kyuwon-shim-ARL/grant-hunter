"""Static HTML dashboard generator for Grant Hunter.

Generates a single self-contained HTML file (CSS + JS inlined) that can be
opened directly in a browser — no server required.

Features:
- Summary cards: total collected, eligible count, average relevance score
- Deadline calendar: upcoming deadlines within 90 days (CSS grid)
- Sortable table: all filtered grants with eligibility colour-coding
- Client-side filters: by source and eligibility status
"""

from __future__ import annotations

import html
import json
import logging
from calendar import monthcalendar, month_name
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from grant_hunter.config import REPORTS_DIR
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

ELIGIBILITY_COLORS = {
    "eligible": "#2e7d32",
    "ineligible": "#c62828",
    "uncertain": "#f57f17",
}

ELIGIBILITY_BG = {
    "eligible": "#e8f5e9",
    "ineligible": "#ffebee",
    "uncertain": "#fff8e1",
}

SOURCE_LABELS = {
    "nih": "NIH",
    "eu": "EU Portal",
    "grants_gov": "Grants.gov",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def _fmt_amount(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:.0f}"


def _days_until(d: Optional[date]) -> Optional[int]:
    if d is None:
        return None
    return (d - date.today()).days


def _deadline_label(d: Optional[date]) -> str:
    if d is None:
        return "N/A"
    days = _days_until(d)
    if days is None:
        return "N/A"
    if days < 0:
        return f"Expired ({d})"
    if days == 0:
        return f"TODAY ({d})"
    if days <= 7:
        return f"⚠ {d} ({days}d)"
    return str(d)


def _source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source.upper())


# ── Calendar section ──────────────────────────────────────────────────────────

def _build_calendar(grants: List[Grant]) -> str:
    today = date.today()
    horizon = today + timedelta(days=90)

    # Group grants with a deadline in the next 90 days by (year, month, day)
    by_date: Dict[date, List[Grant]] = {}
    for g in grants:
        if g.deadline and today <= g.deadline <= horizon:
            by_date.setdefault(g.deadline, []).append(g)

    if not by_date:
        return "<p style='color:#888'>No deadlines in the next 90 days.</p>"

    # Determine months to show
    months_to_show = set()
    d = date(today.year, today.month, 1)
    while d <= date(horizon.year, horizon.month, 1):
        months_to_show.add((d.year, d.month))
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)

    blocks = ""
    for year, month in sorted(months_to_show):
        weeks = monthcalendar(year, month)
        cells = ""
        for week in weeks:
            for day_num in week:
                if day_num == 0:
                    cells += '<div class="cal-cell empty"></div>'
                    continue
                try:
                    cell_date = date(year, month, day_num)
                except ValueError:
                    cells += '<div class="cal-cell empty"></div>'
                    continue
                grants_today = by_date.get(cell_date, [])
                is_today = cell_date == today
                cls = "cal-cell"
                if is_today:
                    cls += " today"
                if grants_today:
                    cls += " has-deadline"
                tooltip = ""
                if grants_today:
                    names = "; ".join(g.title[:40] for g in grants_today[:3])
                    tooltip = f' title="{_esc(names)}"'
                badge = f'<span class="cal-badge">{len(grants_today)}</span>' if grants_today else ""
                cells += f'<div class="{cls}"{tooltip}>{day_num}{badge}</div>'

        blocks += f"""
<div class="cal-month">
  <div class="cal-month-title">{month_name[month]} {year}</div>
  <div class="cal-header">
    <div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div>
    <div>Fri</div><div>Sat</div><div>Sun</div>
  </div>
  <div class="cal-grid">{cells}</div>
</div>"""

    return f'<div class="cal-wrapper">{blocks}</div>'


# ── Table rows ────────────────────────────────────────────────────────────────

def _grant_to_json_row(g: Grant, eligibility: str, elig_reason: str, norm_score: float,
                       breakdown: dict | None = None) -> dict:
    amount = g.amount_max or g.amount_min
    return {
        "id": _esc(g.id),
        "title": _esc(g.title),
        "url": _esc(g.url or "#"),
        "agency": _esc(g.agency),
        "source": _source_label(g.source),
        "deadline": g.deadline.isoformat() if g.deadline else "",
        "deadline_label": _deadline_label(g.deadline),
        "days_until": _days_until(g.deadline),
        "amount": amount or 0,
        "amount_label": _fmt_amount(amount),
        "score": round(norm_score * 100, 1),
        "eligibility": eligibility,
        "elig_reason": _esc(elig_reason),
        "desc": _esc((g.description or "")[:200]),
        "desc_full": _esc(g.description or ""),
        "duration": g.duration_months,
        "keywords": [_esc(k) for k in (g.keywords or [])],
        "breakdown": breakdown or {},
    }


# ── Main generator ────────────────────────────────────────────────────────────

def generate_dashboard(
    all_filtered: List[Grant],
    eligibility_map: Dict[str, str],       # grant.fingerprint() -> status
    eligibility_reason_map: Dict[str, str], # grant.fingerprint() -> reason
    score_map: Dict[str, float],           # grant.fingerprint() -> 0-1 score
    stats: dict,
    run_date: Optional[datetime] = None,
) -> Path:
    """Generate dashboard HTML and return its path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dt = run_date or datetime.utcnow()
    filename = f"dashboard_{run_dt.strftime('%Y%m%d_%H%M%S')}.html"
    path = REPORTS_DIR / filename

    # Summary stats
    total = len(all_filtered)
    eligible_count = sum(1 for g in all_filtered if eligibility_map.get(g.fingerprint()) == "eligible")
    uncertain_count = sum(1 for g in all_filtered if eligibility_map.get(g.fingerprint()) == "uncertain")
    ineligible_count = sum(1 for g in all_filtered if eligibility_map.get(g.fingerprint()) == "ineligible")
    scores = [score_map.get(g.fingerprint(), 0.0) for g in all_filtered]
    avg_score = round(sum(scores) / len(scores) * 100, 1) if scores else 0.0
    total_collected = sum(s.get("collected", 0) for s in stats.values())

    # Build JSON data for JS table
    from grant_hunter.scoring import RelevanceScorer
    scorer = RelevanceScorer()
    rows = []
    for g in all_filtered:
        fp = g.fingerprint()
        rows.append(_grant_to_json_row(
            g,
            eligibility_map.get(fp, "uncertain"),
            eligibility_reason_map.get(fp, ""),
            score_map.get(fp, 0.0),
            breakdown=scorer.score_breakdown(g),
        ))

    rows_json = json.dumps(rows, ensure_ascii=False)

    calendar_html = _build_calendar(all_filtered)
    run_str = run_dt.strftime("%Y-%m-%d %H:%M UTC")

    sources = sorted(set(_source_label(g.source) for g in all_filtered))
    source_options = "\n".join(
        f'<label><input type="checkbox" class="src-filter" value="{s}" checked> {s}</label>'
        for s in sources
    )

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Grant Hunter Dashboard – {run_str}</title>
<style>
/* ── Reset & Base ── */
*, *::before, *::after {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  margin: 0; padding: 0; background: #f0f2f5; color: #1a1a2e;
}}
a {{ color: #1a73e8; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
h1, h2, h3 {{ margin: 0 0 12px; }}

/* ── Layout ── */
.page {{ max-width: 1400px; margin: 0 auto; padding: 24px 20px; }}
header {{
  background: #1a1a2e; color: white;
  padding: 16px 24px; margin-bottom: 24px;
  border-radius: 10px;
  display: flex; justify-content: space-between; align-items: center;
}}
header h1 {{ font-size: 1.4em; margin: 0; color: white; }}
.meta {{ color: #aaa; font-size: 0.85em; }}

/* ── Cards ── */
.cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
.card {{
  background: white; border-radius: 10px;
  padding: 20px 28px; flex: 1; min-width: 140px;
  box-shadow: 0 1px 6px rgba(0,0,0,.08);
  text-align: center;
}}
.card-num {{ font-size: 2.4em; font-weight: 700; line-height: 1; }}
.card-label {{ font-size: 0.82em; color: #888; margin-top: 4px; }}
.card-eligible {{ color: #2e7d32; }}
.card-uncertain {{ color: #f57f17; }}
.card-ineligible {{ color: #c62828; }}
.card-score {{ color: #1a73e8; }}
.card-total {{ color: #1a1a2e; }}

/* ── Section ── */
.section {{
  background: white; border-radius: 10px;
  padding: 20px 24px; margin-bottom: 24px;
  box-shadow: 0 1px 6px rgba(0,0,0,.08);
}}
.section h2 {{ font-size: 1.1em; color: #444; border-bottom: 2px solid #eee; padding-bottom: 8px; }}

/* ── Calendar ── */
.cal-wrapper {{ display: flex; gap: 20px; flex-wrap: wrap; }}
.cal-month {{ min-width: 220px; }}
.cal-month-title {{ font-weight: 600; font-size: 0.95em; margin-bottom: 6px; color: #1a1a2e; }}
.cal-header, .cal-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }}
.cal-header > div {{ text-align: center; font-size: 0.7em; color: #888; padding: 2px 0; font-weight: 600; }}
.cal-cell {{
  position: relative; text-align: center; padding: 4px 2px;
  font-size: 0.78em; border-radius: 4px; min-height: 28px;
  cursor: default;
}}
.cal-cell.empty {{ background: transparent; }}
.cal-cell.today {{ background: #e3f2fd; font-weight: 700; }}
.cal-cell.has-deadline {{ background: #fff3e0; border: 1px solid #ffb74d; cursor: pointer; }}
.cal-cell.has-deadline:hover {{ background: #ffe0b2; }}
.cal-badge {{
  position: absolute; top: 1px; right: 2px;
  background: #e65100; color: white;
  font-size: 0.65em; width: 14px; height: 14px;
  border-radius: 50%; display: flex; align-items: center; justify-content: center;
  line-height: 1;
}}

/* ── Filters ── */
.filters {{
  display: flex; gap: 24px; flex-wrap: wrap; align-items: flex-start;
  margin-bottom: 16px;
}}
.filter-group {{ display: flex; flex-direction: column; gap: 6px; }}
.filter-group label {{ font-size: 0.75em; color: #888; text-transform: uppercase;
  letter-spacing: 0.5px; font-weight: 600; }}
.filter-group .checks {{ display: flex; gap: 12px; flex-wrap: wrap; }}
.filter-group .checks label {{ font-size: 0.85em; color: #333; text-transform: none;
  letter-spacing: 0; font-weight: normal; cursor: pointer; }}
input[type=checkbox] {{ cursor: pointer; }}
input[type=text] {{
  border: 1px solid #ddd; border-radius: 6px;
  padding: 6px 10px; font-size: 0.88em; width: 240px;
  outline: none;
}}
input[type=text]:focus {{ border-color: #1a73e8; }}

/* ── Table ── */
#grants-table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.86em; }}
thead th {{
  background: #1a1a2e; color: white; padding: 10px 12px;
  text-align: left; white-space: nowrap; cursor: pointer;
  user-select: none;
}}
thead th:hover {{ background: #2d2d44; }}
thead th.sorted-asc::after {{ content: " ▲"; font-size: 0.75em; }}
thead th.sorted-desc::after {{ content: " ▼"; font-size: 0.75em; }}
tbody tr:hover td {{ background: #f8f9ff; }}
td {{ padding: 9px 12px; border-bottom: 1px solid #eee; vertical-align: top; }}
.td-title {{ max-width: 280px; }}
.td-title a {{ font-weight: 500; }}
.td-desc {{ color: #666; font-size: 0.8em; margin-top: 3px; }}
.td-agency {{ color: #555; max-width: 160px; }}
.td-deadline {{ white-space: nowrap; font-weight: 600; }}
.td-deadline.urgent {{ color: #c62828; }}
.td-deadline.expired {{ color: #aaa; font-weight: normal; }}
.td-amount {{ white-space: nowrap; text-align: right; }}
.td-score {{ text-align: center; font-weight: 600; }}
.td-eligibility {{ white-space: nowrap; }}
.elig-badge {{
  display: inline-block; padding: 3px 10px; border-radius: 12px;
  font-size: 0.78em; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px;
}}
.src-badge {{
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 0.75em; background: #e3f2fd; color: #1565c0;
}}
.score-bar {{
  display: inline-block; height: 6px; border-radius: 3px;
  background: #1a73e8; margin-left: 6px; vertical-align: middle;
}}
#row-count {{ font-size: 0.82em; color: #888; margin-bottom: 8px; }}

/* ── Checkbox & Action Bar ── */
.cb-col {{ width: 36px; text-align: center; }}
.action-bar {{
  display: none; align-items: center; gap: 12px;
  background: #1a1a2e; color: white; padding: 10px 16px;
  border-radius: 8px; margin-bottom: 12px; font-size: 0.88em;
}}
.action-bar.visible {{ display: flex; }}
.action-bar span {{ font-weight: 600; }}
.action-bar button {{
  background: white; color: #1a1a2e; border: none;
  padding: 6px 14px; border-radius: 6px; cursor: pointer;
  font-size: 0.85em; font-weight: 600;
}}
.action-bar button:hover {{ background: #e3f2fd; }}

/* ── Detail Row ── */
.detail-row td {{ background: #fafbff; padding: 16px 20px; border-bottom: 2px solid #dde; }}
.detail-content {{ display: flex; gap: 24px; flex-wrap: wrap; }}
.detail-main {{ flex: 2; min-width: 300px; }}
.detail-side {{ flex: 1; min-width: 220px; }}
.detail-desc {{ color: #444; line-height: 1.6; margin-bottom: 12px; font-size: 0.9em; max-height: 200px; overflow-y: auto; }}
.detail-meta {{ display: flex; flex-direction: column; gap: 4px; }}
.detail-meta-item {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #eee; font-size: 0.85em; }}
.detail-meta-item .lbl {{ color: #888; }}
.detail-meta-item .val {{ font-weight: 600; text-align: right; max-width: 60%; }}

/* ── Score Breakdown ── */
.breakdown-bar {{ display: flex; gap: 2px; height: 8px; border-radius: 4px; overflow: hidden; margin-top: 6px; }}
.breakdown-seg {{ height: 100%; }}
.breakdown-legend {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; }}
.breakdown-legend span {{ font-size: 0.75em; display: flex; align-items: center; gap: 4px; }}
.breakdown-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}

/* ── Keywords ── */
.kw-tag {{
  display: inline-block; background: #e8eaf6; color: #283593;
  padding: 2px 8px; border-radius: 10px; font-size: 0.72em; margin: 2px;
}}

/* ── External Link Icon ── */
.ext-icon {{ font-size: 0.75em; margin-left: 3px; opacity: 0.4; }}
a:hover .ext-icon {{ opacity: 1; }}

/* ── Calendar Buttons ── */
.cal-btns {{ margin-top: 8px; display: flex; gap: 6px; }}
.cal-btn {{
  display: inline-block; padding: 4px 10px; border-radius: 4px;
  font-size: 0.78em; cursor: pointer; text-decoration: none;
  background: #1a73e8; color: white; border: none; font-weight: 500;
}}
.cal-btn:hover {{ background: #1557b0; color: white; text-decoration: none; }}
.cal-btn.gcal {{ background: #34a853; }}
.cal-btn.gcal:hover {{ background: #2d8e47; }}

/* ── Detail Toggle ── */
.detail-toggle {{
  font-size: 0.75em; color: #1a73e8; cursor: pointer; text-decoration: none;
  display: inline-block; margin-top: 3px;
}}
.detail-toggle:hover {{ text-decoration: underline; }}

/* ── Print ── */
@media print {{
  .filters, header {{ display: none; }}
  .section {{ box-shadow: none; border: 1px solid #ddd; }}
  body {{ background: white; }}
}}

/* ── Responsive ── */
@media (max-width: 768px) {{
  .cards {{ flex-direction: column; }}
  .card {{ min-width: unset; }}
  .cal-wrapper {{ flex-direction: column; }}
}}
</style>
</head>
<body>
<div class="page">

<header>
  <h1>Grant Hunter Dashboard</h1>
  <span class="meta">Generated: {run_str} | AMR + AI focus</span>
</header>

<!-- Summary Cards -->
<div class="cards">
  <div class="card">
    <div class="card-num card-total">{total_collected}</div>
    <div class="card-label">Total Collected</div>
  </div>
  <div class="card">
    <div class="card-num card-total">{total}</div>
    <div class="card-label">Keyword-Filtered</div>
  </div>
  <div class="card">
    <div class="card-num card-eligible">{eligible_count}</div>
    <div class="card-label">Eligible (IPK)</div>
  </div>
  <div class="card">
    <div class="card-num card-uncertain">{uncertain_count}</div>
    <div class="card-label">Uncertain</div>
  </div>
  <div class="card">
    <div class="card-num card-ineligible">{ineligible_count}</div>
    <div class="card-label">Ineligible</div>
  </div>
  <div class="card">
    <div class="card-num card-score">{avg_score}</div>
    <div class="card-label">Avg Relevance Score</div>
  </div>
</div>

<!-- Deadline Calendar -->
<div class="section">
  <h2>Upcoming Deadlines (next 90 days)</h2>
  {calendar_html}
</div>

<!-- Grant Table -->
<div class="section">
  <h2>All Relevant Grants ({total} total)</h2>

  <div class="filters">
    <div class="filter-group">
      <label>Search</label>
      <input type="text" id="search-box" placeholder="Filter by title, agency…">
    </div>
    <div class="filter-group">
      <label>Source</label>
      <div class="checks" id="src-checks">
        {source_options}
      </div>
    </div>
    <div class="filter-group">
      <label>Eligibility</label>
      <div class="checks" id="elig-checks">
        <label><input type="checkbox" class="elig-filter" value="eligible" checked> Eligible</label>
        <label><input type="checkbox" class="elig-filter" value="uncertain" checked> Uncertain</label>
        <label><input type="checkbox" class="elig-filter" value="ineligible" checked> Ineligible</label>
      </div>
    </div>
  </div>

  <div class="action-bar" id="action-bar">
    <span id="selected-count">0 selected</span>
    <button onclick="window._gh.exportICS()">Download .ics</button>
    <button onclick="window._gh.exportGCal()">Open in Google Calendar</button>
    <button onclick="window._gh.clearSelection()">Clear</button>
  </div>

  <div id="row-count"></div>

  <div id="grants-table-wrap">
    <table id="grants-table">
      <thead>
        <tr>
          <th class="cb-col"><input type="checkbox" id="select-all" title="Select all"></th>
          <th data-col="title">Title</th>
          <th data-col="agency">Agency / Source</th>
          <th data-col="deadline_sort">Deadline</th>
          <th data-col="amount">Amount</th>
          <th data-col="score">Score</th>
          <th data-col="eligibility">Eligibility</th>
        </tr>
      </thead>
      <tbody id="table-body"></tbody>
    </table>
  </div>
</div>

<p style="text-align:center;color:#aaa;font-size:0.8em;padding:12px 0">
  Grant Hunter Dashboard – automated AMR+AI grant discovery for Institut Pasteur Korea
</p>

</div><!-- .page -->

<script>
(function() {{
  var DATA = {rows_json};
  var dataById = {{}};
  DATA.forEach(function(r) {{ dataById[r.id] = r; }});

  var selected = {{}};
  var expandedId = null;
  var sortCol = 'score';
  var sortDir = -1;

  function getVal(row, col) {{
    if (col === 'deadline_sort') return row.days_until === null ? 99999 : row.days_until;
    if (col === 'score') return row.score;
    if (col === 'amount') return row.amount;
    if (col === 'title') return row.title.toLowerCase();
    if (col === 'agency') return (row.agency + row.source).toLowerCase();
    if (col === 'eligibility') return row.eligibility;
    return '';
  }}

  function activeFilters() {{
    var srcs = Array.from(document.querySelectorAll('.src-filter:checked')).map(function(e){{return e.value;}});
    var eligs = Array.from(document.querySelectorAll('.elig-filter:checked')).map(function(e){{return e.value;}});
    var q = document.getElementById('search-box').value.trim().toLowerCase();
    return {{srcs: srcs, eligs: eligs, q: q}};
  }}

  function filterData(f) {{
    return DATA.filter(function(r) {{
      if (f.srcs.indexOf(r.source) === -1) return false;
      if (f.eligs.indexOf(r.eligibility) === -1) return false;
      if (f.q && r.title.toLowerCase().indexOf(f.q) === -1 && r.agency.toLowerCase().indexOf(f.q) === -1) return false;
      return true;
    }});
  }}

  function eligBadge(status, reason) {{
    var colors = {{eligible:'#2e7d32',ineligible:'#c62828',uncertain:'#f57f17'}};
    var bgs = {{eligible:'#e8f5e9',ineligible:'#ffebee',uncertain:'#fff8e1'}};
    var c = colors[status] || '#888';
    var bg = bgs[status] || '#f5f5f5';
    var tip = reason ? ' title="' + reason + '"' : '';
    return '<span class="elig-badge" style="color:' + c + ';background:' + bg + '"' + tip + '>' + status + '</span>';
  }}

  function deadlineCell(row) {{
    var cls = 'td-deadline';
    if (row.days_until !== null) {{
      if (row.days_until < 0) cls += ' expired';
      else if (row.days_until <= 7) cls += ' urgent';
    }}
    return '<td class="' + cls + '">' + row.deadline_label + '</td>';
  }}

  function scoreCell(score) {{
    var w = Math.round(score) + 'px';
    var bar = '<span class="score-bar" style="width:' + w + 'px"></span>';
    return '<td class="td-score">' + score + bar + '</td>';
  }}

  /* ── Score Breakdown ── */
  function breakdownHTML(bd) {{
    if (!bd || !bd.total) return '<div style="color:#aaa;font-size:0.8em">No score data</div>';
    var cats = [
      {{key:'amr',label:'AMR',color:'#e53935'}},
      {{key:'ai',label:'AI',color:'#1e88e5'}},
      {{key:'drug',label:'Drug Discovery',color:'#43a047'}},
      {{key:'amount_bonus',label:'Amount Bonus',color:'#fb8c00'}}
    ];
    var bar = '<div class="breakdown-bar">';
    var legend = '<div class="breakdown-legend">';
    cats.forEach(function(c) {{
      var v = (bd[c.key] || 0) * 100;
      if (v > 0) {{
        bar += '<div class="breakdown-seg" style="width:' + Math.max(v, 4) + '%;background:' + c.color + '" title="' + c.label + ': ' + v.toFixed(0) + '%"></div>';
        legend += '<span><span class="breakdown-dot" style="background:' + c.color + '"></span>' + c.label + ' ' + v.toFixed(0) + '%</span>';
      }}
    }});
    bar += '</div>';
    legend += '</div>';
    return bar + legend;
  }}

  function keywordsHTML(kws) {{
    if (!kws || !kws.length) return '';
    return kws.slice(0, 10).map(function(k) {{ return '<span class="kw-tag">' + k + '</span>'; }}).join('');
  }}

  /* ── Detail Row ── */
  function detailRow(r) {{
    var dur = r.duration ? r.duration + ' months' : 'N/A';
    var calBtns = '';
    if (r.deadline) {{
      var dt = r.deadline.replace(/-/g, '');
      var nd = new Date(r.deadline + 'T00:00:00');
      nd.setDate(nd.getDate() + 1);
      var y = nd.getFullYear(), m = ('0'+(nd.getMonth()+1)).slice(-2), d = ('0'+nd.getDate()).slice(-2);
      var dtEnd = y + m + d;
      var gcalUrl = 'https://calendar.google.com/calendar/render?action=TEMPLATE'
        + '&text=' + encodeURIComponent('Grant Deadline: ' + r.title)
        + '&dates=' + dt + '/' + dtEnd
        + '&details=' + encodeURIComponent('Agency: ' + r.agency + '\\nAmount: ' + r.amount_label + '\\nEligibility: ' + r.eligibility + '\\n\\n' + r.url);
      calBtns = '<div class="cal-btns">'
        + '<a class="cal-btn gcal" href="' + gcalUrl + '" target="_blank">Add to Google Calendar</a>'
        + '<button class="cal-btn" onclick="window._gh.exportICSOne(\\'' + r.id.replace(/'/g, "\\\\'") + '\\')">Download .ics</button>'
        + '</div>';
    }}
    return '<tr class="detail-row"><td></td><td colspan="6">'
      + '<div class="detail-content">'
      + '<div class="detail-main">'
        + '<div class="detail-desc">' + (r.desc_full || r.desc || 'No description available.') + '</div>'
        + (r.keywords && r.keywords.length ? '<div style="margin-bottom:10px"><strong style="font-size:0.8em;color:#888">Matched Keywords</strong><br>' + keywordsHTML(r.keywords) + '</div>' : '')
        + '<div><strong style="font-size:0.8em;color:#888">Why Recommended (Score Breakdown)</strong>' + breakdownHTML(r.breakdown) + '</div>'
      + '</div>'
      + '<div class="detail-side">'
        + '<div class="detail-meta">'
          + '<div class="detail-meta-item"><span class="lbl">Agency</span><span class="val">' + r.agency + '</span></div>'
          + '<div class="detail-meta-item"><span class="lbl">Source</span><span class="val">' + r.source + '</span></div>'
          + '<div class="detail-meta-item"><span class="lbl">Deadline</span><span class="val">' + r.deadline_label + '</span></div>'
          + '<div class="detail-meta-item"><span class="lbl">Amount</span><span class="val">' + r.amount_label + '</span></div>'
          + '<div class="detail-meta-item"><span class="lbl">Duration</span><span class="val">' + dur + '</span></div>'
          + '<div class="detail-meta-item"><span class="lbl">Eligibility</span><span class="val">' + eligBadge(r.eligibility, r.elig_reason) + '</span></div>'
        + '</div>'
        + calBtns
        + '<div style="margin-top:12px"><a href="' + r.url + '" target="_blank" style="font-weight:600;font-size:0.9em">View Original Listing &#8599;</a></div>'
      + '</div>'
      + '</div></td></tr>';
  }}

  /* ── Action Bar ── */
  function updateActionBar() {{
    var cnt = Object.keys(selected).length;
    var bar = document.getElementById('action-bar');
    if (cnt > 0) {{
      bar.classList.add('visible');
      document.getElementById('selected-count').textContent = cnt + ' selected';
    }} else {{
      bar.classList.remove('visible');
    }}
  }}

  function updateSelectAll() {{
    var cbs = document.querySelectorAll('.row-cb');
    var all = cbs.length > 0 && Array.from(cbs).every(function(c) {{ return c.checked; }});
    document.getElementById('select-all').checked = all;
  }}

  /* ── ICS Generation ── */
  function makeICS(grants) {{
    var lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//GrantHunter//EN','CALSCALE:GREGORIAN'];
    grants.forEach(function(g) {{
      if (!g.deadline) return;
      var dt = g.deadline.replace(/-/g, '');
      var nd = new Date(g.deadline + 'T00:00:00');
      nd.setDate(nd.getDate() + 1);
      var y = nd.getFullYear(), m = ('0'+(nd.getMonth()+1)).slice(-2), d = ('0'+nd.getDate()).slice(-2);
      lines.push('BEGIN:VEVENT');
      lines.push('DTSTART;VALUE=DATE:' + dt);
      lines.push('DTEND;VALUE=DATE:' + y + m + d);
      lines.push('SUMMARY:Grant Deadline: ' + g.title.substring(0, 75));
      lines.push('DESCRIPTION:Agency: ' + g.agency + '\\nAmount: ' + g.amount_label + '\\nEligibility: ' + g.eligibility + '\\n' + g.url);
      lines.push('URL:' + g.url);
      lines.push('END:VEVENT');
    }});
    lines.push('END:VCALENDAR');
    return lines.join('\\r\\n');
  }}

  function downloadFile(content, filename, mime) {{
    var blob = new Blob([content], {{type: mime}});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }}

  /* ── Render ── */
  function renderRows(rows) {{
    var tbody = document.getElementById('table-body');
    var html = '';
    rows.forEach(function(r) {{
      var ck = selected[r.id] ? ' checked' : '';
      var arrow = expandedId === r.id ? '&#9660;' : '&#9654;';
      html += '<tr' + (expandedId === r.id ? ' style="background:#f0f2ff"' : '') + '>';
      html += '<td class="cb-col"><input type="checkbox" class="row-cb" data-id="' + r.id + '"' + ck + '></td>';
      html += '<td class="td-title"><a href="' + r.url + '" target="_blank">' + r.title + '<span class="ext-icon">&#8599;</span></a>';
      if (r.desc) html += '<div class="td-desc">' + r.desc + '</div>';
      html += '<a href="#" class="detail-toggle" data-id="' + r.id + '">' + arrow + ' Details</a>';
      html += '</td>';
      html += '<td class="td-agency">' + r.agency + '<br><span class="src-badge">' + r.source + '</span></td>';
      html += deadlineCell(r);
      html += '<td class="td-amount">' + r.amount_label + '</td>';
      html += scoreCell(r.score);
      html += '<td class="td-eligibility">' + eligBadge(r.eligibility, r.elig_reason) + '</td>';
      html += '</tr>';
      if (expandedId === r.id) html += detailRow(r);
    }});
    tbody.innerHTML = html;
    document.getElementById('row-count').textContent = rows.length + ' grants shown';

    // Bind detail toggles
    tbody.querySelectorAll('.detail-toggle').forEach(function(a) {{
      a.addEventListener('click', function(e) {{
        e.preventDefault();
        expandedId = expandedId === a.dataset.id ? null : a.dataset.id;
        sortAndRender();
      }});
    }});

    // Bind row checkboxes
    tbody.querySelectorAll('.row-cb').forEach(function(cb) {{
      cb.addEventListener('change', function() {{
        if (cb.checked) {{ selected[cb.dataset.id] = true; }}
        else {{ delete selected[cb.dataset.id]; }}
        updateActionBar();
        updateSelectAll();
      }});
    }});
  }}

  function sortAndRender() {{
    var f = activeFilters();
    var rows = filterData(f);
    rows.sort(function(a, b) {{
      var av = getVal(a, sortCol), bv = getVal(b, sortCol);
      if (av < bv) return sortDir;
      if (av > bv) return -sortDir;
      return 0;
    }});
    renderRows(rows);
    document.querySelectorAll('thead th').forEach(function(th) {{
      th.classList.remove('sorted-asc', 'sorted-desc');
      if (th.dataset.col === sortCol) {{
        th.classList.add(sortDir === -1 ? 'sorted-desc' : 'sorted-asc');
      }}
    }});
  }}

  // Header sort click
  document.querySelectorAll('thead th[data-col]').forEach(function(th) {{
    th.addEventListener('click', function() {{
      var col = th.dataset.col;
      if (sortCol === col) {{ sortDir = -sortDir; }}
      else {{ sortCol = col; sortDir = -1; }}
      sortAndRender();
    }});
  }});

  // Select-all checkbox
  document.getElementById('select-all').addEventListener('change', function() {{
    var checked = this.checked;
    document.querySelectorAll('.row-cb').forEach(function(cb) {{
      cb.checked = checked;
      if (checked) {{ selected[cb.dataset.id] = true; }}
      else {{ delete selected[cb.dataset.id]; }}
    }});
    updateActionBar();
  }});

  // Filter change
  document.querySelectorAll('.src-filter, .elig-filter').forEach(function(el) {{
    el.addEventListener('change', sortAndRender);
  }});
  document.getElementById('search-box').addEventListener('input', sortAndRender);

  // Expose global API for action bar buttons
  window._gh = {{
    exportICS: function() {{
      var grants = Object.keys(selected).map(function(id) {{ return dataById[id]; }}).filter(function(g) {{ return g && g.deadline; }});
      if (!grants.length) {{ alert('No grants with deadlines selected.'); return; }}
      downloadFile(makeICS(grants), 'grant_deadlines.ics', 'text/calendar');
    }},
    exportGCal: function() {{
      var grants = Object.keys(selected).map(function(id) {{ return dataById[id]; }}).filter(function(g) {{ return g && g.deadline; }});
      if (!grants.length) {{ alert('No grants with deadlines selected.'); return; }}
      if (grants.length === 1) {{
        var g = grants[0];
        var dt = g.deadline.replace(/-/g, '');
        var nd = new Date(g.deadline + 'T00:00:00');
        nd.setDate(nd.getDate() + 1);
        var y = nd.getFullYear(), m = ('0'+(nd.getMonth()+1)).slice(-2), d = ('0'+nd.getDate()).slice(-2);
        var url = 'https://calendar.google.com/calendar/render?action=TEMPLATE'
          + '&text=' + encodeURIComponent('Grant Deadline: ' + g.title)
          + '&dates=' + dt + '/' + y + m + d
          + '&details=' + encodeURIComponent('Agency: ' + g.agency + '\\nAmount: ' + g.amount_label + '\\n' + g.url);
        window.open(url, '_blank');
      }} else {{
        downloadFile(makeICS(grants), 'grant_deadlines.ics', 'text/calendar');
        alert('Downloaded .ics file with ' + grants.length + ' events. Import it into Google Calendar (Settings > Import).');
      }}
    }},
    exportICSOne: function(id) {{
      var g = dataById[id];
      if (!g || !g.deadline) return;
      downloadFile(makeICS([g]), 'grant_' + id.substring(0, 20) + '.ics', 'text/calendar');
    }},
    clearSelection: function() {{
      selected = {{}};
      document.querySelectorAll('.row-cb').forEach(function(cb) {{ cb.checked = false; }});
      document.getElementById('select-all').checked = false;
      updateActionBar();
    }}
  }};

  // Initial render
  sortAndRender();
}})();
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)

    logger.info("Dashboard written: %s", path)
    return path
