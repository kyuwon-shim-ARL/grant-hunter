#!/usr/bin/env python3
"""Stratified sampling for gold set construction.

Reads the latest snapshot files from data/snapshots/, groups grants by
source x score tercile (9 buckets), samples min 3 per bucket (merges
adjacent buckets if insufficient), and writes 30+ grants to
data/labels/gold_set_real.json with label=null for human annotation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Dict, Any


DATA_DIR = Path(__file__).parent.parent / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
OUTPUT_PATH = DATA_DIR / "labels" / "gold_set_real.json"

SOURCE_MAP = {
    "nih": "nih",
    "eu": "eu",
    "grants_gov": "grants_gov",
}

MIN_PER_BUCKET = 3
TARGET_TOTAL = 30


def load_latest_snapshots() -> List[dict]:
    """Load the most recent snapshot for each source."""
    all_grants: List[dict] = []
    seen_ids: set = set()

    # Group files by source prefix
    source_files: Dict[str, List[Path]] = {}
    for f in SNAPSHOTS_DIR.glob("*.json"):
        # filename pattern: {source}_{date}.json
        parts = f.stem.rsplit("_", 1)
        if len(parts) != 2:
            continue
        source_prefix = parts[0]
        source_files.setdefault(source_prefix, []).append(f)

    for source_prefix, files in source_files.items():
        latest = sorted(files)[-1]  # lexicographic sort; dates are ISO-formatted
        print(f"  Loading {latest.name} ...")
        with open(latest, encoding="utf-8") as fh:
            grants = json.load(fh)

        # Normalise source name
        # Files are named nih_*, eu_*, grants_gov_*
        if source_prefix == "grants_gov":
            source_label = "grants_gov"
        else:
            source_label = source_prefix  # "nih" or "eu"

        for g in grants:
            gid = g.get("id") or g.get("grant_id", "")
            if gid in seen_ids:
                continue
            seen_ids.add(gid)
            # Override source field for consistency
            g["_source_label"] = source_label
            all_grants.append(g)

    return all_grants


def get_score(g: dict) -> float:
    return float(g.get("relevance_score") or 0.0)


def assign_tercile(score: float, low_thresh: float, high_thresh: float) -> str:
    if score >= high_thresh:
        return "top"
    if score >= low_thresh:
        return "mid"
    return "bot"


def compute_tercile_thresholds(scores: List[float]):
    if not scores:
        return 0.0, 0.0
    s = sorted(scores)
    n = len(s)
    low = s[n // 3]
    high = s[(2 * n) // 3]
    return low, high


def stratified_sample(all_grants: List[dict]) -> List[dict]:
    """Group by source x tercile and sample min 3 per bucket."""
    sources = sorted(set(g["_source_label"] for g in all_grants))

    buckets: Dict[str, List[dict]] = {}
    for source in sources:
        src_grants = [g for g in all_grants if g["_source_label"] == source]
        scores = [get_score(g) for g in src_grants]
        low_t, high_t = compute_tercile_thresholds(scores)

        for tercile in ("top", "mid", "bot"):
            key = f"{source}_{tercile}"
            buckets[key] = []

        for g in src_grants:
            t = assign_tercile(get_score(g), low_t, high_t)
            buckets[f"{source}_{t}"].append(g)

        # Sort each bucket by score descending
        for tercile in ("top", "mid", "bot"):
            key = f"{source}_{tercile}"
            buckets[key].sort(key=get_score, reverse=True)

    # Sample with merge fallback
    selected: Dict[str, List[dict]] = {}
    for source in sources:
        for tercile in ("top", "mid", "bot"):
            key = f"{source}_{tercile}"
            bucket = buckets[key]
            if len(bucket) >= MIN_PER_BUCKET:
                selected[key] = bucket[:MIN_PER_BUCKET]
            else:
                # Merge with adjacent bucket
                if tercile == "bot":
                    adjacent = f"{source}_mid"
                elif tercile == "mid":
                    adjacent = f"{source}_top"
                else:
                    adjacent = f"{source}_mid"
                merged = bucket + buckets.get(adjacent, [])
                # Deduplicate
                seen = set()
                deduped = []
                for g in merged:
                    gid = g.get("id") or g.get("grant_id", "")
                    if gid not in seen:
                        seen.add(gid)
                        deduped.append(g)
                deduped.sort(key=get_score, reverse=True)
                selected[key] = deduped[:MIN_PER_BUCKET]
                print(f"  Bucket {key} had {len(bucket)} grants; merged with {adjacent} -> {len(selected[key])}")

    return selected


def build_output_records(selected: Dict[str, List[dict]]) -> List[dict]:
    """Convert to gold set schema, deduplicating across buckets."""
    seen_ids: set = set()
    records = []
    for bucket_name, grants in sorted(selected.items()):
        for g in grants:
            gid = g.get("id") or g.get("grant_id", "")
            if gid in seen_ids:
                continue
            seen_ids.add(gid)
            records.append({
                "grant_id": gid,
                "title": g.get("title", ""),
                "source": g["_source_label"],
                "score": round(get_score(g), 4),
                "description": (g.get("description") or "")[:500],
                "label": None,
                "bucket": bucket_name,
            })
    return records


def print_distribution(records: List[dict]) -> None:
    from collections import Counter
    bucket_counts = Counter(r["bucket"] for r in records)
    source_counts = Counter(r["source"] for r in records)
    print(f"\nTotal grants sampled: {len(records)}")
    print("\nBy bucket:")
    for bucket, count in sorted(bucket_counts.items()):
        print(f"  {bucket}: {count}")
    print("\nBy source:")
    for source, count in sorted(source_counts.items()):
        print(f"  {source}: {count}")


def main():
    if not SNAPSHOTS_DIR.exists():
        print(f"ERROR: Snapshots directory not found: {SNAPSHOTS_DIR}")
        sys.exit(1)

    print("Loading latest snapshots ...")
    all_grants = load_latest_snapshots()
    print(f"Total unique grants loaded: {len(all_grants)}")

    if not all_grants:
        print("ERROR: No grants found in snapshots directory.")
        sys.exit(1)

    print("\nStratified sampling (9 buckets: 3 sources x 3 score terciles) ...")
    selected = stratified_sample(all_grants)

    records = build_output_records(selected)

    # Top up to TARGET_TOTAL if we have more grants available
    if len(records) < TARGET_TOTAL:
        existing_ids = {r["grant_id"] for r in records}
        extras = [g for g in all_grants if (g.get("id") or g.get("grant_id", "")) not in existing_ids]
        extras.sort(key=get_score, reverse=True)
        for g in extras:
            if len(records) >= TARGET_TOTAL:
                break
            gid = g.get("id") or g.get("grant_id", "")
            records.append({
                "grant_id": gid,
                "title": g.get("title", ""),
                "source": g["_source_label"],
                "score": round(get_score(g), 4),
                "description": (g.get("description") or "")[:500],
                "label": None,
                "bucket": f"{g['_source_label']}_extra",
            })

    print_distribution(records)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(records)} grants to {OUTPUT_PATH}")
    print("\nNext step: Open gold_set_real.json and fill in 'label' (0-3) for each grant.")
    print("Then run: python scripts/evaluate_gold_set.py")


if __name__ == "__main__":
    main()
