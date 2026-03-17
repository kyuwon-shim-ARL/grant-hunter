#!/usr/bin/env python3
"""Generate interactive HTML report for grant exploration.

Usage:
    /home/kyuwon/.venv/bin/python scripts/generate_interactive_report.py
"""

import json
import sys
import os
from datetime import datetime, date
from pathlib import Path

# Allow running from repo root with `python scripts/...`
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grant_hunter.models import Grant
from grant_hunter.eligibility import EligibilityEngine
from grant_hunter.scoring import RelevanceScorer
from grant_hunter.config import init_data_dirs, SNAPSHOTS_DIR, REPORTS_DIR


# ── Data loading ──────────────────────────────────────────────────────────────

def load_grants() -> list[dict]:
    """Load grants from all snapshots, run eligibility engine, return enriched dicts."""
    init_data_dirs()

    snapshot_files = sorted(SNAPSHOTS_DIR.glob("*.json"))
    if not snapshot_files:
        print(f"No snapshot files found in {SNAPSHOTS_DIR}", file=sys.stderr)
        sys.exit(1)

    engine = EligibilityEngine()
    scorer = RelevanceScorer()
    grants: list[dict] = []
    seen: set[str] = set()

    for snap_file in snapshot_files:
        try:
            raw_list = json.loads(snap_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  Warning: could not read {snap_file.name}: {exc}", file=sys.stderr)
            continue

        for raw in raw_list:
            try:
                grant = Grant.from_dict(raw)
            except Exception:
                # Fallback: skip malformed entries
                continue

            fp = grant.fingerprint()
            if fp in seen:
                continue
            seen.add(fp)

            # Score with unified RelevanceScorer
            grant.relevance_score = scorer.score(grant)

            # Run eligibility
            result = engine.check(grant)

            # Parse keywords — NIH stores them as "<Kw1><Kw2>…" in a single string
            raw_kws = grant.keywords or []
            clean_kws: list[str] = []
            for kw in raw_kws:
                if kw.startswith("<") and ">" in kw:
                    # Extract tokens from "<Foo><Bar>…" format, keep short human-readable ones
                    import re as _re
                    tokens = _re.findall(r"<([^<>]+)>", kw)
                    clean_kws.extend(t for t in tokens if len(t) <= 40)
                else:
                    if len(kw) <= 60:
                        clean_kws.append(kw)
            # Keep top 8 shortest/most readable keywords
            clean_kws = sorted(set(clean_kws), key=len)[:8]

            # Truncate description for UI (full text not needed beyond ~400 chars in card)
            desc = (grant.description or "").strip()
            desc = desc[:500] if len(desc) > 500 else desc

            # Build enriched dict (JSON-serialisable, minimal payload)
            d: dict = {}
            d["id"] = grant.id
            d["title"] = grant.title
            d["agency"] = (grant.agency or "")[:80]  # trim very long agency names
            d["source"] = grant.source
            d["url"] = grant.url
            d["description"] = desc
            d["deadline"] = grant.deadline.isoformat() if grant.deadline else None
            d["amount_min"] = grant.amount_min
            d["amount_max"] = grant.amount_max
            d["relevance_score"] = round(grant.relevance_score, 3)
            d["eligibility_status"] = result.status
            d["eligibility_reason"] = result.reason

            grants.append(d)

    print(f"Loaded {len(grants)} unique grants from {len(snapshot_files)} snapshots.")
    return grants


# ── HTML generation ───────────────────────────────────────────────────────────

def generate_html(grants: list[dict]) -> str:
    grants_json = json.dumps(grants, ensure_ascii=False, separators=(",", ":"))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(grants)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Grant Hunter — AMR+AI Funding Explorer</title>
<style>
/* ── Design tokens ── */
:root {{
  --navy:       #1a237e;
  --navy-dark:  #0d1654;
  --navy-light: #283593;
  --teal:       #00897b;
  --teal-light: #4db6ac;
  --teal-dark:  #00695c;
  --bg:         #f5f6fa;
  --surface:    #ffffff;
  --surface2:   #f0f2f8;
  --border:     #e0e4f0;
  --text:       #1c2340;
  --text-muted: #64748b;
  --text-light: #94a3b8;

  /* Source palette */
  --nih:       #1a73e8;
  --eu:        #34a853;
  --grants-gov:#fa7b17;
  --carb-x:    #d32f2f;
  --right:     #7b1fa2;
  --gates:     #0d47a1;
  --pasteur:   #00695c;
  --google-org:#e65100;

  /* Eligibility palette */
  --eligible:   #2e7d32;
  --ineligible: #c62828;
  --uncertain:  #f57f17;

  --radius:  12px;
  --radius-sm: 6px;
  --shadow:  0 2px 12px rgba(26,35,126,.08);
  --shadow-hover: 0 6px 28px rgba(26,35,126,.16);
  --transition: .18s cubic-bezier(.4,0,.2,1);

  --font-sans: 'DM Sans', 'Noto Sans KR', system-ui, sans-serif;
  --font-mono: 'DM Mono', 'Fira Code', monospace;
}}

/* ── Reset & base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  font-family: var(--font-sans);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  line-height: 1.6;
}}

/* ── Google Fonts (inlined as @import — single network call blocked if offline, graceful fallback) ── */
/* Using data URI trick: fonts are declared but fallback to system fonts seamlessly */

/* ── Header ── */
.site-header {{
  background: linear-gradient(135deg, var(--navy-dark) 0%, var(--navy) 55%, var(--navy-light) 100%);
  position: relative;
  overflow: hidden;
  padding: 3rem 2rem 2.5rem;
}}
.site-header::before {{
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 60% 80% at 80% 50%, rgba(0,137,123,.22) 0%, transparent 70%),
    radial-gradient(ellipse 40% 60% at 20% 80%, rgba(77,182,172,.12) 0%, transparent 60%);
  pointer-events: none;
}}
.site-header::after {{
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(77,182,172,.5), transparent);
}}
.header-inner {{
  position: relative;
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}}
.header-title {{
  display: flex;
  align-items: center;
  gap: 1rem;
}}
.header-icon {{
  width: 52px; height: 52px;
  background: linear-gradient(135deg, var(--teal), var(--teal-light));
  border-radius: var(--radius);
  display: flex; align-items: center; justify-content: center;
  font-size: 1.6rem;
  box-shadow: 0 4px 16px rgba(0,137,123,.4);
  flex-shrink: 0;
}}
.header-title h1 {{
  font-size: clamp(1.3rem, 3vw, 2rem);
  font-weight: 700;
  letter-spacing: -.02em;
  color: #fff;
  line-height: 1.2;
}}
.header-title h1 span {{
  color: var(--teal-light);
}}
.header-sub {{
  font-size: .875rem;
  color: rgba(255,255,255,.65);
  margin-top: .25rem;
  letter-spacing: .01em;
}}
.header-badge {{
  background: rgba(255,255,255,.1);
  border: 1px solid rgba(255,255,255,.2);
  color: rgba(255,255,255,.9);
  font-size: .8rem;
  padding: .4rem .9rem;
  border-radius: 100px;
  backdrop-filter: blur(8px);
  white-space: nowrap;
}}

