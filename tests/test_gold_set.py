"""Tests for grant_hunter.gold_set module."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from grant_hunter.gold_set import (
    RELEVANCE_RUBRIC,
    bootstrap_ci,
    load_gold_set,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    sample_for_labeling,
    save_gold_set,
)
from tests.conftest import make_grant


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_label(grant_id: str, label: int) -> dict:
    return {
        "grant_id": grant_id,
        "label": label,
        "labeler": "tester",
        "timestamp": "2026-03-01T00:00:00+00:00",
        "rubric_version": "1.0",
    }


def _make_scored_grants(n: int, base_score: float = 0.0, step: float = 0.05):
    return [
        make_grant(
            id=f"G-{i:03d}",
            title=f"Grant {i}",
            relevance_score=round(base_score + i * step, 4),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# test_rubric_definition
# ---------------------------------------------------------------------------


def test_rubric_definition():
    """RELEVANCE_RUBRIC has exactly 4 entries with keys 0, 1, 2, 3."""
    assert len(RELEVANCE_RUBRIC) == 4
    assert set(RELEVANCE_RUBRIC.keys()) == {0, 1, 2, 3}
    for k, v in RELEVANCE_RUBRIC.items():
        assert isinstance(v, str) and len(v) > 0


# ---------------------------------------------------------------------------
# test_stratified_sampling
# ---------------------------------------------------------------------------


def test_stratified_sampling():
    """Sample produces grants from multiple tiers (balanced coverage)."""
    # Create grants spread across score ranges to hit T1-T4
    grants = (
        [make_grant(id=f"T1-{i}", relevance_score=0.50 + i * 0.01) for i in range(15)]
        + [make_grant(id=f"T2-{i}", relevance_score=0.30 + i * 0.01) for i in range(15)]
        + [make_grant(id=f"T3-{i}", relevance_score=0.22 + i * 0.01) for i in range(10)]
        + [make_grant(id=f"T4-{i}", relevance_score=0.05 + i * 0.01) for i in range(10)]
    )

    sample = sample_for_labeling(grants, n=30)

    assert len(sample) <= 30
    assert len(sample) > 0

    # Should include grants from different score ranges
    ids = {g.id for g in sample}
    t1_in = any(gid.startswith("T1-") for gid in ids)
    t4_in = any(gid.startswith("T4-") for gid in ids)
    assert t1_in, "Expected T1 grants in sample"
    assert t4_in, "Expected T4 grants in sample"

    # Result should be sorted by relevance_score descending
    scores = [g.relevance_score for g in sample]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# test_save_load_roundtrip
# ---------------------------------------------------------------------------


def test_save_load_roundtrip():
    """Save and load gold set; data matches including all required fields."""
    labels = [_make_label(f"G-{i:03d}", i % 4) for i in range(10)]

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "gold.json"
        save_gold_set(labels, path=path)
        loaded = load_gold_set(path=path)

    assert len(loaded) == len(labels)
    for original, restored in zip(labels, loaded):
        assert restored["grant_id"] == original["grant_id"]
        assert restored["label"] == original["label"]
        assert restored["labeler"] == original["labeler"]


# ---------------------------------------------------------------------------
# test_precision_at_k
# ---------------------------------------------------------------------------


def test_precision_at_k():
    """Known ranking → expected precision@k."""
    # 5 grants; gold labels: G-0=3, G-1=0, G-2=2, G-3=1, G-4=3
    ranked_ids = ["G-0", "G-1", "G-2", "G-3", "G-4"]
    gold = {"G-0": 3, "G-1": 0, "G-2": 2, "G-3": 1, "G-4": 3}

    # At k=3: top-3 are G-0(3), G-1(0), G-2(2) — 2 relevant (>= threshold=2)
    assert precision_at_k(ranked_ids, gold, k=3, threshold=2) == pytest.approx(2 / 3)

    # At k=5: G-0(3), G-2(2), G-4(3) are relevant — 3/5
    assert precision_at_k(ranked_ids, gold, k=5, threshold=2) == pytest.approx(3 / 5)

    # At k=0: always 0
    assert precision_at_k(ranked_ids, gold, k=0) == 0.0


# ---------------------------------------------------------------------------
# test_recall_at_k
# ---------------------------------------------------------------------------


def test_recall_at_k():
    """Known ranking → expected recall@k."""
    ranked_ids = ["G-0", "G-1", "G-2", "G-3", "G-4"]
    gold = {"G-0": 3, "G-1": 0, "G-2": 2, "G-3": 1, "G-4": 3}

    # Relevant (>= 2): G-0, G-2, G-4 → 3 total relevant
    # At k=3: G-0, G-2 found → 2/3
    assert recall_at_k(ranked_ids, gold, k=3, threshold=2) == pytest.approx(2 / 3)

    # At k=5: all 3 found → 3/3 = 1.0
    assert recall_at_k(ranked_ids, gold, k=5, threshold=2) == pytest.approx(1.0)

    # No relevant grants → 0.0
    assert recall_at_k(ranked_ids, {"G-0": 0, "G-1": 0}, k=5, threshold=2) == 0.0


# ---------------------------------------------------------------------------
# test_ndcg_at_k
# ---------------------------------------------------------------------------


def test_ndcg_at_k():
    """Known ranking → expected NDCG (compared against hand-calculated value)."""
    # Ideal order: [3, 3, 2, 1, 0]
    # System order: [3, 0, 2, 1, 3]
    ranked_ids = ["G-0", "G-1", "G-2", "G-3", "G-4"]
    gold = {"G-0": 3, "G-1": 0, "G-2": 2, "G-3": 1, "G-4": 3}

    # Hand-calculate DCG@5 for system:
    # rank 1: gain=3, log2(2)=1.0  → 3/1=3.0
    # rank 2: gain=0               → 0
    # rank 3: gain=2, log2(4)=2.0  → 2/2=1.0
    # rank 4: gain=1, log2(5)≈2.322 → 1/2.322≈0.4307
    # rank 5: gain=3, log2(6)≈2.585 → 3/2.585≈1.1610
    dcg_system = (
        3 / math.log2(2)
        + 0 / math.log2(3)
        + 2 / math.log2(4)
        + 1 / math.log2(5)
        + 3 / math.log2(6)
    )

    # Ideal DCG@5: gains sorted [3, 3, 2, 1, 0]
    dcg_ideal = (
        3 / math.log2(2)
        + 3 / math.log2(3)
        + 2 / math.log2(4)
        + 1 / math.log2(5)
        + 0 / math.log2(6)
    )

    expected_ndcg = dcg_system / dcg_ideal

    result = ndcg_at_k(ranked_ids, gold, k=5)
    assert result == pytest.approx(expected_ndcg, rel=1e-4)

    # Perfect ranking (ideal order) → NDCG = 1.0
    perfect_order = ["G-0", "G-4", "G-2", "G-3", "G-1"]  # 3,3,2,1,0
    assert ndcg_at_k(perfect_order, gold, k=5) == pytest.approx(1.0, rel=1e-4)

    # No relevant labels → 0.0
    assert ndcg_at_k(ranked_ids, {"G-0": 0, "G-1": 0}, k=5) == 0.0


# ---------------------------------------------------------------------------
# test_bootstrap_ci
# ---------------------------------------------------------------------------


def test_bootstrap_ci():
    """bootstrap_ci returns (point, lower, upper) with lower <= point <= upper."""
    ranked_ids = ["G-0", "G-1", "G-2", "G-3", "G-4"]
    gold = {"G-0": 3, "G-1": 0, "G-2": 2, "G-3": 1, "G-4": 3}

    point, lower, upper = bootstrap_ci(
        precision_at_k,
        ranked_ids,
        gold,
        k=5,
        n_bootstrap=500,
        ci=0.95,
        seed=42,
        threshold=2,
    )

    assert isinstance(point, float)
    assert isinstance(lower, float)
    assert isinstance(upper, float)
    assert lower <= point
    assert point <= upper

    # Empty gold → (0.0, 0.0, 0.0)
    p2, l2, u2 = bootstrap_ci(precision_at_k, ranked_ids, {}, k=5)
    assert (p2, l2, u2) == (0.0, 0.0, 0.0)
