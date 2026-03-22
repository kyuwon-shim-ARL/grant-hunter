"""Tests for score_and_rank_grants, filter_grants (alias), diff_grants, and passes_keyword_gate."""

import pytest
from grant_hunter.filters import score_and_rank_grants, filter_grants, diff_grants, passes_keyword_gate
from tests.conftest import make_grant


# ---------------------------------------------------------------------------
# score_and_rank_grants / filter_grants (alias) — all grants returned
# ---------------------------------------------------------------------------

def test_filter_passes_amr_and_ai_grant():
    """Grant with both AMR + AI keywords is returned."""
    grant = make_grant(
        id="PASS-001",
        title="Machine learning for antimicrobial resistance",
        source="nih",
        description=(
            "Using artificial intelligence to study antibiotic resistance "
            "and drug-resistant pathogens."
        ),
    )
    result = score_and_rank_grants([grant])
    assert len(result) == 1
    assert result[0].id == "PASS-001"


def test_filter_includes_amr_only_as_tier2():
    """Grant with only AMR keywords is still included and has a positive score."""
    grant = make_grant(
        id="AMR-ONLY-001",
        title="Antibiotic resistance surveillance",
        source="nih",
        description="Study of antimicrobial resistance patterns in healthcare settings.",
    )
    result = score_and_rank_grants([grant])
    assert len(result) == 1
    assert result[0].relevance_score > 0.0


def test_filter_rejects_ai_only_grant():
    """Grant with only AI keywords is included but scores lower than an AMR+AI grant."""
    ai_only = make_grant(
        id="AI-ONLY-001",
        title="Deep learning for image recognition",
        source="nih",
        description="Using machine learning and neural networks for computer vision.",
    )
    amr_ai = make_grant(
        id="AMR-AI-001",
        title="Machine learning for antimicrobial resistance",
        source="nih",
        description=(
            "Using artificial intelligence to study antibiotic resistance "
            "and drug-resistant pathogens."
        ),
    )
    result = score_and_rank_grants([ai_only, amr_ai])
    assert len(result) == 2
    # AMR+AI grant should score higher than AI-only grant
    amr_ai_result = next(r for r in result if r.id == "AMR-AI-001")
    ai_only_result = next(r for r in result if r.id == "AI-ONLY-001")
    assert amr_ai_result.relevance_score > ai_only_result.relevance_score


def test_filter_rejects_no_keywords_grant():
    """Grant with no relevant keywords is included but scores ~0.0."""
    grant = make_grant(
        id="NONE-001",
        title="Climate change research",
        source="eu",
        description="Studying the effects of climate change on biodiversity.",
    )
    result = score_and_rank_grants([grant])
    assert len(result) == 1
    assert result[0].relevance_score < 0.05


# ---------------------------------------------------------------------------
# diff_grants — keep as-is
# ---------------------------------------------------------------------------

def test_diff_grants_detects_new():
    """diff_grants detects a new grant not in previous snapshot."""
    current = [
        make_grant(id="NEW-001", source="nih", title="New Grant"),
        make_grant(id="OLD-001", source="nih", title="Old Grant"),
    ]
    previous = [
        make_grant(id="OLD-001", source="nih", title="Old Grant"),
    ]
    new_grants, changed_grants = diff_grants(current, previous)
    assert len(new_grants) == 1
    assert new_grants[0].id == "NEW-001"
    assert len(changed_grants) == 0


def test_diff_grants_detects_changed():
    """diff_grants detects a changed grant (same id, different title)."""
    current = [
        make_grant(id="CHG-001", source="nih", title="Updated Title"),
    ]
    previous = [
        make_grant(id="CHG-001", source="nih", title="Original Title"),
    ]
    new_grants, changed_grants = diff_grants(current, previous)
    assert len(new_grants) == 0
    assert len(changed_grants) == 1
    assert changed_grants[0].title == "Updated Title"


# ---------------------------------------------------------------------------
# passes_keyword_gate — keep as-is
# ---------------------------------------------------------------------------

def test_core_amr_gate():
    """Grant with only 1 broad AMR term (surveillance) + ML should be skip (no core AMR)."""
    grant = make_grant(
        id="BROAD-001",
        title="Surveillance study",
        source="nih",
        description="Using ML for surveillance of infectious disease.",
    )
    assert passes_keyword_gate(grant) == "skip"


def test_core_amr_passes_tier1():
    """Grant with core AMR keyword (antimicrobial resistance) + ML should be tier1."""
    grant = make_grant(
        id="CORE-001",
        title="Antimicrobial resistance detection",
        source="nih",
        description="Using ML to detect antimicrobial resistance patterns.",
    )
    assert passes_keyword_gate(grant) == "tier1"


def test_broad_amr_two_hits_tier1():
    """Grant with 2 broad AMR keywords (surveillance + metagenomics) + ML should be tier1."""
    grant = make_grant(
        id="BROAD2-001",
        title="Surveillance and metagenomics study",
        source="nih",
        description="Using machine learning for surveillance and metagenomics.",
    )
    assert passes_keyword_gate(grant) == "tier1"


def test_amr_only_tier2():
    """Grant with AMR core keyword but no AI should be tier2."""
    grant = make_grant(
        id="TIER2-001",
        title="Antimicrobial resistance in hospitals",
        source="nih",
        description="Study of antibiotic resistance and MRSA in healthcare settings.",
    )
    assert passes_keyword_gate(grant) == "tier2"


