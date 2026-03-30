#!/usr/bin/env python3
"""Import feedback JSON (downloaded from HTML report) into data/labels/user_feedback.json.

Usage:
    python scripts/import_feedback.py <feedback_file.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FEEDBACK_PATH = Path(__file__).parent.parent / "data" / "labels" / "user_feedback.json"
REQUIRED_KEYS = {"grant_id", "label", "relevance", "timestamp"}


def load_existing() -> dict[str, dict]:
    """Return existing feedback keyed by grant_id."""
    if not FEEDBACK_PATH.exists():
        return {}
    try:
        data = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {e["grant_id"]: e for e in data if "grant_id" in e}
        return {}
    except (json.JSONDecodeError, KeyError):
        return {}


def validate_entry(entry: dict) -> bool:
    """Return True if entry has all required keys and valid values."""
    if not REQUIRED_KEYS.issubset(entry.keys()):
        return False
    if entry.get("label") not in ("relevant", "irrelevant"):
        return False
    if entry.get("relevance") not in (0, 2):
        return False
    if not isinstance(entry.get("timestamp"), (int, float)):
        return False
    return True


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_feedback.py <feedback_file.json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    try:
        new_entries: list[dict] = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}")
        sys.exit(1)

    if not isinstance(new_entries, list):
        print("Error: expected a JSON array at the top level")
        sys.exit(1)

    # Validate
    valid, skipped = [], []
    for entry in new_entries:
        if validate_entry(entry):
            valid.append(entry)
        else:
            skipped.append(entry)

    if skipped:
        print(f"Skipped {len(skipped)} invalid entries (missing keys or bad values)")

    # Merge with existing — keep latest by timestamp
    existing = load_existing()
    updated = 0
    added = 0
    for entry in valid:
        gid = entry["grant_id"]
        if gid in existing:
            if entry["timestamp"] >= existing[gid]["timestamp"]:
                existing[gid] = entry
                updated += 1
        else:
            existing[gid] = entry
            added += 1

    # Write back as sorted list
    merged = sorted(existing.values(), key=lambda e: e["timestamp"], reverse=True)
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Imported from: {input_path}")
    print(f"  Added:   {added}")
    print(f"  Updated: {updated}")
    print(f"  Skipped: {len(skipped)}")
    print(f"  Total in store: {len(merged)}")
    print(f"  Saved to: {FEEDBACK_PATH}")


if __name__ == "__main__":
    main()
