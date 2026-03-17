"""Tests for filter_grants and diff_grants."""

import pytest
from grant_hunter.filters import filter_grants, diff_grants, passes_keyword_gate
from tests.conftest import make_grant


def test_filter_passes_amr_and_ai_grant():
    """Grant with both AMR + AI keywords passes."""
    grant = make_grant(
        id="PASS-001",
        title="Machine learning for antimicrobial resistance",
        source="nih",
        description=(
            "Using artificial intelligence to study antibiotic resistance "
            "and drug-resistant pathogens."
        ),
    )
    result = filter_grants([grant])
    assert len(result) == 1
    assert result[0].id == "PASS-001"


def test_filter_rejects_amr_only_grant():
    """Grant with only AMR keywords is filtered out."""
    grant = make_grant(
        id="AMR-ONLY-001",
        title="Antibiotic resistance surveillance",
        source="nih",
        description="Study of antimicrobial resistance patterns. Drug-resistant bacteria.",
    )
    result = filter_grants([grant])
    assert len(result) == 0


def test_filter_rejects_ai_only_grant():
    """Grant with only AI keywords is filtered out."""
    grant = make_grant(
        id="AI-ONLY-001",
        title="Deep learning for image recognition",
        source="nih",
        description="Using machine learning and neural networks for computer vision.",
    )
    result = filter_grants([grant])
    assert len(result) == 0


def test_filter_rejects_no_keywords_grant():
    """Grant with no relevant keywords is filtered out."""
    grant = make_grant(
        id="NONE-001",
        title="Climate change research",
        source="eu",
        description="Studying the effects of climate change on biodiversity.",
    )
    result = filter_grants([grant])
    assert len(result) == 0


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


def test_core_amr_gate():
    """Grant with only 1 broad AMR term (surveillance) + ML should NOT pass."""
    grant = make_grant(
        id="BROAD-001",
        title="Surveillance study",
        source="nih",
        description="Using ML for surveillance of infectious disease.",
    )
    assert not passes_keyword_gate(grant)


def test_core_amr_passes():
    """Grant with core AMR keyword (antimicrobial resistance) + ML should pass."""
    grant = make_grant(
        id="CORE-001",
        title="Antimicrobial resistance detection",
        source="nih",
        description="Using ML to detect antimicrobial resistance patterns.",
    )
    assert passes_keyword_gate(grant)


def test_broad_amr_two_hits():
    """Grant with 2 broad AMR keywords (surveillance + metagenomics) + ML should pass."""
    grant = make_grant(
        id="BROAD2-001",
        title="Surveillance and metagenomics study",
        source="nih",
        description="Using machine learning for surveillance and metagenomics.",
    )
    assert passes_keyword_gate(grant)