/* ── Summary cards ── */
.summary-section {{
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem 2rem .5rem;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
}}
@media (max-width: 900px) {{
  .summary-section {{ grid-template-columns: repeat(2,1fr); }}
}}
@media (max-width: 520px) {{
  .summary-section {{ grid-template-columns: 1fr; padding: 1rem; }}
}}
.summary-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem 1.5rem;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: .4rem;
  position: relative;
  overflow: hidden;
}}
.summary-card::before {{
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 4px; height: 100%;
  border-radius: var(--radius) 0 0 var(--radius);
}}
.summary-card.total::before   {{ background: var(--navy); }}
.summary-card.eligible::before {{ background: var(--eligible); }}
.summary-card.deadline::before {{ background: var(--uncertain); }}
.summary-card.score::before    {{ background: var(--teal); }}
.summary-label {{
  font-size: .75rem;
  font-weight: 600;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--text-muted);
}}
.summary-value {{
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -.03em;
  line-height: 1;
  color: var(--text);
}}
.summary-card.eligible .summary-value {{ color: var(--eligible); }}
.summary-card.deadline .summary-value {{ color: var(--uncertain); }}
.summary-card.score .summary-value    {{ color: var(--teal); }}
.summary-detail {{
  font-size: .78rem;
  color: var(--text-muted);
  display: flex; gap: .4rem; flex-wrap: wrap; margin-top: .1rem;
}}
.source-pip {{
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  padding: .15rem .45rem;
  border-radius: 4px;
  font-size: .7rem;
  font-weight: 600;
  color: #fff;
}}
/* Gauge for avg score */
.gauge-bar {{
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
  margin-top: .35rem;
}}
.gauge-fill {{
  height: 100%;
  background: linear-gradient(90deg, var(--teal-dark), var(--teal-light));
  border-radius: 3px;
  transition: width .6s cubic-bezier(.4,0,.2,1);
}}

