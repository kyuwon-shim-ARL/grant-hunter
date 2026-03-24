"""Main pipeline orchestrator for grant_hunter."""

from __future__ import annotations

import concurrent.futures
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

from grant_hunter.collectors.nih import NIHCollector
from grant_hunter.collectors.eu_portal import EUPortalCollector
from grant_hunter.collectors.grants_gov import GrantsGovCollector
from grant_hunter.collectors.base import BaseCollector
from grant_hunter.eligibility import EligibilityEngine
from grant_hunter.filters import score_and_rank_grants, diff_grants
from grant_hunter.models import Grant
from grant_hunter.profiles import get_profile
from grant_hunter.report_generator import generate_html_report
from grant_hunter.dashboard import generate_dashboard
from grant_hunter.config import REPORT_EMAIL, SKIP_EMAIL_ON_FIRST_RUN, LOGS_DIR, SNAPSHOTS_DIR, NIH_COLLECTOR_TIMEOUT, GRANT_HUNTER_PROFILE

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


def validate_grant(grant_dict: dict) -> tuple[bool, str]:
    """Validate a grant dict has minimum required fields.
    Returns (is_valid, reason).
    """
    if not grant_dict.get("title", "").strip():
        return False, "missing title"
    desc = grant_dict.get("description", "").strip()
    if len(desc) < 20:
        return False, f"description too short ({len(desc)} chars)"
    return True, "ok"


def _collect_with_retry(collector_fn, source_name: str, max_retries: int = 3, timeout: int = NIH_COLLECTOR_TIMEOUT) -> list:
    """Run collector_fn with exponential backoff retry and wall-clock timeout (10 min default)."""
    for attempt in range(max_retries):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(collector_fn)
                return future.result(timeout=timeout)  # wall-clock timeout (configurable)
        except concurrent.futures.TimeoutError:
            print(f"  Warning: {source_name} attempt {attempt+1}/{max_retries} timed out after {timeout}s")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        except Exception as exc:
            wait = 2 ** attempt
            print(f"  Warning: {source_name} attempt {attempt+1}/{max_retries} failed: {exc}")
            if attempt < max_retries - 1:
                time.sleep(wait)
    print(f"  ERROR: {source_name} failed after {max_retries} attempts")
    return []


ACTIVE_COLLECTORS = {"nih", "eu", "grants_gov"}


def check_staleness(snapshot_dir: Path, max_age_hours: int = 48) -> list:
    """Return list of stale source names (snapshot files older than max_age_hours)."""
    stale = []
    for f in snapshot_dir.glob("*.json"):
        # Skip orphan snapshots from deleted collectors
        source_name = f.stem.rsplit("_", 1)[0] if "_" in f.stem else f.stem
        if source_name not in ACTIVE_COLLECTORS:
            continue
        age = datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)
        if age > timedelta(hours=max_age_hours):
            stale.append(f.stem)
    return stale


def _run_collector(collector: BaseCollector) -> Tuple[List[Grant], dict]:
    """Run a single collector with retry; return (grants, stats_dict)."""
    stats: dict = {"success": False, "collected": 0, "filtered": 0, "error": None}
    grants = _collect_with_retry(collector.collect, collector.name)
    if grants:
        stats["success"] = True
        stats["collected"] = len(grants)
    else:
        stats["error"] = f"{collector.name} returned no results after retries"
    return grants, stats


