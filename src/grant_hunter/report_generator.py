"""HTML report generator for filtered grants."""

from __future__ import annotations

import html
import logging
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from grant_hunter.config import REPORTS_DIR, DEADLINE_WARN_DAYS
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

SOURCE_COLORS = {
    "nih": "#1a73e8",
    "eu": "#34a853",
    "grants_gov": "#fa7b17",
}

SOURCE_LABELS = {
    "nih": "NIH",
    "eu": "EU Portal",
    "grants_gov": "Grants.gov",
}


def _fmt_amount(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:.0f}"


def _fmt_deadline(d: Optional[date]) -> str:
    if d is None:
        return "N/A"
    return d.strftime("%Y-%m-%d")


def _is_urgent(d: Optional[date]) -> bool:
    if d is None:
        return False
    delta = (d - date.today()).days
    return 0 <= delta <= DEADLINE_WARN_DAYS


def _deadline_class(d: Optional[date]) -> str:
    if d is None:
        return ""
    delta = (d - date.today()).days
    if delta < 0:
        return "expired"
    if delta <= DEADLINE_WARN_DAYS:
        return "urgent"
    return ""


def _source_badge(source: str) -> str:
    color = SOURCE_COLORS.get(source, "#888")
    label = SOURCE_LABELS.get(source, source.upper())
    return f'<span class="badge" style="background:{color}">{label}</span>'