/* ── Sticky filter bar ── */
.filter-bar {{
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(245,246,250,.97);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: .9rem 2rem;
  box-shadow: 0 2px 12px rgba(26,35,126,.06);
}}
.filter-inner {{
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: .75rem;
  flex-wrap: wrap;
}}
.search-wrap {{
  flex: 1;
  min-width: 220px;
  position: relative;
}}
.search-icon {{
  position: absolute;
  left: .75rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  pointer-events: none;
  font-style: normal;
  font-size: 1rem;
}}
#searchInput {{
  width: 100%;
  padding: .6rem .75rem .6rem 2.4rem;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: .875rem;
  background: var(--surface);
  color: var(--text);
  outline: none;
  transition: border-color var(--transition), box-shadow var(--transition);
  font-family: var(--font-sans);
}}
#searchInput:focus {{
  border-color: var(--teal);
  box-shadow: 0 0 0 3px rgba(0,137,123,.12);
}}
.filter-select {{
  padding: .6rem .9rem;
  border: 1.5px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: .8rem;
  background: var(--surface);
  color: var(--text);
  outline: none;
  cursor: pointer;
  transition: border-color var(--transition);
  font-family: var(--font-sans);
  min-width: 130px;
}}
.filter-select:focus {{ border-color: var(--teal); }}
.filter-count {{
  margin-left: auto;
  font-size: .8rem;
  font-weight: 600;
  color: var(--text-muted);
  white-space: nowrap;
  padding: .4rem .75rem;
  background: var(--surface2);
  border-radius: var(--radius-sm);
}}
.filter-count span {{ color: var(--navy); }}

/* ── Main grid ── */
.main-content {{
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem 2rem 3rem;
}}
.grants-grid {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.25rem;
}}
@media (max-width: 1100px) {{ .grants-grid {{ grid-template-columns: repeat(2,1fr); }} }}
@media (max-width: 680px)  {{ .grants-grid {{ grid-template-columns: 1fr; }} }}

