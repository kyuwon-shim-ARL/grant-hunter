"""Gold set infrastructure for Grant Hunter v4.0 evaluation.

Provides rubric definitions, stratified sampling, gold set I/O,
and ranking evaluation metrics (precision@k, NDCG@k, recall@k, bootstrap CI).
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from grant_hunter.config import DATA_HOME
from grant_hunter.models import Grant

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUBRIC_VERSION = "1.0"

RELEVANCE_RUBRIC: Dict[int, str] = {
    0: "주제 무관 (AMR/AI/Drug 어느 축과도 관련 없음)",
    1: "분야만 일치 (AMR 또는 AI 관련이나 IPK 연구 방향과 교차점 약함)",
    2: "방법론+분야 일치 (AI×AMR 교차점 존재, IPK가 기여 가능)",
    3: "연구목표 직접 부합 (AI 기반 AMR 해결, IPK 핵심 역량과 직결, 지원 필수)",
}

GOLD_SET_PATH: Path = DATA_HOME / "labels" / "gold_set.json"

# Tier thresholds based on relevance_score
_TIER_THRESHOLDS = {
    "T1": 0.40,
    "T2": 0.28,
    "T3": 0.20,
    "T4": 0.0,   # catch-all below T3
}

# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------


def _assign_tier(score: float) -> str:
    if score >= _TIER_THRESHOLDS["T1"]:
        return "T1"
    if score >= _TIER_THRESHOLDS["T2"]:
        return "T2"
    if score >= _TIER_THRESHOLDS["T3"]:
        return "T3"
    return "T4"


# ---------------------------------------------------------------------------
# Stratified sampling
# ---------------------------------------------------------------------------


def sample_for_labeling(grants: List[Grant], n: int = 30) -> List[Grant]:
    """Return a stratified sample of *n* grants for manual labeling.

    Strategy
    --------
    - Bucket grants into tiers T1–T4 by ``relevance_score``.
    - Also force-include grants with ``relevance_score >= 0.10`` that might
      otherwise be under-represented in T4 to catch potential false negatives.
    - Allocate slots roughly equally across available tiers, with a minimum of
      5 per tier when possible.
    - Within each tier, sort by ``relevance_score`` descending before sampling
      so the highest-scoring items are preferred.
    - If a tier has fewer grants than its allocated slots, the remaining slots
      are redistributed to other tiers.

    Parameters
    ----------
    grants:
        Full list of scored Grant objects.
    n:
        Target sample size (default 30).

    Returns
    -------
    List of Grant objects, sorted by ``relevance_score`` descending.
    """
    if not grants:
        return []

    # Build tier buckets
    buckets: Dict[str, List[Grant]] = {t: [] for t in ("T1", "T2", "T3", "T4")}
    for g in grants:
        buckets[_assign_tier(g.relevance_score)].append(g)

    # Sort each bucket descending by score
    for tier in buckets:
        buckets[tier].sort(key=lambda g: g.relevance_score, reverse=True)

    available_tiers = [t for t in ("T1", "T2", "T3", "T4") if buckets[t]]
    if not available_tiers:
        return []

    # Initial equal allocation with minimum-5 guarantee
    min_per_tier = 5
    base_alloc = max(min_per_tier, n // len(available_tiers))
    alloc: Dict[str, int] = {t: min(base_alloc, len(buckets[t])) for t in available_tiers}

    # Redistribute leftover slots
    total_allocated = sum(alloc.values())
    remaining = n - total_allocated
    if remaining > 0:
        # Give extra slots to tiers that still have headroom, highest tier first
        for tier in ("T1", "T2", "T3", "T4"):
            if tier not in available_tiers or remaining <= 0:
                continue
            headroom = len(buckets[tier]) - alloc[tier]
            extra = min(headroom, remaining)
            alloc[tier] += extra
            remaining -= extra

    # Draw samples per tier (top-N by score, then shuffle within tier is
    # deliberately avoided to keep highest-score grants in the set)
    sampled: List[Grant] = []
    for tier in ("T1", "T2", "T3", "T4"):
        if tier not in available_tiers:
            continue
        sampled.extend(buckets[tier][: alloc[tier]])

    # Ensure false-negative candidates (score >= 0.10 in T4) are represented
    fn_candidates = [
        g for g in buckets.get("T4", [])
        if g.relevance_score >= 0.10 and g not in sampled
    ]
    fn_candidates.sort(key=lambda g: g.relevance_score, reverse=True)
    # Add up to 5 false-negative candidates if budget allows
    fn_budget = max(0, n - len(sampled))
    sampled.extend(fn_candidates[: min(5, fn_budget)])

    # Deduplicate preserving order
    seen: set = set()
    unique: List[Grant] = []
    for g in sampled:
        if g.id not in seen:
            seen.add(g.id)
            unique.append(g)

    # Final sort: score descending
    unique.sort(key=lambda g: g.relevance_score, reverse=True)
    return unique[:n]


# ---------------------------------------------------------------------------
# Gold set I/O
# ---------------------------------------------------------------------------

_REQUIRED_LABEL_KEYS = {"grant_id", "label", "labeler", "timestamp", "rubric_version"}


def save_gold_set(labels: List[dict], path: Optional[Path] = None) -> None:
    """Persist gold set labels to *path* (default: GOLD_SET_PATH).

    Each entry must contain: grant_id, label, labeler, timestamp, rubric_version.
    Missing timestamps are filled with the current UTC time.

    Parameters
    ----------
    labels:
        List of label dicts.
    path:
        Destination file. Defaults to ``GOLD_SET_PATH``.
    """
    dest = path or GOLD_SET_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat()
    validated: List[dict] = []
    for i, entry in enumerate(labels):
        if not isinstance(entry, dict):
            raise ValueError(f"Label at index {i} is not a dict: {entry!r}")
        missing = _REQUIRED_LABEL_KEYS - entry.keys()
        if missing - {"timestamp", "rubric_version"}:
            raise ValueError(
                f"Label at index {i} missing required keys: {missing - {'timestamp', 'rubric_version'}}"
            )
        row = dict(entry)
        row.setdefault("timestamp", now_iso)
        row.setdefault("rubric_version", RUBRIC_VERSION)
        # Coerce label to int
        try:
            row["label"] = int(row["label"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Label at index {i} has non-integer 'label': {row['label']!r}"
            ) from exc
        if row["label"] not in RELEVANCE_RUBRIC:
            raise ValueError(
                f"Label at index {i} has out-of-range label {row['label']}; "
                f"valid values: {list(RELEVANCE_RUBRIC.keys())}"
            )
        validated.append(row)

    with dest.open("w", encoding="utf-8") as fh:
        json.dump(validated, fh, ensure_ascii=False, indent=2)


def load_gold_set(path: Optional[Path] = None) -> List[dict]:
    """Load gold set labels from *path* (default: GOLD_SET_PATH).

    Validates schema on load; raises ``ValueError`` on malformed entries.

    Parameters
    ----------
    path:
        Source file. Defaults to ``GOLD_SET_PATH``.

    Returns
    -------
    List of validated label dicts.
    """
    src = path or GOLD_SET_PATH
    if not src.exists():
        raise FileNotFoundError(f"Gold set file not found: {src}")

    with src.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list):
        raise ValueError(f"Gold set file must contain a JSON array, got {type(data).__name__}")

    validated: List[dict] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry at index {i} is not a dict")
        missing = _REQUIRED_LABEL_KEYS - entry.keys()
        if missing:
            raise ValueError(f"Entry at index {i} missing keys: {missing}")
        row = dict(entry)
        row["label"] = int(row["label"])
        validated.append(row)

    return validated


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------


def precision_at_k(
    ranked_ids: List[str],
    gold: Dict[str, int],
    k: int = 10,
    threshold: int = 2,
) -> float:
    """Fraction of top-*k* grants whose gold label is >= *threshold*.

    Parameters
    ----------
    ranked_ids:
        Grant IDs ordered from most to least relevant by the system.
    gold:
        Mapping of grant_id -> integer relevance label.
    k:
        Cutoff rank.
    threshold:
        Minimum label to count as relevant.

    Returns
    -------
    Float in [0, 1]. Returns 0.0 when k == 0 or top-k is empty.
    """
    if k <= 0:
        return 0.0
    top_k = [gid for gid in ranked_ids[:k] if gid in gold]
    if not top_k:
        return 0.0
    hits = sum(1 for gid in top_k if gold[gid] >= threshold)
    return hits / k


def ndcg_at_k(
    ranked_ids: List[str],
    gold: Dict[str, int],
    k: int = 10,
) -> float:
    """Normalised Discounted Cumulative Gain at *k* using gold labels as gains.

    Parameters
    ----------
    ranked_ids:
        Grant IDs ordered from most to least relevant by the system.
    gold:
        Mapping of grant_id -> integer relevance label.
    k:
        Cutoff rank.

    Returns
    -------
    Float in [0, 1]. Returns 0.0 when there are no relevant labels.
    """
    if k <= 0:
        return 0.0

    def _dcg(ordered_gains: List[int], cutoff: int) -> float:
        total = 0.0
        for rank, gain in enumerate(ordered_gains[:cutoff], start=1):
            total += gain / math.log2(rank + 1)
        return total

    # System DCG
    system_gains = [gold.get(gid, 0) for gid in ranked_ids[:k]]
    dcg = _dcg(system_gains, k)

    # Ideal DCG: sort gold labels in gold descending, take top-k
    ideal_gains = sorted(gold.values(), reverse=True)
    idcg = _dcg(ideal_gains, k)

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def recall_at_k(
    ranked_ids: List[str],
    gold: Dict[str, int],
    k: int = 10,
    threshold: int = 2,
) -> float:
    """Fraction of relevant grants (gold label >= *threshold*) appearing in top-*k*.

    Parameters
    ----------
    ranked_ids:
        Grant IDs ordered from most to least relevant by the system.
    gold:
        Mapping of grant_id -> integer relevance label.
    k:
        Cutoff rank.
    threshold:
        Minimum label to count as relevant.

    Returns
    -------
    Float in [0, 1]. Returns 0.0 when there are no relevant grants in gold.
    """
    relevant_ids = {gid for gid, lbl in gold.items() if lbl >= threshold}
    if not relevant_ids:
        return 0.0
    top_k_set = set(ranked_ids[:k])
    hits = len(relevant_ids & top_k_set)
    return hits / len(relevant_ids)


def bootstrap_ci(
    metric_fn: Callable[..., float],
    ranked_ids: List[str],
    gold: Dict[str, int],
    k: int = 10,
    n_bootstrap: int = 1000,
    ci: float = 0.95,
    seed: Optional[int] = None,
    **metric_kwargs,
) -> Tuple[float, float, float]:
    """Bootstrap confidence interval for any metric function.

    Re-samples the gold set (with replacement) *n_bootstrap* times and
    computes the metric for each re-sample.

    Parameters
    ----------
    metric_fn:
        One of ``precision_at_k``, ``ndcg_at_k``, ``recall_at_k``, or a
        compatible callable with signature
        ``(ranked_ids, gold, k, **kwargs) -> float``.
    ranked_ids:
        Grant IDs in ranked order (held fixed across bootstrap iterations).
    gold:
        Mapping of grant_id -> label.
    k:
        Cutoff passed to *metric_fn*.
    n_bootstrap:
        Number of bootstrap replicates.
    ci:
        Confidence level, e.g. 0.95 for 95 % CI.
    seed:
        Optional random seed for reproducibility.
    **metric_kwargs:
        Additional keyword arguments forwarded to *metric_fn*.

    Returns
    -------
    Tuple of (point_estimate, lower_bound, upper_bound) where the bounds
    correspond to the requested CI percentile.
    """
    if not gold:
        return (0.0, 0.0, 0.0)

    rng = random.Random(seed)
    gold_items = list(gold.items())
    n = len(gold_items)

    point_estimate = metric_fn(ranked_ids, gold, k=k, **metric_kwargs)

    scores: List[float] = []
    for _ in range(n_bootstrap):
        # Sample gold set with replacement
        sample_items = [gold_items[rng.randrange(n)] for _ in range(n)]
        sample_gold: Dict[str, int] = {}
        for gid, lbl in sample_items:
            # Last occurrence wins for duplicate keys (consistent with dict)
            sample_gold[gid] = lbl
        score = metric_fn(ranked_ids, sample_gold, k=k, **metric_kwargs)
        scores.append(score)

    scores.sort()
    alpha = 1.0 - ci
    lower_idx = int(math.floor(alpha / 2 * n_bootstrap))
    upper_idx = int(math.ceil((1.0 - alpha / 2) * n_bootstrap)) - 1
    lower_idx = max(0, lower_idx)
    upper_idx = min(n_bootstrap - 1, upper_idx)

    return (point_estimate, scores[lower_idx], scores[upper_idx])