def test_plural_keyword_matching_ai():
    """'predictive models' (plural) should match 'predictive model' keyword."""
    grant = make_grant(
        id="PLURAL-AI-001",
        title="Predictive models for antimicrobial resistance",
        source="nih",
        description=(
            "We develop predictive models using neural networks to study "
            "antimicrobial resistance patterns."
        ),
    )
    result = passes_keyword_gate(grant)
    assert result == "tier1", f"Expected tier1, got {result}"


def test_plural_keyword_matching_amr():
    """'antimicrobial compounds' should get AMR hits via standalone 'antimicrobial' keyword."""
    from grant_hunter.filters import _count_hits, AMR_KEYWORDS

    text = "Novel antimicrobial compounds targeting drug-resistant bacteria."
    hits, matched = _count_hits(text, AMR_KEYWORDS)
    assert hits >= 1, f"Expected AMR hits, got 0. matched={matched}"
    assert any("antimicrobial" in kw.lower() for kw in matched)


# ---------------------------------------------------------------------------
# New tests for Score-First Architecture
# ---------------------------------------------------------------------------

def test_score_ranking_amr_ai_above_amr_only():
    """AMR+AI grant should score higher than AMR-only grant."""
    amr_ai = make_grant(
        id="AMR-AI-RANK-001",
        title="Machine learning for antimicrobial resistance",
        source="nih",
        description=(
            "Using artificial intelligence and deep learning to study "
            "antimicrobial resistance and antibiotic resistance."
        ),
    )
    amr_only = make_grant(
        id="AMR-ONLY-RANK-001",
        title="Antimicrobial resistance in hospitals",
        source="nih",
        description="Study of antibiotic resistance and MRSA in healthcare settings.",
    )
    result = score_and_rank_grants([amr_only, amr_ai])
    assert len(result) == 2
    amr_ai_result = next(r for r in result if r.id == "AMR-AI-RANK-001")
    amr_only_result = next(r for r in result if r.id == "AMR-ONLY-RANK-001")
    assert amr_ai_result.relevance_score > amr_only_result.relevance_score


def test_score_ranking_amr_only_above_unrelated():
    """AMR-only grant should score higher than a completely unrelated grant."""
    amr_only = make_grant(
        id="AMR-RANK-002",
        title="Antimicrobial resistance surveillance",
        source="nih",
        description="Study of antimicrobial resistance patterns in healthcare settings.",
    )
    unrelated = make_grant(
        id="UNRELATED-RANK-001",
        title="Climate change research",
        source="eu",
        description="Studying the effects of climate change on biodiversity.",
    )
    result = score_and_rank_grants([unrelated, amr_only])
    assert len(result) == 2
    amr_result = next(r for r in result if r.id == "AMR-RANK-002")
    unrelated_result = next(r for r in result if r.id == "UNRELATED-RANK-001")
    assert amr_result.relevance_score > unrelated_result.relevance_score


def test_all_grants_returned():
    """score_and_rank_grants returns the same number of grants as input."""
    grants = [
        make_grant(id="G-001", title="AMR + AI grant", source="nih",
                   description="Machine learning for antimicrobial resistance."),
        make_grant(id="G-002", title="AMR-only grant", source="nih",
                   description="Antibiotic resistance in hospitals."),
        make_grant(id="G-003", title="AI-only grant", source="nih",
                   description="Deep learning for computer vision."),
        make_grant(id="G-004", title="Unrelated grant", source="eu",
                   description="Climate change research."),
    ]
    result = score_and_rank_grants(grants)
    assert len(result) == len(grants)


def test_unrelated_grant_gets_zero_or_near_zero_score():
    """Grant with no relevant keywords receives a near-zero relevance score."""
    grant = make_grant(
        id="ZERO-001",
        title="Climate change and biodiversity",
        source="eu",
        description="Studying the effects of climate change on biodiversity and ecosystems.",
    )
    result = score_and_rank_grants([grant])
    assert len(result) == 1
    assert result[0].relevance_score < 0.05


def test_tier2_amr_plus_drug_discovery_scores_higher_than_amr_only():
    """AMR+drug_discovery grant scores higher than pure AMR-only (natural scoring, no penalty)."""
    pure_amr = make_grant(
        id="TIER2-PURE-002",
        title="Antimicrobial resistance in hospitals",
        source="nih",
        description="Study of antibiotic resistance and MRSA in healthcare settings.",
    )
    amr_drug = make_grant(
        id="TIER2-DRUG-001",
        title="Antimicrobial resistance drug discovery",
        source="nih",
        description=(
            "Study of antibiotic resistance and MRSA. "
            "Novel antibiotic drug discovery and lead optimization."
        ),
    )
    result = score_and_rank_grants([pure_amr, amr_drug])
    assert len(result) == 2
    pure_result = next(r for r in result if r.id == "TIER2-PURE-002")
    drug_result = next(r for r in result if r.id == "TIER2-DRUG-001")
    assert drug_result.relevance_score > pure_result.relevance_score


def test_filter_grants_alias():
    """filter_grants is a backward-compatible alias for score_and_rank_grants."""
    grants = [
        make_grant(id="ALIAS-001", title="AMR + AI grant", source="nih",
                   description="Machine learning for antimicrobial resistance."),
    ]
    assert filter_grants(grants) == score_and_rank_grants(grants)