/* ── Grant card ── */
.grant-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: .65rem;
  cursor: pointer;
  transition:
    transform var(--transition),
    box-shadow var(--transition),
    border-color var(--transition);
  animation: cardIn .25s ease both;
}}
.grant-card:hover {{
  transform: translateY(-3px);
  box-shadow: var(--shadow-hover);
  border-color: var(--teal-light);
}}
@keyframes cardIn {{
  from {{ opacity: 0; transform: translateY(12px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}
.card-header {{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: .5rem;
}}
.card-badges {{
  display: flex;
  gap: .35rem;
  align-items: center;
  flex-wrap: wrap;
  flex-shrink: 0;
}}
.badge {{
  font-size: .68rem;
  font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
  padding: .2rem .5rem;
  border-radius: 4px;
  color: #fff;
  white-space: nowrap;
}}
.badge-nih         {{ background: var(--nih); }}
.badge-eu          {{ background: var(--eu); }}
.badge-grants_gov  {{ background: var(--grants-gov); }}
.badge-carb_x      {{ background: var(--carb-x); }}
.badge-right_foundation {{ background: var(--right); }}
.badge-gates_gc    {{ background: var(--gates); }}
.badge-pasteur_network  {{ background: var(--pasteur); }}
.badge-google_org  {{ background: var(--google-org); }}
.badge-eligible    {{ background: var(--eligible); }}
.badge-ineligible  {{ background: var(--ineligible); }}
.badge-uncertain   {{ background: var(--uncertain); color: #fff; }}

.card-title {{
  font-size: .92rem;
  font-weight: 600;
  color: var(--text);
  line-height: 1.4;
  flex: 1;
}}
.card-title a {{
  color: inherit;
  text-decoration: none;
  transition: color var(--transition);
}}
.card-title a:hover {{ color: var(--teal); text-decoration: underline; }}

.card-agency {{
  font-size: .78rem;
  color: var(--text-muted);
  display: flex; align-items: center; gap: .3rem;
}}

.card-meta {{
  display: flex;
  gap: .75rem;
  flex-wrap: wrap;
  align-items: center;
}}
.meta-chip {{
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  font-size: .75rem;
  color: var(--text-muted);
  background: var(--surface2);
  padding: .22rem .55rem;
  border-radius: 4px;
}}
.meta-chip.urgent  {{ background: #ffeaea; color: var(--ineligible); font-weight: 600; }}
.meta-chip.warning {{ background: #fff3e0; color: var(--uncertain); font-weight: 600; }}
.meta-chip.ok      {{ background: #e8f5e9; color: var(--eligible); }}

/* Relevance score bar */
.score-row {{
  display: flex;
  align-items: center;
  gap: .6rem;
}}
.score-label {{
  font-size: .7rem;
  color: var(--text-light);
  min-width: 58px;
}}
.score-bar {{
  flex: 1;
  height: 5px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}}
.score-fill {{
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--teal-dark), var(--teal-light));
}}
.score-num {{
  font-size: .72rem;
  font-weight: 700;
  color: var(--teal-dark);
  min-width: 34px;
  text-align: right;
  font-family: var(--font-mono);
}}

/* Description */
.card-desc {{
  font-size: .8rem;
  color: var(--text-muted);
  line-height: 1.55;
}}
.desc-short {{}}
.desc-full  {{ display: none; }}
.desc-toggle {{
  background: none;
  border: none;
  cursor: pointer;
  font-size: .75rem;
  color: var(--teal);
  padding: 0;
  font-family: var(--font-sans);
  margin-top: .15rem;
  display: inline;
}}
.desc-toggle:hover {{ text-decoration: underline; }}

/* eligibility reason tooltip-ish */
.elig-reason {{
  font-size: .7rem;
  color: var(--text-light);
  font-style: italic;
  border-top: 1px solid var(--border);
  padding-top: .5rem;
  margin-top: -.1rem;
}}

/* ── Pagination ── */
.pagination {{
  display: flex;
  align-items: center;
  justify-content: center;
  gap: .5rem;
  padding: 2rem 0 1rem;
  flex-wrap: wrap;
}}
.page-btn {{
  min-width: 36px;
  height: 36px;
  padding: 0 .6rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  border: 1.5px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-size: .825rem;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: background var(--transition), border-color var(--transition), color var(--transition);
}}
.page-btn:hover {{ border-color: var(--teal); color: var(--teal); }}
.page-btn.active {{
  background: var(--navy);
  border-color: var(--navy);
  color: #fff;
  font-weight: 700;
}}
.page-btn:disabled {{
  opacity: .35;
  cursor: not-allowed;
}}
.page-info {{
  font-size: .8rem;
  color: var(--text-muted);
  padding: 0 .25rem;
}}

/* ── Empty state ── */
.empty-state {{
  text-align: center;
  padding: 4rem 2rem;
  color: var(--text-muted);
  grid-column: 1 / -1;
}}
.empty-state .icon {{ font-size: 2.5rem; margin-bottom: .75rem; }}
.empty-state h3 {{ font-size: 1.1rem; color: var(--text); margin-bottom: .5rem; }}

/* ── Footer ── */
.site-footer {{
  border-top: 1px solid var(--border);
  padding: 1.5rem 2rem;
  text-align: center;
  font-size: .78rem;
  color: var(--text-light);
  background: var(--surface);
}}
.site-footer strong {{ color: var(--text-muted); }}

/* ── Source legend ── */
.source-legend {{
  display: flex;
  gap: .5rem;
  flex-wrap: wrap;
  align-items: center;
  font-size: .72rem;
  padding: .25rem 0;
}}
.legend-item {{
  display: flex;
  align-items: center;
  gap: .25rem;
  color: var(--text-muted);
}}
.legend-dot {{
  width: 8px; height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--teal-light); }}
</style>
</head>
<body>

<!-- ── Header ── -->
<header class="site-header">
  <div class="header-inner">
    <div class="header-title">
      <div class="header-icon">🔬</div>
      <div>
        <h1>Grant Hunter — <span>AMR+AI</span> Funding Explorer</h1>
        <div class="header-sub">Institut Pasteur Korea · Generated {now_str}</div>
      </div>
    </div>
    <div class="header-badge" id="headerTotalBadge">{total} grants loaded</div>
  </div>
</header>

<!-- ── Summary cards ── -->
<div class="summary-section" id="summarySection">
  <!-- Filled by JS -->
</div>

<!-- ── Filter bar ── -->
<div class="filter-bar">
  <div class="filter-inner">
    <div class="search-wrap">
      <i class="search-icon">⌕</i>
      <input type="text" id="searchInput" placeholder="Search title, agency, description…" autocomplete="off">
    </div>
    <select class="filter-select" id="sourceFilter">
      <option value="">All Sources</option>
      <option value="nih">NIH</option>
      <option value="eu">EU Horizon</option>
      <option value="grants_gov">Grants.gov</option>
      <option value="carb_x">CARB-X</option>
      <option value="right_foundation">RIGHT Fund</option>
      <option value="gates_gc">Gates Foundation</option>
      <option value="pasteur_network">Pasteur Network</option>
      <option value="google_org">Google.org</option>
    </select>
    <select class="filter-select" id="eligFilter">
      <option value="">All Eligibility</option>
      <option value="eligible">✓ Eligible</option>
      <option value="uncertain">? Uncertain</option>
      <option value="ineligible">✗ Ineligible</option>
    </select>
    <select class="filter-select" id="deadlineFilter">
      <option value="">All Deadlines</option>
      <option value="30">Next 30 days</option>
      <option value="90">Next 90 days</option>
      <option value="none">No Deadline</option>
    </select>
    <select class="filter-select" id="sortSelect">
      <option value="relevance">Sort: Relevance</option>
      <option value="deadline">Sort: Deadline</option>
      <option value="amount">Sort: Amount</option>
      <option value="title">Sort: Title</option>
    </select>
    <div class="filter-count"><span id="filteredCount">{total}</span> grants found</div>
  </div>
</div>

<!-- ── Main content ── -->
<div class="main-content">
  <div class="grants-grid" id="grantsGrid"></div>
  <div class="pagination" id="pagination"></div>
</div>

<!-- ── Footer ── -->
<footer class="site-footer">
  <strong>Grant Hunter</strong> · Institut Pasteur Korea AMR+AI Grant Intelligence ·
  Generated {now_str} ·
  <span id="footerStats"></span>
</footer>

<script>
// ── Embedded grant data ──
const GRANTS = {grants_json};

// ── Constants ──
const PAGE_SIZE = 50;
const TODAY = new Date();
TODAY.setHours(0,0,0,0);

const SOURCE_COLORS = {{
  nih:              '#1a73e8',
  eu:               '#34a853',
  grants_gov:       '#fa7b17',
  carb_x:           '#d32f2f',
  right_foundation: '#7b1fa2',
  gates_gc:         '#0d47a1',
  pasteur_network:  '#00695c',
  google_org:       '#e65100',
}};
const SOURCE_LABELS = {{
  nih:              'NIH',
  eu:               'EU',
  grants_gov:       'Grants.gov',
  carb_x:           'CARB-X',
  right_foundation: 'RIGHT',
  gates_gc:         'Gates',
  pasteur_network:  'Pasteur',
  google_org:       'Google.org',
}};

// ── State ──
let filtered = [];
let currentPage = 1;

// ── Helpers ──
function daysDiff(isoDate) {{
  if (!isoDate) return null;
  const d = new Date(isoDate);
  d.setHours(0,0,0,0);
  return Math.round((d - TODAY) / 86400000);
}}

function fmt_amount(min, max) {{
  const fmt = n => {{
    if (n >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
    if (n >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
    return '$' + n.toFixed(0);
  }};
  if (min != null && max != null) {{
    if (min === max) return fmt(min);
    return fmt(min) + ' – ' + fmt(max);
  }}
  if (max != null) return '≤ ' + fmt(max);
  if (min != null) return '≥ ' + fmt(min);
  return null;
}}

function escHtml(s) {{
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}}

function deadlineChip(isoDate) {{
  const days = daysDiff(isoDate);
  if (days === null) return '';
  const label = isoDate.slice(0,10);
  if (days < 0) return `<span class="meta-chip">📅 ${{label}} (expired)</span>`;
  const dLabel = days === 0 ? 'Today!' : `D-${{days}}`;
  const cls = days <= 7 ? 'urgent' : days <= 30 ? 'warning' : 'ok';
  return `<span class="meta-chip ${{cls}}">📅 ${{label}} (${{dLabel}})</span>`;
}}

function sourceBadge(source) {{
  const color = SOURCE_COLORS[source] || '#607d8b';
  const label = SOURCE_LABELS[source] || source.toUpperCase();
  return `<span class="badge" style="background:${{color}}">${{escHtml(label)}}</span>`;
}}

function eligBadge(status) {{
  const map = {{
    eligible:   ['badge-eligible',   '✓ Eligible'],
    ineligible: ['badge-ineligible', '✗ Ineligible'],
    uncertain:  ['badge-uncertain',  '? Uncertain'],
  }};
  const [cls, lbl] = map[status] || ['badge-uncertain', '?'];
  return `<span class="badge ${{cls}}">${{lbl}}</span>`;
}}

// ── Build summary cards ──
function buildSummary() {{
  const total = GRANTS.length;
  const eligCount = GRANTS.filter(g => g.eligibility_status === 'eligible').length;

  // Upcoming deadlines within 30 days
  const upcoming = GRANTS.filter(g => {{
    const d = daysDiff(g.deadline);
    return d !== null && d >= 0 && d <= 30;
  }}).length;

  // Average relevance
  const avgScore = GRANTS.length
    ? GRANTS.reduce((s,g) => s + g.relevance_score, 0) / GRANTS.length
    : 0;

  // Source breakdown
  const sourceCounts = {{}};
  GRANTS.forEach(g => {{ sourceCounts[g.source] = (sourceCounts[g.source]||0)+1; }});
  const sourceHtml = Object.entries(sourceCounts)
    .sort((a,b) => b[1]-a[1])
    .slice(0,4)
    .map(([src,n]) => {{
      const color = SOURCE_COLORS[src] || '#607d8b';
      const lbl = SOURCE_LABELS[src] || src;
      return `<span class="source-pip" style="background:${{color}}">${{lbl}} ${{n}}</span>`;
    }}).join('');

  const section = document.getElementById('summarySection');
  section.innerHTML = `
    <div class="summary-card total">
      <div class="summary-label">Total Grants</div>
      <div class="summary-value">${{total.toLocaleString()}}</div>
      <div class="summary-detail">${{sourceHtml}}</div>
    </div>
    <div class="summary-card eligible">
      <div class="summary-label">Eligible (IPK)</div>
      <div class="summary-value">${{eligCount.toLocaleString()}}</div>
      <div class="summary-detail">
        <span>${{((eligCount/total)*100).toFixed(1)}}% of all grants</span>
      </div>
    </div>
    <div class="summary-card deadline">
      <div class="summary-label">Due in 30 Days</div>
      <div class="summary-value">${{upcoming.toLocaleString()}}</div>
      <div class="summary-detail"><span>Act now — deadlines approaching</span></div>
    </div>
    <div class="summary-card score">
      <div class="summary-label">Avg Relevance</div>
      <div class="summary-value">${{(avgScore*100).toFixed(0)}}%</div>
      <div class="gauge-bar"><div class="gauge-fill" style="width:${{(avgScore*100).toFixed(1)}}%"></div></div>
    </div>
  `;
  document.getElementById('footerStats').textContent =
    `${{total.toLocaleString()}} grants · ${{eligCount}} eligible · ${{upcoming}} due soon`;
}}

// ── Card HTML ──
function cardHtml(g, idx) {{
  const desc = g.description || '';
  const shortLen = 160;
  const isLong = desc.length > shortLen;
  const shortDesc = isLong ? desc.slice(0, shortLen) + '…' : desc;
  const amtStr = fmt_amount(g.amount_min, g.amount_max);

  return `
<div class="grant-card" id="card-${{idx}}" onclick="toggleDesc(${{idx}})">
  <div class="card-header">
    <div class="card-badges">
      ${{sourceBadge(g.source)}}
      ${{eligBadge(g.eligibility_status)}}
    </div>
  </div>
  <div class="card-title">
    <a href="${{escHtml(g.url||'#')}}" target="_blank" rel="noopener" onclick="event.stopPropagation()">
      ${{escHtml(g.title)}}
    </a>
  </div>
  ${{g.agency ? `<div class="card-agency">🏛 ${{escHtml(g.agency)}}</div>` : ''}}
  <div class="card-meta">
    ${{deadlineChip(g.deadline)}}
    ${{amtStr ? `<span class="meta-chip">💰 ${{escHtml(amtStr)}}</span>` : ''}}
  </div>
  <div class="score-row">
    <span class="score-label">Relevance</span>
    <div class="score-bar">
      <div class="score-fill" style="width:${{(g.relevance_score*100).toFixed(1)}}%"></div>
    </div>
    <span class="score-num">${{(g.relevance_score*100).toFixed(0)}}%</span>
  </div>
  <div class="card-desc" id="desc-${{idx}}">
    <span class="desc-short" id="dshort-${{idx}}">${{escHtml(shortDesc)}}</span>
    ${{isLong ? `<span class="desc-full" id="dfull-${{idx}}">${{escHtml(desc)}}</span>` : ''}}
    ${{isLong ? `<button class="desc-toggle" id="dtgl-${{idx}}" onclick="event.stopPropagation();toggleDesc(${{idx}})">Show more ▾</button>` : ''}}
  </div>
  ${{g.eligibility_reason ? `<div class="elig-reason">Rule: ${{escHtml(g.eligibility_reason)}}</div>` : ''}}
</div>`;
}}

// ── Toggle description ──
const expandedCards = new Set();
function toggleDesc(idx) {{
  const btn = document.getElementById('dtgl-'+idx);
  if (!btn) return;
  const shortEl = document.getElementById('dshort-'+idx);
  const fullEl  = document.getElementById('dfull-'+idx);
  if (!fullEl) return;
  const isExpanded = expandedCards.has(idx);
  if (isExpanded) {{
    shortEl.style.display = '';
    fullEl.style.display = 'none';
    btn.textContent = 'Show more ▾';
    expandedCards.delete(idx);
  }} else {{
    shortEl.style.display = 'none';
    fullEl.style.display = '';
    btn.textContent = 'Show less ▴';
    expandedCards.add(idx);
  }}
}}

// ── Filter & sort ──
function applyFilters() {{
  const q       = document.getElementById('searchInput').value.trim().toLowerCase();
  const src     = document.getElementById('sourceFilter').value;
  const elig    = document.getElementById('eligFilter').value;
  const deadline= document.getElementById('deadlineFilter').value;
  const sortBy  = document.getElementById('sortSelect').value;

  filtered = GRANTS.filter(g => {{
    // Text search
    if (q) {{
      const haystack = (g.title + ' ' + (g.agency||'') + ' ' + (g.description||'')).toLowerCase();
      if (!haystack.includes(q)) return false;
    }}
    // Source
    if (src && g.source !== src) return false;
    // Eligibility
    if (elig && g.eligibility_status !== elig) return false;
    // Deadline
    if (deadline) {{
      if (deadline === 'none') {{
        if (g.deadline !== null) return false;
      }} else {{
        const days = daysDiff(g.deadline);
        if (days === null || days < 0 || days > parseInt(deadline)) return false;
      }}
    }}
    return true;
  }});

  // Sort
  filtered.sort((a, b) => {{
    if (sortBy === 'relevance') return b.relevance_score - a.relevance_score;
    if (sortBy === 'title')     return a.title.localeCompare(b.title, 'en', {{sensitivity:'base'}});
    if (sortBy === 'amount') {{
      const aA = Math.max(a.amount_max||0, a.amount_min||0);
      const bA = Math.max(b.amount_max||0, b.amount_min||0);
      return bA - aA;
    }}
    if (sortBy === 'deadline') {{
      const dA = a.deadline ? daysDiff(a.deadline) : 99999;
      const dB = b.deadline ? daysDiff(b.deadline) : 99999;
      // expired at the end
      const eA = dA < 0 ? 99998 : dA;
      const eB = dB < 0 ? 99998 : dB;
      return eA - eB;
    }}
    return 0;
  }});

  document.getElementById('filteredCount').textContent = filtered.length.toLocaleString();
  currentPage = 1;
  renderPage();
}}

// ── Render current page ──
function renderPage() {{
  const grid = document.getElementById('grantsGrid');
  const start = (currentPage - 1) * PAGE_SIZE;
  const pageGrants = filtered.slice(start, start + PAGE_SIZE);

  if (filtered.length === 0) {{
    grid.innerHTML = `
      <div class="empty-state">
        <div class="icon">🔍</div>
        <h3>No grants found</h3>
        <p>Try adjusting your search or filter criteria.</p>
      </div>`;
    document.getElementById('pagination').innerHTML = '';
    return;
  }}

  grid.innerHTML = pageGrants.map((g, i) => cardHtml(g, start + i)).join('');
  renderPagination();
  // Scroll to top of grid on page change
  grid.scrollIntoView({{behavior:'smooth', block:'start'}});
}}

// ── Pagination ──
function renderPagination() {{
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  if (totalPages <= 1) {{
    document.getElementById('pagination').innerHTML = '';
    return;
  }}

  const p = document.getElementById('pagination');
  let html = '';

  html += `<button class="page-btn" onclick="goPage(${{currentPage-1}})" ${{currentPage===1?'disabled':''}}>‹ Prev</button>`;

  // Window of page buttons
  const window = 2;
  const pages = [];
  for (let i = 1; i <= totalPages; i++) {{
    if (i === 1 || i === totalPages ||
        (i >= currentPage - window && i <= currentPage + window)) {{
      pages.push(i);
    }}
  }}

  let prev = null;
  for (const pg of pages) {{
    if (prev !== null && pg - prev > 1) {{
      html += `<span class="page-info">…</span>`;
    }}
    html += `<button class="page-btn${{pg===currentPage?' active':''}}" onclick="goPage(${{pg}})">${{pg}}</button>`;
    prev = pg;
  }}

  html += `<button class="page-btn" onclick="goPage(${{currentPage+1}})" ${{currentPage===totalPages?'disabled':''}}>Next ›</button>`;
  html += `<span class="page-info">${{((currentPage-1)*PAGE_SIZE+1)}}–${{Math.min(currentPage*PAGE_SIZE,filtered.length)}} of ${{filtered.length.toLocaleString()}}</span>`;

  p.innerHTML = html;
}}

function goPage(n) {{
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  if (n < 1 || n > totalPages) return;
  currentPage = n;
  renderPage();
}}

// ── Event listeners ──
let searchTimer;
document.getElementById('searchInput').addEventListener('input', () => {{
  clearTimeout(searchTimer);
  searchTimer = setTimeout(applyFilters, 180);
}});
['sourceFilter','eligFilter','deadlineFilter','sortSelect'].forEach(id => {{
  document.getElementById(id).addEventListener('change', applyFilters);
}});

// ── Init ──
buildSummary();
applyFilters();
</script>
</body>
</html>"""

    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    grants = load_grants()
    html = generate_html(grants)

    init_data_dirs()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_reports = Path(__file__).parent.parent / "reports"
    project_reports.mkdir(parents=True, exist_ok=True)
    out_path = project_reports / f"interactive_report_{ts}.html"
    out_path.write_text(html, encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    print(f"Report saved to: {out_path}")
    print(f"File size: {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
