"""HTML report generator for filtered grants."""

from __future__ import annotations

import html
import logging
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from grant_hunter.classifier import GrantClassifier
from grant_hunter.config import REPORTS_DIR, DEADLINE_WARN_DAYS
from grant_hunter.models import Grant
from grant_hunter.scoring import RelevanceScorer

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

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


_ELIG_COLORS = {
    "eligible": "#2e7d32",
    "uncertain": "#e65100",
    "ineligible": "#c62828",
}


def _grant_row(g: Grant, tag: str = "", eligibility: str = "", reason: str = "") -> str:
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

    if eligibility:
        color = _ELIG_COLORS.get(eligibility, "#888")
        reason_escaped = html.escape(reason or "")
        elig_html = f'<span style="color:{color};font-weight:bold" title="{reason_escaped}">{eligibility}</span>'
    else:
        elig_html = '<span style="color:#aaa">—</span>'

    return f"""
    <tr class="{dl_class}">
      <td>{tag_html}{badge}</td>
      <td><a href="{url_escaped}" target="_blank">{title_escaped}</a>
          <div class="desc">{desc_escaped}…</div></td>
      <td>{agency_escaped}</td>
      <td class="deadline">{deadline_str}</td>
      <td>{amount}</td>
      <td class="score">{score_str}</td>
      <td>{elig_html}</td>
    </tr>"""


def _urgency_chip(days: Optional[int]) -> str:
    """Return (chip_class, label) for a deadline days-until value."""
    if days is None:
        return "urg-green", "미정"
    if days < 0:
        return "urg-red", "만료"
    if days <= 30:
        return "urg-red", f"긴급 D-{days}"
    if days <= 60:
        return "urg-orange", f"주의 D-{days}"
    if days <= 90:
        return "urg-yellow", f"준비 D-{days}"
    return "urg-green", f"여유 D-{days}"


def _stage_tag_class(stage: str) -> str:
    return {
        "basic": "stage-basic",
        "translational": "stage-translational",
        "clinical": "stage-clinical",
        "infrastructure": "stage-infrastructure",
    }.get(stage, "stage-basic")


def _ftype_tag_class(ftype: str) -> str:
    return {
        "project_grant": "ftype-project",
        "fellowship": "ftype-fellowship",
        "consortium": "ftype-consortium",
        "challenge": "ftype-challenge",
        "institutional": "ftype-inst",
    }.get(ftype, "ftype-project")


def _ftype_label(ftype: str) -> str:
    return {
        "project_grant": "프로젝트",
        "fellowship": "펠로우십",
        "consortium": "컨소시엄",
        "challenge": "챌린지",
        "institutional": "기관",
    }.get(ftype, ftype)


def _stage_label(stage: str) -> str:
    return {
        "basic": "기초",
        "translational": "중개",
        "clinical": "임상",
        "infrastructure": "인프라",
        "unclassified": "미분류",
    }.get(stage, stage)


def _breakdown_bar_html(breakdown: dict) -> str:
    """Render an inline stacked bar for score breakdown."""
    amr = breakdown.get("amr", 0)
    ai = breakdown.get("ai", 0)
    drug = breakdown.get("drug", 0)
    amt = breakdown.get("amount_bonus", 0)
    total = amr + ai + drug + amt
    if total <= 0:
        return '<div class="breakdown-bar"><div class="breakdown-empty"></div></div>'

    def pct(v: float) -> float:
        return round(v / total * 100, 1) if total > 0 else 0

    return f'''<div class="breakdown-bar" title="AMR {amr:.0%} · AI {ai:.0%} · Drug {drug:.0%} · Amt {amt:.0%}">
      <div class="bd-seg bd-amr" style="width:{pct(amr)}%"></div>
      <div class="bd-seg bd-ai" style="width:{pct(ai)}%"></div>
      <div class="bd-seg bd-drug" style="width:{pct(drug)}%"></div>
      <div class="bd-seg bd-amt" style="width:{pct(amt)}%"></div>
    </div>'''