def _send_email_report(subject: str, body: str, html_path: Path) -> bool:
    """Send report via ~/bin/send-email utility."""
    try:
        if html_path.exists():
            # Pass file path instead of HTML content to avoid ARG_MAX limit
            result = subprocess.run(
                ["send-email", REPORT_EMAIL, subject, body,
                 "--html", "--file", str(html_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        else:
            result = subprocess.run(
                ["send-email", REPORT_EMAIL, subject, body, "--html"],
                capture_output=True,
                text=True,
                timeout=60,
            )

        if result.returncode == 0:
            logger.info("Email sent to %s", REPORT_EMAIL)
            return True
        else:
            logger.error("send-email failed (stderr): %s", result.stderr)
            if result.stdout:
                logger.error("send-email failed (stdout): %s", result.stdout)
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

    profile = get_profile(GRANT_HUNTER_PROFILE)
    logger.info("Using profile: %s (%s)", profile.name, GRANT_HUNTER_PROFILE)

    run_start = datetime.utcnow()
    logger.info("=" * 60)
    logger.info("Grant Hunter Pipeline started: %s", run_start.isoformat())
    logger.info("=" * 60)

    collectors: List[BaseCollector] = [
        NIHCollector(),
        EUPortalCollector(),
        GrantsGovCollector(),
    ]

    all_current: List[Grant] = []
    all_previous: List[Grant] = []
    stats: CollectorStats = {}
    is_first_run_any = False
    validation_passed = 0
    validation_rejected = 0

    # ── 1. Collect from all sources ────────────────────────────────────────────
    for collector in collectors:
        first_run = not collector.has_previous_snapshot()
        if first_run:
            is_first_run_any = True
            logger.info("[%s] First run detected – will save baseline only", collector.name)

        grants, src_stats = _run_collector(collector)
        stats[collector.name] = src_stats

        if grants:
            # Validate each grant before including
            valid_grants = []
            for g in grants:
                grant_dict = {"title": g.title, "description": g.description}
                ok, reason = validate_grant(grant_dict)
                if ok:
                    valid_grants.append(g)
                    validation_passed += 1
                else:
                    validation_rejected += 1
                    logger.debug("[%s] Rejected grant '%s': %s", collector.name, g.title, reason)
            grants = valid_grants

            # Save today's snapshot
            collector.save_snapshot(grants)

            # Load previous snapshot for diff
            previous = collector.load_previous_snapshot()
            all_current.extend(grants)
            all_previous.extend(previous)

    total_collected = sum(s["collected"] for s in stats.values())
    logger.info("Total collected across all sources: %d", total_collected)
    logger.info("Validation: %d passed, %d rejected", validation_passed, validation_rejected)

    # ── 2. Cross-source deduplication (title similarity) ─────────────────────
    deduped = _dedup(all_current)
    logger.info("After dedup: %d grants (removed %d duplicates)", len(deduped), len(all_current) - len(deduped))

    # ── 3. Score and rank all grants ────────────────────────────────────────
    scored = score_and_rank_grants(deduped, profile=profile)
    for src_name in stats:
        src_grants = [g for g in scored if g.source == src_name]
        stats[src_name]["filtered"] = len(src_grants)

    # ── 4. Eligibility (scoring already done) ────────────────────────────────
    elig_engine = EligibilityEngine()

    eligibility_map: dict = {}
    eligibility_reason_map: dict = {}
    score_map: dict = {}

    eligible_count = uncertain_count = ineligible_count = 0
    for g in scored:
        fp = g.fingerprint()
        result = elig_engine.check(g)
        eligibility_map[fp] = result.status
        eligibility_reason_map[fp] = result.reason
        score_map[fp] = g.relevance_score  # already set by score_and_rank_grants
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
    new_grants, changed_grants = diff_grants(scored, score_and_rank_grants(_dedup(all_previous), profile=profile))
    logger.info("New: %d | Changed: %d", len(new_grants), len(changed_grants))

    # ── 6. Generate HTML report ───────────────────────────────────────────────
    report_path = generate_html_report(
        new_grants=new_grants,
        changed_grants=changed_grants,
        all_filtered=scored,
        stats=stats,
        run_date=run_start,
        eligibility_map=eligibility_map,
        eligibility_reason_map=eligibility_reason_map,
        profile_name=profile.name,
    )

    # ── 7. Generate interactive dashboard ────────────────────────────────────
    dashboard_path = generate_dashboard(
        all_filtered=scored,
        eligibility_map=eligibility_map,
        eligibility_reason_map=eligibility_reason_map,
        score_map=score_map,
        stats=stats,
        run_date=run_start,
    )
    logger.info("Dashboard: %s", dashboard_path)

    # ── 8. Send email (skip when nothing new) ───────────────────────────────
    email_sent = False
    n_new = len(new_grants)
    n_changed = len(changed_grants)
    if SKIP_EMAIL_ON_FIRST_RUN and is_first_run_any and not all_previous:
        logger.info("Skipping email on baseline (first) run")
    elif n_new == 0 and n_changed == 0:
        logger.info("Skipping email: 0 new, 0 changed grants")
    else:
        profile_label = f" [{profile.name}]" if GRANT_HUNTER_PROFILE != "default" else ""
        subject = f"[Grant Hunter{profile_label}] {n_new} new, {n_changed} changed AMR+AI grants – {run_start.strftime('%Y-%m-%d')}"
        body_text = (
            f"Grant Hunter found {n_new} new and {n_changed} changed grants matching AMR+AI criteria.\n"
            f"Total relevant: {len(scored)} | Eligible (IPK): {eligible_count} | Uncertain: {uncertain_count}\n\n"
            f"See attached HTML report for details.\nDashboard: {dashboard_path}"
        )
        email_sent = _send_email_report(subject, body_text, report_path)

    # ── 9. Staleness check ────────────────────────────────────────────────────
    stale_sources = check_staleness(SNAPSHOTS_DIR)

    # ── 10. Print collection summary ─────────────────────────────────────────
    print("\nCollection Summary:")
    for src, s in stats.items():
        count = s["collected"]
        if not s["success"]:
            status = f"ERROR: {s['error']}"
        elif count == 0:
            status = "WARNING: empty"
        else:
            status = "OK"
        print(f"  {src}: {count} grants ({status})")
    total_validated = validation_passed + validation_rejected
    print(f"  Validation: {validation_passed}/{total_validated} passed, {validation_rejected} rejected")
    print(f"  Stale sources: {', '.join(stale_sources) if stale_sources else 'none'}")

    summary = {
        "run_at": run_start.isoformat(),
        "total_collected": total_collected,
        "after_dedup": len(deduped),
        "filtered": len(scored),
        "eligible": eligible_count,
        "uncertain": uncertain_count,
        "ineligible": ineligible_count,
        "new": len(new_grants),
        "changed": len(changed_grants),
        "email_sent": email_sent,
        "report_path": str(report_path),
        "dashboard_path": str(dashboard_path),
        "sources": stats,
        "validation_passed": validation_passed,
        "validation_rejected": validation_rejected,
        "stale_sources": stale_sources,
    }

    # ── 10.5. Persist run history + anomaly detection ─────────────────────
    try:
        from grant_hunter.monitoring import save_run_history, check_volume_anomaly
        from grant_hunter.config import RUN_HISTORY_FILE

        save_run_history(summary, RUN_HISTORY_FILE)
        anomaly_alerts = check_volume_anomaly(summary, RUN_HISTORY_FILE)
        if anomaly_alerts:
            for alert in anomaly_alerts:
                logger.warning("ANOMALY: %s", alert)
        summary["anomaly_alerts"] = anomaly_alerts
    except Exception as exc:
        logger.warning("Monitoring failed (non-fatal): %s", exc)
        summary["anomaly_alerts"] = []

    logger.info("-" * 60)
    logger.info("SUMMARY")
    logger.info("  Collected : %d", total_collected)
    logger.info("  After dedup: %d", len(deduped))
    logger.info("  Scored    : %d", len(scored))
    logger.info("  Eligible  : %d  Uncertain: %d  Ineligible: %d",
                eligible_count, uncertain_count, ineligible_count)
    logger.info("  New       : %d", len(new_grants))
    logger.info("  Changed   : %d", len(changed_grants))
    logger.info("  Email sent: %s", email_sent)
    logger.info("  Report    : %s", report_path)
    logger.info("  Dashboard : %s", dashboard_path)
    logger.info("  Stale sources: %s", stale_sources or "none")
    for src, s in stats.items():
        ok = "OK" if s["success"] else f"FAIL({s['error']})"
        logger.info("  [%s] collected=%d filtered=%d status=%s", src, s["collected"], s["filtered"], ok)
    logger.info("=" * 60)

    return summary


def _dedup(grants: List[Grant]) -> List[Grant]:
    """Remove duplicates by fingerprint; cross-source dedup by normalized title."""
    seen_fp: dict = {}
    seen_title: dict = {}
    for g in grants:
        fp = g.fingerprint()
        if fp in seen_fp:
            continue
        seen_fp[fp] = g
        # Cross-source: keep the one with longer description
        title_key = g.cross_fingerprint()
        if title_key in seen_title:
            existing = seen_title[title_key]
            if len(g.description or "") > len(existing.description or ""):
                # Replace with richer version
                existing_fp = existing.fingerprint()
                if existing_fp in seen_fp:
                    del seen_fp[existing_fp]
                seen_fp[fp] = g
                seen_title[title_key] = g
        else:
            seen_title[title_key] = g
    return list(seen_fp.values())


def main():
    """CLI entry point for grant-hunter-run."""
    import argparse
    parser = argparse.ArgumentParser(description="Grant Hunter Pipeline")
    parser.add_argument("--profile", default=None, help="Researcher profile name (default, wetlab_amr, computational, translational, clinical)")
    args = parser.parse_args()

    if args.profile:
        import os
        os.environ["GRANT_HUNTER_PROFILE"] = args.profile
        # Re-import to pick up the new value
        import grant_hunter.config
        grant_hunter.config.GRANT_HUNTER_PROFILE = args.profile

    result = run_pipeline()
    sys.exit(0 if any(s.get("success") for s in result["sources"].values()) else 1)


if __name__ == "__main__":
    main()
