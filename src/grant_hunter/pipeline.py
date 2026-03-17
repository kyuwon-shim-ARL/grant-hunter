"""Main pipeline orchestrator for grant_hunter."""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from grant_hunter.collectors.nih import NIHCollector
from grant_hunter.collectors.eu_portal import EUPortalCollector
from grant_hunter.collectors.grants_gov import GrantsGovCollector
from grant_hunter.collectors.carb_x import CarbXCollector
from grant_hunter.collectors.right_foundation import RightFoundationCollector
from grant_hunter.collectors.gates_gc import GatesGCCollector
from grant_hunter.collectors.pasteur_network import PasteurNetworkCollector
from grant_hunter.collectors.google_org import GoogleOrgCollector
from grant_hunter.collectors.base import BaseCollector
from grant_hunter.eligibility import EligibilityEngine
from grant_hunter.filters import filter_grants, diff_grants
from grant_hunter.models import Grant
from grant_hunter.report_generator import generate_html_report
from grant_hunter.dashboard import generate_dashboard
from grant_hunter.config import REPORT_EMAIL, SKIP_EMAIL_ON_FIRST_RUN, LOGS_DIR

logger = logging.getLogger("pipeline")
_logging_configured = False


def _setup_logging() -> None:
    """Configure file + console logging (called once from run_pipeline)."""
    global _logging_configured
    if _logging_configured:
        return
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"pipeline_{datetime.utcnow().strftime('%Y%m%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    _logging_configured = True


CollectorStats = Dict[str, dict]


def _run_collector(collector: BaseCollector) -> Tuple[List[Grant], dict]:
    """Run a single collector; return (grants, stats_dict)."""
    stats: dict = {"success": False, "collected": 0, "filtered": 0, "error": None}
    try:
        grants = collector.collect()
        stats["success"] = True
        stats["collected"] = len(grants)
        return grants, stats
    except Exception as exc:
        logger.error("[%s] Collector failed: %s", collector.name, exc, exc_info=True)
        stats["error"] = str(exc)
        return [], stats