def _build_tier_row_html(g: Grant, clf, eligibility: str = "", reason: str = "",
                         breakdown: dict | None = None) -> str:
    """Build an HTML <tr> for the MECE tier table."""
    today = date.today()
    days = (g.deadline - today).days if g.deadline else None
    chip_class, chip_label = _urgency_chip(days)
    deadline_str = _fmt_deadline(g.deadline)
    score_val = int(g.relevance_score * 100)
    score_class = "score-high" if score_val >= 70 else ("score-mid" if score_val >= 50 else "score-low")
    title_escaped = html.escape(g.title or "")
    url_escaped = html.escape(g.url or "#")
    agency_escaped = html.escape(g.agency or "")
    stage_class = _stage_tag_class(clf.research_stage)
    stage_lbl = _stage_label(clf.research_stage)
    ftype_class = _ftype_tag_class(clf.funding_type)
    ftype_lbl = _ftype_label(clf.funding_type)

    # Eligibility column
    if eligibility:
        color = _ELIG_COLORS.get(eligibility, "#888")
        reason_escaped = html.escape(reason or "")
        elig_html = f'<span style="color:{color};font-weight:bold" title="{reason_escaped}">{eligibility}</span>'
    else:
        elig_html = '<span style="color:#aaa">—</span>'

    # Score breakdown bar
    bd_html = _breakdown_bar_html(breakdown) if breakdown else ""

    return f"""<tr>
      <td>
        <div class="grant-name"><a href="{url_escaped}" target="_blank">{title_escaped}</a></div>
        <div class="grant-funder">{agency_escaped}</div>
      </td>
      <td>
        <div class="mece-tags">
          <span class="mece-tag {stage_class}">{stage_lbl}</span>
          <span class="mece-tag {ftype_class}">{ftype_lbl}</span>
        </div>
      </td>
      <td>
        <div class="deadline-cell">{deadline_str}</div>
        <div><span class="urg-chip {chip_class}">{chip_label}</span></div>
      </td>
      <td>
        <span class="score-badge {score_class}">{score_val}</span>
        {bd_html}
      </td>
      <td>{elig_html}</td>
    </tr>"""


def _heat_class(n: int) -> str:
    if n == 0:
        return "heat-0"
    if n == 1:
        return "heat-1"
    if n == 2:
        return "heat-2"
    if n <= 4:
        return "heat-3"
    return "heat-hot"


