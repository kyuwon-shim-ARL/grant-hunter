"""30-day uptime report for grant_hunter pipeline.

Usage:
    uv run python scripts/check_uptime.py
    uv run python scripts/check_uptime.py --file /path/to/run_history.json
    uv run python scripts/check_uptime.py --days 7
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_history(history_file: Path) -> list[dict]:
    if not history_file.exists():
        print(f"History file not found: {history_file}", file=sys.stderr)
        return []
    try:
        return json.loads(history_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Could not read history file: {e}", file=sys.stderr)
        return []


def _parse_dt(ts: str) -> datetime | None:
    """Parse ISO-8601 timestamp to UTC-aware datetime."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _is_successful(entry: dict) -> bool:
    """A run is successful if all sources have success=True."""
    sources = entry.get("sources", {})
    if not sources:
        return False
    return all(info.get("success", False) for info in sources.values())


def compute_report(history: list[dict], days: int = 30) -> dict:
    """Compute uptime metrics from run history for the last `days` days."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(days=days)
    period_start = now  # will be set to earliest run in window

    window = []
    for entry in history:
        run_at = _parse_dt(entry.get("run_at", ""))
        if run_at and run_at >= cutoff:
            window.append((run_at, entry))
            if run_at < period_start:
                period_start = run_at

    total_runs = len(window)
    successful_runs = sum(1 for _, e in window if _is_successful(e))
    uptime_pct = (successful_runs / total_runs * 100) if total_runs > 0 else 0.0

    # MTTR: for each alert, find time from alert_sent_at to next successful run
    mttrs: list[float] = []
    sorted_window = sorted(window, key=lambda x: x[0])
    for i, (run_at, entry) in enumerate(sorted_window):
        alert_sent_at_str = entry.get("alert_sent_at")
        if not alert_sent_at_str:
            continue
        alert_dt = _parse_dt(alert_sent_at_str)
        if not alert_dt:
            continue
        # Find next successful run after this alert
        recovery_dt = None
        for j in range(i + 1, len(sorted_window)):
            next_dt, next_entry = sorted_window[j]
            if _is_successful(next_entry):
                recovery_dt = next_dt
                break
        if recovery_dt is not None:
            hours = max(0.0, (recovery_dt - alert_dt).total_seconds() / 3600)
            mttrs.append(hours)

    avg_mttr = sum(mttrs) / len(mttrs) if mttrs else None
    alert_count = sum(1 for _, e in window if e.get("alert_sent_at"))

    return {
        "period_start": period_start if total_runs > 0 else cutoff,
        "period_end": now,
        "days": days,
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "uptime_pct": uptime_pct,
        "alert_count": alert_count,
        "mttrs_hours": mttrs,
        "avg_mttr_hours": avg_mttr,
    }


def print_report(r: dict) -> None:
    uptime_target = 97.0
    mttr_target = 4.0

    period_start_str = r["period_start"].strftime("%Y-%m-%d")
    period_end_str = r["period_end"].strftime("%Y-%m-%d")

    uptime_ok = r["uptime_pct"] >= uptime_target
    uptime_status = "ON TARGET" if uptime_ok else "BELOW TARGET"

    print(f"=== Grant Hunter Uptime Report (Last {r['days']} days) ===")
    print(f"Period: {period_start_str} ~ {period_end_str}")
    print(f"Total runs:  {r['total_runs']}")
    print(f"Successful:  {r['successful_runs']}")
    print(f"Uptime:      {r['uptime_pct']:.1f}%")
    print(f"Target:      >= {uptime_target:.0f}%")
    print(f"Status:      {'[OK] ' + uptime_status if uptime_ok else '[!!] ' + uptime_status}")
    print()
    print(f"Alerts:      {r['alert_count']}")
    if r["avg_mttr_hours"] is not None:
        mttr_ok = r["avg_mttr_hours"] <= mttr_target
        mttr_status = "ON TARGET" if mttr_ok else "ABOVE TARGET"
        print(f"Avg MTTR:    {r['avg_mttr_hours']:.1f}h")
        print(f"Target MTTR: <= {mttr_target:.0f}h")
        print(f"MTTR Status: {'[OK] ' if mttr_ok else '[!!] '}{mttr_status}")
    else:
        print("Avg MTTR:    N/A (no resolved alerts in period)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant Hunter 30-day uptime report")
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to run_history.json (default: auto-detect from config)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to include in report (default: 30)",
    )
    args = parser.parse_args()

    if args.file is not None:
        history_file = args.file
    else:
        try:
            from grant_hunter.config import RUN_HISTORY_FILE
            history_file = RUN_HISTORY_FILE
        except ImportError:
            # Fallback: look relative to project root
            history_file = Path(__file__).resolve().parents[1] / "data" / "run_history.json"

    history = _load_history(history_file)
    report = compute_report(history, days=args.days)
    print_report(report)


if __name__ == "__main__":
    main()
