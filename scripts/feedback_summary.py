#!/usr/bin/env python3
"""Summarise user feedback stored in data/labels/user_feedback.json.

Usage:
    python scripts/feedback_summary.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

FEEDBACK_PATH = Path(__file__).parent.parent / "data" / "labels" / "user_feedback.json"


def main() -> None:
    if not FEEDBACK_PATH.exists():
        print(f"No feedback file found at: {FEEDBACK_PATH}")
        return

    try:
        entries: list[dict] = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error reading feedback file: {exc}")
        return

    if not entries:
        print("Feedback file is empty.")
        return

    # Group by year-month
    by_month: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        ts = entry.get("timestamp")
        if ts:
            try:
                dt = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts)
                month_key = dt.strftime("%Y-%m")
            except (OSError, ValueError):
                month_key = "unknown"
        else:
            month_key = "unknown"
        by_month[month_key].append(entry)

    # Print table
    col_w = [10, 8, 10, 12, 18]
    header = (
        f"{'Month':<{col_w[0]}} {'Total':>{col_w[1]}} "
        f"{'Relevant':>{col_w[2]}} {'Irrelevant':>{col_w[3]}} "
        f"{'Precision Est.':>{col_w[4]}}"
    )
    sep = "-" * len(header)
    print()
    print("Grant Hunter — Feedback Summary")
    print(sep)
    print(header)
    print(sep)

    total_all = 0
    relevant_all = 0

    for month in sorted(by_month.keys()):
        month_entries = by_month[month]
        total = len(month_entries)
        relevant = sum(1 for e in month_entries if e.get("label") == "relevant")
        irrelevant = total - relevant
        precision = relevant / total if total > 0 else 0.0
        precision_str = f"{precision:.1%}"
        print(
            f"{month:<{col_w[0]}} {total:{col_w[1]}} "
            f"{relevant:{col_w[2]}} {irrelevant:{col_w[3]}} "
            f"{precision_str:>{col_w[4]}}"
        )
        total_all += total
        relevant_all += relevant

    print(sep)
    irrelevant_all = total_all - relevant_all
    precision_all = relevant_all / total_all if total_all > 0 else 0.0
    precision_all_str = f"{precision_all:.1%}"
    print(
        f"{'TOTAL':<{col_w[0]}} {total_all:{col_w[1]}} "
        f"{relevant_all:{col_w[2]}} {irrelevant_all:{col_w[3]}} "
        f"{precision_all_str:>{col_w[4]}}"
    )
    print()
    print(f"Feedback file: {FEEDBACK_PATH}")


if __name__ == "__main__":
    main()
