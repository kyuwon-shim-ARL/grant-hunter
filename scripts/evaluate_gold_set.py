#!/usr/bin/env python3
"""Evaluate gold set against the RelevanceScorer.

Loads data/labels/gold_set_real.json, scores each labeled grant,
and computes NDCG@10, MRR, Precision@10.

Usage:
    python scripts/evaluate_gold_set.py
    python scripts/evaluate_gold_set.py --kappa   # also generate LLM comparison labels (stub)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure src/ is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grant_hunter.models import Grant
from grant_hunter.scoring import RelevanceScorer
from grant_hunter.validation import ndcg_at_k, mrr, compute_inter_rater_kappa

GOLD_SET_PATH = Path(__file__).parent.parent / "data" / "labels" / "gold_set_real.json"


def load_gold_set() -> list[dict]:
    with open(GOLD_SET_PATH, encoding="utf-8") as f:
        return json.load(f)


def make_grant(entry: dict) -> Grant:
    return Grant(
        id=entry["grant_id"],
        title=entry["title"],
        agency="Unknown",
        source=entry.get("source", "unknown"),
        url=f"https://example.com/{entry['grant_id']}",
        description=entry.get("description", ""),
        amount_max=None,
        keywords=[],
        raw_data={},
    )


def precision_at_k(scored_items: list[dict], k: int = 10, threshold: int = 2) -> float:
    top_k = sorted(scored_items, key=lambda x: x["score"], reverse=True)[:k]
    relevant = sum(1 for s in top_k if (s.get("label") or 0) >= threshold)
    return round(relevant / k, 4) if k > 0 else 0.0


def generate_llm_labels_stub(entries: list[dict]) -> list[int]:
    """Placeholder: returns label=1 for all entries as a stub.

    Replace with actual LLM calls when implementing inter-rater comparison.
    Each call should send the grant title + description to the LLM with the
    labeling rubric from data/labels/labeling_guide.md and parse a 0-3 response.
    """
    print("\n[--kappa stub] LLM label generation not yet implemented.")
    print("  Returning placeholder labels (all 1s) for schema validation only.")
    return [1] * len(entries)


def main():
    parser = argparse.ArgumentParser(description="Evaluate gold set scoring metrics.")
    parser.add_argument("--kappa", action="store_true", help="Also compute inter-rater kappa vs LLM labels (stub)")
    args = parser.parse_args()

    if not GOLD_SET_PATH.exists():
        print(f"ERROR: Gold set not found: {GOLD_SET_PATH}")
        sys.exit(1)

    all_entries = load_gold_set()
    if not all_entries:
        print("Gold set is empty. Run scripts/sample_for_gold_set.py first.")
        sys.exit(0)

    # Filter to labeled entries only
    labeled = [e for e in all_entries if e.get("label") is not None]
    if not labeled:
        print(f"No labeled entries found ({len(all_entries)} total, all label=null).")
        print("Label grants in gold_set_real.json (set 'label' to 0/1/2/3) then re-run.")
        sys.exit(0)

    print(f"Gold set: {len(all_entries)} total, {len(labeled)} labeled, {len(all_entries) - len(labeled)} pending.")

    scorer = RelevanceScorer()

    scored_items = []
    for entry in labeled:
        grant = make_grant(entry)
        score = scorer.score(grant)
        scored_items.append({
            "grant_id": entry["grant_id"],
            "title": entry["title"],
            "label": int(entry["label"]),
            "score": score,
            "bucket": entry.get("bucket", ""),
        })

    scored_items.sort(key=lambda x: x["score"], reverse=True)

    # Compute metrics
    ndcg = ndcg_at_k(scored_items, k=10)
    mrr_val = mrr(scored_items, relevant_threshold=2)
    p10 = precision_at_k(scored_items, k=10)

    # Label distribution
    from collections import Counter
    label_dist = Counter(s["label"] for s in scored_items)

    print("\n" + "=" * 50)
    print("EVALUATION RESULTS")
    print("=" * 50)
    print(f"  NDCG@10       : {ndcg:.4f}")
    print(f"  MRR           : {mrr_val:.4f}")
    print(f"  Precision@10  : {p10:.4f}")
    print("\nLabel distribution:")
    for lbl in sorted(label_dist.keys()):
        label_names = {0: "irrelevant", 1: "low", 2: "medium_relevant", 3: "high_relevant"}
        print(f"  {lbl} ({label_names.get(lbl, '?')}): {label_dist[lbl]}")

    print("\nTop 10 scored grants:")
    print(f"  {'Rank':<5} {'Score':<8} {'Label':<6} {'Title'[:60]}")
    print(f"  {'-'*5} {'-'*8} {'-'*6} {'-'*50}")
    for i, s in enumerate(scored_items[:10], 1):
        title = s["title"][:50] + "..." if len(s["title"]) > 50 else s["title"]
        print(f"  {i:<5} {s['score']:<8.4f} {s['label']:<6} {title}")

    if args.kappa:
        human_labels = [s["label"] for s in scored_items]
        llm_labels = generate_llm_labels_stub(labeled)
        if len(llm_labels) == len(human_labels):
            kappa = compute_inter_rater_kappa(human_labels, llm_labels)
            print(f"\n  Inter-rater kappa (human vs LLM stub): {kappa:.4f}")
            print("  (Replace stub in generate_llm_labels_stub() for real comparison)")

    print("=" * 50)


if __name__ == "__main__":
    main()
