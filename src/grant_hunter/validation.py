"""Scoring validation against ground truth labels."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from grant_hunter.models import Grant
from grant_hunter.scoring import RelevanceScorer

VALIDATION_SET_FILE = Path(__file__).parent / "data" / "validation_set.json"

# Label -> minimum expected score (used for misclassification detection)
LABEL_THRESHOLDS = {
    "high": 0.15,
    "medium": 0.08,
    "low": 0.03,
    "irrelevant": 0.0,
}


def load_validation_set() -> List[dict]:
    """Load ground truth validation grants."""
    with open(VALIDATION_SET_FILE, encoding="utf-8") as f:
        return json.load(f)


def grants_from_validation_set(entries: List[dict]) -> List[Grant]:
    """Convert validation entries to Grant objects."""
    grants = []
    for entry in entries:
        g = Grant(
            id=entry["id"],
            title=entry["title"],
            agency=entry.get("agency", "Unknown"),
            source=entry.get("source", "nih"),
            url=f"https://example.com/{entry['id']}",
            description=entry.get("description", ""),
            amount_max=entry.get("amount_max"),
            keywords=[],
            raw_data={},
        )
        grants.append(g)
    return grants


def evaluate_scoring(scorer: RelevanceScorer = None) -> Dict:
    """Run scoring validation and return metrics.

    Returns dict with:
    - precision_at_10: precision@10 (fraction of top-10 that are high/medium)
    - precision_at_20: precision@20
    - label_avg_scores: avg score per label
    - rank_order_correct: whether high >= medium >= low >= irrelevant on average
    - misclassifications: high/medium grants scoring at or below irrelevant average
    - total_grants: total number of grants evaluated
    - scored_grants: full list sorted by score descending
    """
    if scorer is None:
        scorer = RelevanceScorer()

    entries = load_validation_set()
    grants = grants_from_validation_set(entries)

    # Score all grants
    scored = []
    for grant, entry in zip(grants, entries):
        score = scorer.score(grant)
        scored.append({
            "id": entry["id"],
            "title": entry["title"],
            "label": entry["relevance_label"],
            "score": score,
        })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Precision@K: fraction of top-K that are "high" or "medium"
    def precision_at_k(k: int) -> float:
        top_k = scored[:k]
        relevant = sum(1 for s in top_k if s["label"] in ("high", "medium"))
        return relevant / k if k > 0 else 0.0

    # Per-label average scores
    label_scores: Dict[str, float] = {}
    for label in ("high", "medium", "low", "irrelevant"):
        label_grants = [s for s in scored if s["label"] == label]
        if label_grants:
            label_scores[label] = sum(s["score"] for s in label_grants) / len(label_grants)
        else:
            label_scores[label] = 0.0

    # Rank order check: high_avg >= medium_avg >= low_avg >= irrelevant_avg
    rank_order_correct = (
        label_scores.get("high", 0) >= label_scores.get("medium", 0)
        >= label_scores.get("low", 0) >= label_scores.get("irrelevant", 0)
    )

    # Misclassifications: high/medium grants scoring at or below irrelevant average
    irrelevant_avg = label_scores.get("irrelevant", 0)
    misclassifications = [
        s for s in scored
        if s["label"] in ("high", "medium") and s["score"] <= irrelevant_avg
    ]

    return {
        "precision_at_10": round(precision_at_k(10), 3),
        "precision_at_20": round(precision_at_k(20), 3),
        "label_avg_scores": {k: round(v, 4) for k, v in label_scores.items()},
        "rank_order_correct": rank_order_correct,
        "misclassifications": misclassifications,
        "total_grants": len(scored),
        "scored_grants": scored,
    }