def generate_html_report(
    new_grants: List[Grant],
    changed_grants: List[Grant],
    all_filtered: List[Grant],
    stats: dict,
    run_date: Optional[datetime] = None,
) -> Path:
    """Generate HTML report and return its path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dt = run_date or datetime.utcnow()
    filename = f"report_{run_dt.strftime('%Y%m%d_%H%M%S')}.html"
    path = REPORTS_DIR / filename

    new_fps = {g.fingerprint() for g in new_grants}

    # Sort combined highlights by deadline
    highlights = sorted(
        new_grants + changed_grants,
        key=lambda g: g.deadline or date.max,
    )

    html_content = _build_html(highlights, all_filtered, stats, run_dt, new_fps)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html_content)

    logger.info("Report written: %s", path)
    return path


def _grant_row(g: Grant, tag: str = "") -> str:
    dl_class = _deadline_class(g.deadline)
    badge = _source_badge(g.source)
    tag_html = f'<span class="tag tag-{tag}">{tag.upper()}</span>' if tag else ""
    amount = _fmt_amount(g.amount_max or g.amount_min)
    deadline_str = _fmt_deadline(g.deadline)
    score_str = f"{g.relevance_score * 100:.0f}%"
    title_escaped = html.escape(g.title or "")
    url_escaped = html.escape(g.url or "#")
    agency_escaped = html.escape(g.agency or "")
    desc_escaped = html.escape((g.description or "")[:300]).replace("\n", " ")

    return f"""
    <tr class="{dl_class}">
      <td>{tag_html}{badge}</td>
      <td><a href="{url_escaped}" target="_blank">{title_escaped}</a>
          <div class="desc">{desc_escaped}…</div></td>
      <td>{agency_escaped}</td>
      <td class="deadline">{deadline_str}</td>
      <td>{amount}</td>
      <td class="score">{score_str}</td>
    </tr>"""


def _build_html(
    highlights: List[Grant],
    all_filtered: List[Grant],
    stats: dict,
    run_dt: datetime,
    new_fps: Optional[set] = None,
) -> str:
    run_str = run_dt.strftime("%Y-%m-%d %H:%M UTC")

    highlight_rows = ""
    for g in highlights:
        tag = "new" if (new_fps and g.fingerprint() in new_fps) else "changed"
        highlight_rows += _grant_row(g, tag)

    all_rows = ""
    for g in sorted(all_filtered, key=lambda x: x.deadline or date.max):
        all_rows += _grant_row(g)

    # Stats summary
    stat_items = ""
    for src, info in stats.items():
        status_icon = "OK" if info.get("success") else "FAIL"
        stat_items += f"<li><strong>{src}</strong>: {info.get('collected', 0)} collected, {info.get('filtered', 0)} relevant [{status_icon}]</li>"

    errors_html = ""
    for src, info in stats.items():
        if info.get("error"):
            errors_html += f"<p class='error'>{html.escape(src)}: {html.escape(str(info['error']))}</p>"

    urgent_count = sum(1 for g in all_filtered if _is_urgent(g.deadline))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Grant Hunter Report – {run_str}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f5f7fa; color: #333; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #1a73e8; padding-bottom: 8px; }}
  h2 {{ color: #444; margin-top: 30px; }}
  .meta {{ color: #888; font-size: 0.9em; margin-bottom: 20px; }}
  .summary-box {{ background: white; border-radius: 8px; padding: 16px 24px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.1); }}
  .kpi {{ display: inline-block; margin-right: 32px; text-align: center; }}
  .kpi-num {{ font-size: 2em; font-weight: bold; color: #1a73e8; }}
  .kpi-label {{ font-size: 0.8em; color: #888; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.1); margin-bottom: 30px; }}
  th {{ background: #1a1a2e; color: white; padding: 10px 12px; text-align: left; font-size: 0.85em; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #eee; vertical-align: top; font-size: 0.88em; }}
  tr:hover td {{ background: #f0f4ff; }}
  tr.urgent td {{ background: #fff8e1; }}
  tr.expired td {{ opacity: 0.5; }}
  .deadline {{ font-weight: bold; }}
  tr.urgent .deadline {{ color: #c62828; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; color: white; font-size: 0.75em; margin-right: 4px; }}
  .tag {{ display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.7em; margin-right: 4px; font-weight: bold; }}
  .tag-new {{ background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }}
  .tag-changed {{ background: #fff3e0; color: #e65100; border: 1px solid #ffcc80; }}
  .score {{ color: #888; font-size: 0.8em; }}
  .desc {{ color: #666; font-size: 0.8em; margin-top: 3px; }}
  .error {{ color: #c62828; background: #ffebee; padding: 6px 12px; border-radius: 4px; }}
  a {{ color: #1a73e8; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  ul {{ margin: 4px 0; padding-left: 20px; }}
  .section-label {{ font-size: 0.8em; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
</style>
</head>
<body>
<h1>Grant Hunter Report</h1>
<p class="meta">Generated: {run_str} | AMR + AI keyword filter</p>

<div class="summary-box">
  <div class="kpi"><div class="kpi-num">{len(all_filtered)}</div><div class="kpi-label">Relevant Grants</div></div>
  <div class="kpi"><div class="kpi-num">{len(highlights)}</div><div class="kpi-label">New / Changed</div></div>
  <div class="kpi"><div class="kpi-num" style="color:#c62828">{urgent_count}</div><div class="kpi-label">Deadline ≤7 days</div></div>
</div>

<div class="summary-box">
  <strong>Collection Summary</strong>
  <ul>{stat_items}</ul>
  {errors_html}
</div>

{"<h2>New &amp; Changed Grants</h2><table><thead><tr><th>Source</th><th>Title</th><th>Agency</th><th>Deadline</th><th>Amount</th><th>Score</th></tr></thead><tbody>" + highlight_rows + "</tbody></table>" if highlights else "<p>No new or changed grants in this run.</p>"}

<h2>All Relevant Grants ({len(all_filtered)} total)</h2>
<table>
<thead><tr><th>Source</th><th>Title</th><th>Agency</th><th>Deadline</th><th>Amount</th><th>Score</th></tr></thead>
<tbody>{all_rows}</tbody>
</table>

<p class="meta">Grant Hunter v1.0 – automated AMR+AI grant discovery pipeline</p>
</body>
</html>"""