def _safe_pct(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(part / total * 100, 1)


def generate_html_report(
    new_grants: List[Grant],
    changed_grants: List[Grant],
    all_filtered: List[Grant],
    stats: dict,
    run_date: Optional[datetime] = None,
    eligibility_map: Optional[dict] = None,
    eligibility_reason_map: Optional[dict] = None,
    profile_name: Optional[str] = None,
) -> Path:
    """Generate HTML report and return its path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dt = run_date or datetime.utcnow()
    filename = f"report_{run_dt.strftime('%Y%m%d_%H%M%S')}.html"
    path = REPORTS_DIR / filename

    html_content = _build_html(
        all_filtered, stats, run_dt,
        eligibility_map, eligibility_reason_map, profile_name
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html_content)

    logger.info("Report written: %s", path)
    return path


def _build_html(
    all_filtered: List[Grant],
    stats: dict,
    run_dt: datetime,
    eligibility_map: Optional[dict] = None,
    eligibility_reason_map: Optional[dict] = None,
    profile_name: Optional[str] = None,
) -> str:
    run_str = run_dt.strftime("%Y-%m-%d %H:%M UTC")
    elig_map = eligibility_map or {}
    reason_map = eligibility_reason_map or {}

    classifier = GrantClassifier()
    today = date.today()

    # --- Classify all grants ---
    classifications = {g.fingerprint(): classifier.classify(g, today) for g in all_filtered}

    # --- KPI counts ---
    tier_counts = {"tier1": 0, "tier2": 0, "tier3": 0, "tier4": 0}
    for clf in classifications.values():
        tier_counts[clf.tier] = tier_counts.get(clf.tier, 0) + 1

    total = len(all_filtered)
    kpi = {
        "total": total,
        "tier1": tier_counts["tier1"],
        "tier2": tier_counts["tier2"],
        "tier3": tier_counts["tier3"],
        "tier1_pct": _safe_pct(tier_counts["tier1"], total),
        "tier2_pct": _safe_pct(tier_counts["tier2"], total),
        "tier3_pct": _safe_pct(tier_counts["tier3"], total),
    }

    # --- Urgency counts ---
    u_urgent = sum(1 for g in all_filtered if g.deadline and (g.deadline - today).days >= 0 and (g.deadline - today).days <= 30)
    u_hot = sum(1 for g in all_filtered if g.deadline and 30 < (g.deadline - today).days <= 60)
    u_warn = sum(1 for g in all_filtered if g.deadline and 60 < (g.deadline - today).days <= 90)
    u_safe = sum(1 for g in all_filtered if not g.deadline or (g.deadline - today).days > 90)
    urgency = {
        "urgent_count": u_urgent,
        "hot_count": u_hot,
        "warn_count": u_warn,
        "safe_count": u_safe,
        "urgent_pct": _safe_pct(u_urgent, total),
        "hot_pct": _safe_pct(u_hot, total),
        "warn_pct": _safe_pct(u_warn, total),
        "safe_pct": _safe_pct(u_safe, total),
    }

    # --- Source distribution ---
    source_counts: dict[str, int] = {}
    for g in all_filtered:
        source_counts[g.source] = source_counts.get(g.source, 0) + 1
    source_dist = [
        {
            "label": SOURCE_LABELS.get(src, src.upper()),
            "count": cnt,
            "pct": _safe_pct(cnt, total),
            "color": SOURCE_COLORS.get(src, "#888"),
        }
        for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1])
    ]

    # --- MECE matrix ---
    STAGES = ["basic", "translational", "clinical", "infrastructure", "unclassified"]
    FTYPES = ["project_grant", "fellowship", "consortium", "challenge", "institutional"]

    # count per (stage, ftype)
    matrix: dict[tuple[str, str], int] = {}
    for fp, clf in classifications.items():
        key = (clf.research_stage, clf.funding_type)
        matrix[key] = matrix.get(key, 0) + 1

    STAGE_LABELS = {
        "basic": "기초 (Basic)",
        "translational": "중개 (Translational)",
        "clinical": "임상 (Clinical)",
        "infrastructure": "인프라 (Infra)",
        "unclassified": "미분류",
    }
    FTYPE_LABELS = {
        "project_grant": "프로젝트<br>과제",
        "fellowship": "펠로우십",
        "consortium": "컨소시엄",
        "challenge": "챌린지",
        "institutional": "기관·인프라",
    }

    mece_cols = [{"label": FTYPE_LABELS[ft]} for ft in FTYPES]
    mece_matrix = []
    for stage in STAGES:
        row_cells = []
        row_total = 0
        for ftype in FTYPES:
            n = matrix.get((stage, ftype), 0)
            row_total += n
            row_cells.append({
                "num": str(n) if n > 0 else "—",
                "heat_class": _heat_class(n),
                "label": "",
            })
        mece_matrix.append({
            "label": STAGE_LABELS[stage],
            "cells": row_cells,
            "total": row_total,
            "total_heat": _heat_class(row_total),
            "muted": stage == "unclassified",
        })

    mece_col_totals = []
    for ftype in FTYPES:
        col_sum = sum(matrix.get((stage, ftype), 0) for stage in STAGES)
        mece_col_totals.append(col_sum)

    # --- Tier grant rows ---
    scorer = RelevanceScorer()

    def _make_tier_rows(tier_key: str) -> list:
        rows = []
        for g in sorted(all_filtered, key=lambda x: (-x.relevance_score, x.deadline or date.max)):
            fp = g.fingerprint()
            clf = classifications.get(fp)
            if clf and clf.tier == tier_key:
                breakdown = scorer.score_breakdown(g)
                row_html = _build_tier_row_html(
                    g, clf,
                    elig_map.get(fp, ""),
                    reason_map.get(fp, ""),
                    breakdown=breakdown,
                )
                rows.append({"row_html": row_html})
        return rows

    tier1_grants = _make_tier_rows("tier1")
    tier2_grants = _make_tier_rows("tier2")
    tier3_grants = _make_tier_rows("tier3")
    tier4_grants = _make_tier_rows("tier4")

    # --- Stats ---
    stat_items = []
    error_items = []
    for src, info in stats.items():
        stat_items.append({
            "source": src,
            "collected": info.get("collected", 0),
            "filtered": info.get("filtered", 0),
            "status": "OK" if info.get("success") else "FAIL",
        })
        if info.get("error"):
            error_items.append(f"{html.escape(src)}: {html.escape(str(info['error']))}")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("mece_report.html")

    return template.render(
        run_date=run_str,
        profile_name=profile_name,
        kpi=kpi,
        urgency=urgency,
        source_dist=source_dist,
        mece_cols=mece_cols,
        mece_matrix=mece_matrix,
        mece_col_totals=mece_col_totals,
        tier1_grants=tier1_grants,
        tier2_grants=tier2_grants,
        tier3_grants=tier3_grants,
        tier4_grants=tier4_grants,
        stat_items=stat_items,
        error_items=error_items,
    )