def _send_email_report(subject: str, body: str, html_path: Path) -> bool:
    """Send report via ~/bin/send-email utility."""
    cmd = ["send-email", REPORT_EMAIL, subject, body, "--html"]
    try:
        # If report HTML exists, read it and pass as body
        if html_path.exists():
            html_body = html_path.read_text(encoding="utf-8")
            result = subprocess.run(
                ["send-email", REPORT_EMAIL, subject, html_body, "--html"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        else:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

        if result.returncode == 0:
            logger.info("Email sent to %s", REPORT_EMAIL)
            return True
        else:
            logger.error("send-email failed: %s", result.stderr)
            return False
    except FileNotFoundError:
        logger.warning("send-email utility not found in PATH – skipping email")
        return False
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return False


def run_pipeline() -> dict:
    """Execute the full grant collection pipeline.

    Returns a summary dict with per-source stats and counts.
    """
    from grant_hunter.config import init_data_dirs
    init_data_dirs()
    _setup_logging()

    run_start = datetime.utcnow()
    logger.info("=" * 60)
    logger.info("Grant Hunter Pipeline started: %s", run_start.isoformat())
    logger.info("=" * 60)

    collectors: List[BaseCollector] = [
        NIHCollector(),
        EUPortalCollector(),
        GrantsGovCollector(),
        CarbXCollector(),
        RightFoundationCollector(),
        GatesGCCollector(),
        PasteurNetworkCollector(),
        GoogleOrgCollector(),
    ]

    all_current: List[Grant] = []
    all_previous: List[Grant] = []
    stats: CollectorStats = {}
    is_first_run_any = False

    # ── 1. Collect from all sources ────────────────────────────────────────────
    for collector in collectors:
        first_run = not collector.has_previous_snapshot()
        if first_run:
            is_first_run_any = True
            logger.info("[%s] First run detected – will save baseline only", collector.name)

        grants, src_stats = _run_collector(collector)
        stats[collector.name] = src_stats

        if grants:
            # Save today's snapshot
            collector.save_snapshot(grants)

            # Load previous snapshot for diff
            previous = collector.load_previous_snapshot()
            all_current.extend(grants)
            all_previous.extend(previous)

    total_collected = sum(s["collected"] for s in stats.values())
    logger.info("Total collected across all sources: %d", total_collected)

    # ── 2. Cross-source deduplication (title similarity) ─────────────────────
    deduped = _dedup(all_current)
    logger.info("After dedup: %d grants (removed %d duplicates)", len(deduped), len(all_current) - len(deduped))

    # ── 3. Keyword filtering ──────────────────────────────────────────────────
    filtered = filter_grants(deduped)
    for src_name in stats:
        src_grants = [g for g in filtered if g.source == src_name]
        stats[src_name]["filtered"] = len(src_grants)

    # ── 4. Eligibility (scoring already done by filter_grants) ──────────────
    elig_engine = EligibilityEngine()

    eligibility_map: dict = {}
    eligibility_reason_map: dict = {}
    score_map: dict = {}

    eligible_count = uncertain_count = ineligible_count = 0
    for g in filtered:
        fp = g.fingerprint()
        result = elig_engine.check(g)
        eligibility_map[fp] = result.status
        eligibility_reason_map[fp] = result.reason
        score_map[fp] = g.relevance_score  # already set by filter_grants
        if result.status == "eligible":
            eligible_count += 1
        elif result.status == "uncertain":
            uncertain_count += 1
        else:
            ineligible_count += 1

    logger.info(
        "Eligibility: eligible=%d uncertain=%d ineligible=%d",
        eligible_count, uncertain_count, ineligible_count,
    )

    # ── 5. Diff: detect new / changed grants ─────────────────────────────────
    new_grants, changed_grants = diff_grants(filtered, filter_grants(_dedup(all_previous)))
    logger.info("New: %d | Changed: %d", len(new_grants), len(changed_grants))

    # ── 6. Generate HTML report ───────────────────────────────────────────────
    report_path = generate_html_report(
        new_grants=new_grants,
        changed_grants=changed_grants,
        all_filtered=filtered,
        stats=stats,
        run_date=run_start,
    )

    # ── 7. Generate interactive dashboard ────────────────────────────────────
    dashboard_path = generate_dashboard(
        all_filtered=filtered,
        eligibility_map=eligibility_map,
        eligibility_reason_map=eligibility_reason_map,
        score_map=score_map,
        stats=stats,
        run_date=run_start,
    )
    logger.info("Dashboard: %s", dashboard_path)

    # ── 8. Send email (skip on first-ever run) ────────────────────────────────
    email_sent = False
    if SKIP_EMAIL_ON_FIRST_RUN and is_first_run_any and not all_previous:
        logger.info("Skipping email on baseline (first) run")
    else:
        n_new = len(new_grants)
        n_changed = len(changed_grants)
        subject = f"[Grant Hunter] {n_new} new, {n_changed} changed AMR+AI grants – {run_start.strftime('%Y-%m-%d')}"
        body_text = (
            f"Grant Hunter found {n_new} new and {n_changed} changed grants matching AMR+AI criteria.\n"
            f"Total relevant: {len(filtered)} | Eligible (IPK): {eligible_count} | Uncertain: {uncertain_count}\n\n"
            f"See attached HTML report for details.\nDashboard: {dashboard_path}"
        )
        email_sent = _send_email_report(subject, body_text, report_path)

    # ── 9. Print summary ──────────────────────────────────────────────────────
    summary = {
        "run_at": run_start.isoformat(),
        "total_collected": total_collected,
        "after_dedup": len(deduped),
        "filtered": len(filtered),
        "eligible": eligible_count,
        "uncertain": uncertain_count,
        "ineligible": ineligible_count,
        "new": len(new_grants),
        "changed": len(changed_grants),
        "email_sent": email_sent,
        "report_path": str(report_path),
        "dashboard_path": str(dashboard_path),
        "sources": stats,
    }

    logger.info("-" * 60)
    logger.info("SUMMARY")
    logger.info("  Collected : %d", total_collected)
    logger.info("  After dedup: %d", len(deduped))
    logger.info("  Filtered  : %d", len(filtered))
    logger.info("  Eligible  : %d  Uncertain: %d  Ineligible: %d",
                eligible_count, uncertain_count, ineligible_count)
    logger.info("  New       : %d", len(new_grants))
    logger.info("  Changed   : %d", len(changed_grants))
    logger.info("  Email sent: %s", email_sent)
    logger.info("  Report    : %s", report_path)
    logger.info("  Dashboard : %s", dashboard_path)
    for src, s in stats.items():
        ok = "OK" if s["success"] else f"FAIL({s['error']})"
        logger.info("  [%s] collected=%d filtered=%d status=%s", src, s["collected"], s["filtered"], ok)
    logger.info("=" * 60)

    return summary


def _dedup(grants: List[Grant]) -> List[Grant]:
    """Remove duplicates by fingerprint; for cross-source keep all."""
    seen: dict = {}
    for g in grants:
        fp = g.fingerprint()
        if fp not in seen:
            seen[fp] = g
    return list(seen.values())


if __name__ == "__main__":
    result = run_pipeline()
    sys.exit(0 if result["sources"] else 1)
