"""Integration tests for unified scoring pipeline (v2.8 Score-First Architecture).

Verifies that:
1. score_and_rank_grants uses RelevanceScorer (0-1 normalized) consistently
2. ALL grants are scored and returned (no gate filtering)
3. Scores match RelevanceScorer.score() directly (no tier2 penalty)
4. No dual scoring: filters.py and scoring.py produce the same score
"""

import pytest
from grant_hunter.filters import score_and_rank_grants, filter_grants, passes_keyword_gate
from grant_hunter.scoring import RelevanceScorer
from tests.conftest import make_grant


@pytest.fixture
def scorer():
    return RelevanceScorer()


@pytest.fixture
def amr_ai_grant():
    return make_grant(
        id="INT-001",
        title="Machine learning for antimicrobial resistance",
        source="nih",
        description=(
            "Using artificial intelligence and deep learning to study "
            "antimicrobial resistance and antibiotic resistance in drug discovery."
        ),
        amount_max=2_000_000.0,
    )


@pytest.fixture
def amr_only_grant():
    return make_grant(
        id="INT-002",
        title="Antibiotic resistance surveillance",
        source="nih",
        description="Study of antimicrobial resistance patterns in drug-resistant bacteria.",
    )


def test_filter_grants_sets_normalized_score(amr_ai_grant, scorer):
    """score_and_rank_grants should set relevance_score using RelevanceScorer (0-1)."""
    result = score_and_rank_grants([amr_ai_grant])
    assert len(result) == 1
    g = result[0]
    # Score should be between 0 and 1 (normalized)
    assert 0.0 < g.relevance_score <= 1.0
    # Score should exactly match RelevanceScorer directly (no tier2 penalty)
    expected = scorer.score(amr_ai_grant)
    assert g.relevance_score == expected


def test_filter_grants_score_matches_scorer(scorer):
    """Unified scoring: score_and_rank_grants and RelevanceScorer produce identical scores."""
    grants = [
        make_grant(
            id=f"UNIFY-{i}",
            title=title,
            source="nih",
            description=desc,
            amount_max=amount,
        )
        for i, (title, desc, amount) in enumerate([
            (
                "AI-driven antimicrobial resistance drug discovery",
                "Machine learning approaches to combat drug-resistant bacteria using deep learning.",
                5_000_000.0,
            ),
            (
                "Computational approaches to antibiotic resistance",
                "Artificial intelligence and bioinformatics for AMR pathogen detection.",
                1_000_000.0,
            ),
        ])
    ]

    filtered = score_and_rank_grants(grants)
    for g in filtered:
        scorer_score = scorer.score(g)
        assert g.relevance_score == scorer_score, (
            f"Score mismatch for '{g.title}': "
            f"filter={g.relevance_score}, scorer={scorer_score}"
        )


def test_passes_keyword_gate_requires_amr_and_ai(amr_ai_grant, amr_only_grant):
    """Keyword gate: AMR+AI → tier1, AMR-only → tier2."""
    assert passes_keyword_gate(amr_ai_grant) == "tier1"
    assert passes_keyword_gate(amr_only_grant) == "tier2"


def test_filtered_grants_sorted_by_score_descending():
    """Scored grants should be sorted by relevance_score descending."""
    grants = [
        make_grant(
            id="SORT-LOW",
            title="Antimicrobial resistance computational analysis",
            source="nih",
            description="Machine learning for AMR.",
        ),
        make_grant(
            id="SORT-HIGH",
            title="Deep learning artificial intelligence antimicrobial resistance antibiotic drug discovery",
            source="nih",
            description=(
                "Machine learning deep learning neural network AI artificial intelligence "
                "antimicrobial resistance AMR antibiotic resistance drug-resistant bacteria "
                "drug discovery lead optimization high-throughput screening."
            ),
            amount_max=10_000_000.0,
        ),
    ]
    result = score_and_rank_grants(grants)
    assert len(result) == 2
    assert result[0].relevance_score >= result[1].relevance_score
    assert result[0].id == "SORT-HIGH"


def test_unrelated_grants_receive_score():
    """All grants are scored including unrelated ones; unrelated grants score at 0.0 or near 0."""
    grant = make_grant(
        id="UNRELATED-001",
        title="Climate change policy",
        source="eu",
        description="Studying environmental policy impacts.",
    )
    result = score_and_rank_grants([grant])
    # ALL grants are returned now (no gate filtering)
    assert len(result) == 1
    # Unrelated grant is scored (score set), and should be 0.0 or very close
    assert result[0].id == "UNRELATED-001"
    assert result[0].relevance_score == pytest.approx(0.0, abs=0.05)
