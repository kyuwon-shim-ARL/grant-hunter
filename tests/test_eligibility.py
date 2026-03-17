"""Tests for EligibilityEngine - IPK eligibility rules."""

import pytest
from grant_hunter.eligibility import EligibilityEngine
from tests.conftest import make_grant


@pytest.fixture
def engine():
    return EligibilityEngine()


# ── HIC_EXCLUDE ───────────────────────────────────────────────────────────────

def test_hic_exclude_lmic_description(engine):
    grant = make_grant(
        id="HIC-001",
        title="Research Grant",
        source="eu",
        description="Open to low-income and developing countries only.",
    )
    result = engine.check(grant)
    assert result.status == "ineligible"
    assert any("HIC_EXCLUDE" in r for r in result.rules_matched)


def test_hic_exclude_eligible_when_no_lmic(engine):
    grant = make_grant(
        id="HIC-002",
        title="Research Grant",
        source="eu",
        description="Open to research institutes worldwide.",
    )
    result = engine.check(grant)
    # Should not be ineligible due to HIC_EXCLUDE
    assert not any("HIC_EXCLUDE" in r for r in result.rules_matched)


# ── UNIVERSITY_ONLY ───────────────────────────────────────────────────────────

def test_university_only_ineligible(engine):
    grant = make_grant(
        id="UNIV-001",
        title="Faculty Research Grant",
        source="nih",
        description="Open to universities only. Faculty member only applications accepted.",
    )
    result = engine.check(grant)
    assert result.status == "ineligible"
    assert any("UNIVERSITY_ONLY" in r for r in result.rules_matched)


def test_university_only_not_triggered(engine):
    grant = make_grant(
        id="UNIV-002",
        title="Research Institute Grant",
        source="nih",
        description="Open to research centers and non-profit organizations.",
    )
    result = engine.check(grant)
    assert not any("UNIVERSITY_ONLY" in r for r in result.rules_matched)


# ── US_ONLY ───────────────────────────────────────────────────────────────────

def test_us_only_ineligible(engine):
    grant = make_grant(
        id="US-001",
        title="Domestic Research Grant",
        source="grants_gov",
        description="US domestic institutions only. Domestic applicants only.",
    )
    result = engine.check(grant)
    assert result.status == "ineligible"
    assert any("US_ONLY" in r for r in result.rules_matched)


def test_us_only_nih_r01_exempt(engine):
    """NIH R01 is foreign-eligible and should not be blocked by US_ONLY."""
    grant = make_grant(
        id="R01-GM123456",
        title="NIH R01 Grant for AMR research",
        source="nih",
        description="US domestic institutions only. Must be a U.S. institution.",
    )
    result = engine.check(grant)
    # R01 in ID should exempt from US_ONLY
    assert not any("US_ONLY" in r for r in result.rules_matched)
    assert any("NIH_FOREIGN_ELIGIBLE" in r for r in result.rules_matched)


# ── INDUSTRY_ONLY ─────────────────────────────────────────────────────────────

def test_industry_only_ineligible(engine):
    grant = make_grant(
        id="IND-001",
        title="Industry Partnership Grant",
        source="grants_gov",
        description="For-profit only companies. Private sector only applicants.",
    )
    result = engine.check(grant)
    assert result.status == "ineligible"
    assert any("INDUSTRY_ONLY" in r for r in result.rules_matched)


def test_industry_only_not_triggered(engine):
    grant = make_grant(
        id="IND-002",
        title="Non-profit Research Grant",
        source="nih",
        description="Open to non-profit research institutions.",
    )
    result = engine.check(grant)
    assert not any("INDUSTRY_ONLY" in r for r in result.rules_matched)


# ── NAMED_INELIGIBLE ─────────────────────────────────────────────────────────

def test_named_ineligible_amr_action_fund(engine):
    grant = make_grant(
        id="AMR-AF-001",
        title="AMR Action Fund Investment Round",
        source="eu",
        description="AMR Action Fund equity investment for antimicrobial drug developers.",
    )
    result = engine.check(grant)
    assert result.status == "ineligible"
    assert any("NAMED_INELIGIBLE" in r for r in result.rules_matched)


def test_named_ineligible_longitude_prize(engine):
    grant = make_grant(
        id="LONG-001",
        title="Longitude Prize for AMR diagnostics",
        source="eu",
        description="The Longitude Prize competition for diagnostic solutions.",
    )
    result = engine.check(grant)
    assert result.status == "ineligible"
    assert any("NAMED_INELIGIBLE" in r for r in result.rules_matched)


# ── LMIC_COUNTRY ─────────────────────────────────────────────────────────────

def test_lmic_country_ineligible(engine):
    grant = make_grant(
        id="LMIC-C-001",
        title="National Government Grant",
        source="eu",
        description="National government only. ODA recipient countries exclusively.",
    )
    result = engine.check(grant)
    assert result.status == "ineligible"
    assert any("LMIC_COUNTRY" in r for r in result.rules_matched)


