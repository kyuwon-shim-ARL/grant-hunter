"""Tests for RelevanceScorer."""

import pytest
from grant_hunter.scoring import RelevanceScorer
from tests.conftest import make_grant


@pytest.fixture
def scorer():
    return RelevanceScorer()


def test_score_returns_value_between_0_and_1(scorer):
    grant = make_grant(
        id="SCR-001",
        title="Antimicrobial resistance machine learning",
        source="nih",
        description="Using AI to tackle drug-resistant bacteria.",
    )
    score = scorer.score(grant)
    assert 0.0 <= score <= 1.0


def test_amr_ai_heavy_grant_scores_higher_than_generic(scorer):
    heavy = make_grant(
        id="HEAVY-001",
        title="Machine learning deep learning artificial intelligence antimicrobial resistance antibiotic",
        source="nih",
        description=(
            "Antimicrobial resistance AMR antibiotic resistance drug-resistant bacteria. "
            "Machine learning deep learning neural network AI artificial intelligence."
        ),
        amount_max=5_000_000.0,
    )
    generic = make_grant(
        id="GENERIC-001",
        title="General Health Research",
        source="nih",
        description="A general health research project with broad scope.",
        amount_max=100_000.0,
    )
    assert scorer.score(heavy) > scorer.score(generic)


def test_no_relevant_keywords_scores_low(scorer):
    grant = make_grant(
        id="LOW-001",
        title="Urban planning and infrastructure",
        source="eu",
        description="This grant funds research on urban development and city planning.",
    )
    score = scorer.score(grant)
    # With no AMR or AI keywords, score should be near 0 (only amount bonus)
    assert score < 0.2


def test_scorer_handles_empty_description(scorer):
    grant = make_grant(
        id="EMPTY-001",
        title="",
        source="nih",
        description="",
        keywords=[],
    )
    score = scorer.score(grant)
    assert 0.0 <= score <= 1.0
