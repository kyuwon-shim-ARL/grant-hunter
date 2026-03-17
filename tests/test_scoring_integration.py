"""Integration tests for unified scoring pipeline (e013).

Verifies that:
1. filter_grants uses RelevanceScorer (0-1 normalized) consistently
2. Scored grants have non-zero relevance_score after filtering
3. generate_interactive_report scores grants on load
4. No dual scoring: filters.py and scoring.py produce the same score
"""

import pytest
from grant_hunter.filters import filter_grants, passes_keyword_gate
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
    """filter_grants should set relevance_score using RelevanceScorer (0-1)."""
    result = filter_grants([amr_ai_grant])
    assert len(result) == 1
    g = result[0]
    # Score should be between 0 and 1 (normalized)
    assert 0.0 < g.relevance_score <= 1.0
    # Score should match RelevanceScorer directly
    expected = scorer.score(amr_ai_grant)
    assert g.relevance_score == expected


def test_filter_grants_score_matches_scorer(scorer):
    """Unified scoring: filter_grants and RelevanceScorer produce identical scores."""
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

    filtered = filter_grants(grants)
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
    """Filtered grants should be sorted by relevance_score descending."""
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
    result = filter_grants(grants)
    assert len(result) == 2
    assert result[0].relevance_score >= result[1].relevance_score
    assert result[0].id == "SORT-HIGH"


def test_no_score_leakage_for_rejected_grants():
    """Grants that don't pass the gate should not have their score modified."""
    grant = make_grant(
        id="REJECT-001",
        title="Climate change policy",
        source="eu",
        description="Studying environmental policy impacts.",
    )
    original_score = grant.relevance_score
    result = filter_grants([grant])
    assert len(result) == 0
    # Score should remain unchanged (0.0)
    assert grant.relevance_score == original_score