def test_lmic_country_not_triggered(engine):
    grant = make_grant(
        id="LMIC-C-002",
        title="International Research Collaboration",
        source="eu",
        description="Open to research institutes in any country.",
    )
    result = engine.check(grant)
    assert not any("LMIC_COUNTRY" in r for r in result.rules_matched)


# ── NONPROFIT_POSITIVE ────────────────────────────────────────────────────────

def test_nonprofit_positive_eligible(engine):
    grant = make_grant(
        id="NP-001",
        title="Non-profit Research Grant",
        source="nih",
        description="Open to non-profit and research institute applicants worldwide.",
    )
    result = engine.check(grant)
    assert result.status == "eligible"
    assert any("NONPROFIT_POSITIVE" in r for r in result.rules_matched)


# ── EU_HORIZON ────────────────────────────────────────────────────────────────

def test_eu_horizon_eligible_by_source(engine):
    grant = make_grant(
        id="eu-123456",
        title="Horizon Europe Research Project",
        source="eu",
        description="Funded under Horizon Europe framework programme.",
    )
    result = engine.check(grant)
    assert result.status == "eligible"
    assert any("EU_HORIZON" in r for r in result.rules_matched)


def test_eu_horizon_eligible_by_keyword(engine):
    grant = make_grant(
        id="HOR-001",
        title="Horizon Europe AMR Grant",
        source="grants_gov",
        description="This grant is part of the Horizon Europe programme.",
    )
    result = engine.check(grant)
    assert result.status == "eligible"
    assert any("EU_HORIZON" in r for r in result.rules_matched)


# ── NIH_FOREIGN_ELIGIBLE ─────────────────────────────────────────────────────

def test_nih_r21_foreign_eligible(engine):
    grant = make_grant(
        id="R21-AI999999",
        title="NIH R21 Exploratory Research",
        source="nih",
        description="Exploratory research on antimicrobial resistance.",
    )
    result = engine.check(grant)
    assert any("NIH_FOREIGN_ELIGIBLE" in r for r in result.rules_matched)


def test_nih_foreign_eligible_r01_in_title(engine):
    grant = make_grant(
        id="PA-24-001",
        title="R01 Research Project Grant",
        source="nih",
        description="Standard NIH research project grant.",
    )
    result = engine.check(grant)
    assert any("NIH_FOREIGN_ELIGIBLE" in r for r in result.rules_matched)


# ── US_ONLY expanded phrases ──────────────────────────────────────────────────

def test_us_only_real_phrases(engine):
    phrases = [
        "applicants must be us-based organizations",
        "only organizations in the united states",
        "restricted to american institutions",
        "must hold us permanent residency",
        "sbir eligible entities",
        "501(c)(3) us nonprofit only",
    ]
    for phrase in phrases:
        grant = make_grant(
            id="US-REAL-001",
            title="Domestic Grant",
            source="grants_gov",
            description=phrase,
        )
        result = engine.check(grant)
        assert result.status == "ineligible", f"Expected ineligible for phrase: {phrase!r}"
        assert any("US_ONLY" in r for r in result.rules_matched), (
            f"Expected US_ONLY rule for phrase: {phrase!r}"
        )


# ── EU_HORIZON vs EU_SOURCE_LIKELY_ELIGIBLE ───────────────────────────────────

def test_eu_horizon_explicit(engine):
    """Grant with Horizon Europe text → eligible with EU_HORIZON_ASSOCIATE."""
    grant = make_grant(
        id="EU-HOR-001",
        title="Horizon Europe Research",
        source="grants_gov",
        description="This project is funded under Horizon Europe.",
    )
    result = engine.check(grant)
    assert result.status == "eligible"
    assert "EU_HORIZON_ASSOCIATE" in result.rules_matched


def test_eu_source_no_horizon(engine):
    """Grant from source=eu with NO horizon keywords → EU_SOURCE_LIKELY_ELIGIBLE with lower confidence."""
    grant = make_grant(
        id="EU-SRC-001",
        title="European Research Grant",
        source="eu",
        description="A research grant open to international institutions.",
    )
    result = engine.check(grant)
    assert result.status == "eligible"
    assert "EU_SOURCE_LIKELY_ELIGIBLE" in result.rules_matched
    assert "EU_HORIZON_ASSOCIATE" not in result.rules_matched
    assert result.confidence < 0.7  # lower confidence for source-only signal


def test_eu_source_with_horizon(engine):
    """Grant from source=eu WITH Horizon Europe keyword → EU_HORIZON_ASSOCIATE (not the weaker one)."""
    grant = make_grant(
        id="EU-SRC-HOR-001",
        title="Horizon Europe International Grant",
        source="eu",
        description="Funded under Horizon Europe, open to associate countries.",
    )
    result = engine.check(grant)
    assert result.status == "eligible"
    assert "EU_HORIZON_ASSOCIATE" in result.rules_matched
    assert "EU_SOURCE_LIKELY_ELIGIBLE" not in result.rules_matched
