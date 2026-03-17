"""Tests for GrantClassifier - research stage, funding type, urgency, and priority tier."""

import pytest
from datetime import date, timedelta
from grant_hunter.classifier import GrantClassifier, GrantClassification
from tests.conftest import make_grant


@pytest.fixture
def classifier():
    return GrantClassifier()


# ── RESEARCH STAGE ────────────────────────────────────────────────────────────

def test_research_stage_basic_for_molecular_mechanism_keyword(classifier):
    grant = make_grant(
        id="STAGE-001",
        title="Molecular mechanism of antibiotic resistance",
        source="nih",
        description="Investigating the molecular mechanism underlying beta-lactam resistance.",
    )
    result = classifier.classify(grant)
    assert result.research_stage == "basic"


def test_research_stage_translational_for_preclinical_drug_development(classifier):
    grant = make_grant(
        id="STAGE-002",
        title="Preclinical drug development for AMR pathogens",
        source="nih",
        description="Preclinical drug development studies on novel antibiotics.",
    )
    result = classifier.classify(grant)
    assert result.research_stage == "translational"


def test_research_stage_clinical_for_phase_ii_trial(classifier):
    grant = make_grant(
        id="STAGE-003",
        title="Phase II clinical trial of novel antibiotic",
        source="nih",
        description="A Phase II clinical trial evaluating efficacy of XYZ compound.",
    )
    result = classifier.classify(grant)
    assert result.research_stage == "clinical"


def test_research_stage_infrastructure_for_surveillance_capacity_building(classifier):
    grant = make_grant(
        id="STAGE-004",
        title="AMR surveillance capacity building in Southeast Asia",
        source="eu",
        description="Surveillance capacity building programme to strengthen AMR monitoring.",
    )
    result = classifier.classify(grant)
    assert result.research_stage == "infrastructure"


def test_research_stage_unclassified_when_no_matching_keywords(classifier):
    grant = make_grant(
        id="STAGE-005",
        title="General health economics study",
        source="eu",
        description="A health economics analysis of spending in European countries.",
    )
    result = classifier.classify(grant)
    assert result.research_stage == "unclassified"


# ── FUNDING TYPE ──────────────────────────────────────────────────────────────

def test_funding_type_project_grant_for_nih_source(classifier):
    grant = make_grant(
        id="FUND-001",
        title="Research on antimicrobial peptides",
        source="nih",
        description="Studying novel antimicrobial peptides against drug-resistant pathogens.",
    )
    result = classifier.classify(grant)
    assert result.funding_type == "project_grant"


def test_funding_type_fellowship_for_fellowship_in_title(classifier):
    grant = make_grant(
        id="FUND-002",
        title="Fellowship in Antimicrobial Resistance Research",
        source="eu",
        description="A fellowship programme for early-career researchers in AMR.",
    )
    result = classifier.classify(grant)
    assert result.funding_type == "fellowship"


def test_funding_type_challenge_for_carbx_source(classifier):
    grant = make_grant(
        id="FUND-003",
        title="CARB-X Product Development Award",
        source="carb_x",
        description="Funding for early-stage antibacterial product development.",
    )
    result = classifier.classify(grant)
    assert result.funding_type == "challenge"


def test_funding_type_consortium_for_consortium_in_title(classifier):
    grant = make_grant(
        id="FUND-004",
        title="European AMR Research Consortium Grant",
        source="eu",
        description="Multi-partner consortium grant for collaborative AMR research.",
    )
    result = classifier.classify(grant)
    assert result.funding_type == "consortium"


# ── URGENCY ───────────────────────────────────────────────────────────────────

def test_urgency_urgent_when_deadline_in_15_days(classifier):
    today = date(2026, 3, 17)
    grant = make_grant(
        id="URG-001",
        title="Urgent deadline grant",
        source="nih",
        deadline=today + timedelta(days=15),
    )
    result = classifier.classify(grant, today=today)
    assert result.urgency == "urgent"


def test_urgency_upcoming_when_deadline_in_60_days(classifier):
    today = date(2026, 3, 17)
    grant = make_grant(
        id="URG-002",
        title="Upcoming deadline grant",
        source="nih",
        deadline=today + timedelta(days=60),
    )
    result = classifier.classify(grant, today=today)
    assert result.urgency == "upcoming"


def test_urgency_open_when_deadline_in_120_days(classifier):
    today = date(2026, 3, 17)
    grant = make_grant(
        id="URG-003",
        title="Open deadline grant",
        source="nih",
        deadline=today + timedelta(days=120),
    )
    result = classifier.classify(grant, today=today)
    assert result.urgency == "open"


def test_urgency_rolling_when_no_deadline(classifier):
    grant = make_grant(
        id="URG-004",
        title="No deadline grant",
        source="nih",
        deadline=None,
    )
    result = classifier.classify(grant)
    assert result.urgency == "rolling"


def test_expired_urgency(classifier):
    today = date(2026, 3, 17)
    grant = make_grant(
        id="URG-005",
        title="Expired deadline grant",
        source="nih",
        deadline=today - timedelta(days=10),
    )
    result = classifier.classify(grant, today=today)
    assert result.urgency == "expired"


def test_expired_not_urgent(classifier):
    today = date(2026, 3, 17)
    grant = make_grant(
        id="URG-006",
        title="Past deadline grant",
        source="nih",
        deadline=today - timedelta(days=1),
    )
    result = classifier.classify(grant, today=today)
    assert result.urgency != "urgent"


# ── PRIORITY TIER ─────────────────────────────────────────────────────────────
# The classifier reads eligibility_status via getattr(grant, "eligibility_status", "uncertain").
# Grant is a dataclass without that field, so we attach it as an instance attribute.

def test_priority_tier1_for_high_score_eligible(classifier):
    grant = make_grant(
        id="TIER-001",
        title="High priority AMR grant",
        source="nih",
        relevance_score=0.45,
    )
    grant.eligibility_status = "eligible"
    result = classifier.classify(grant)
    assert result.tier == "tier1"


def test_priority_tier2_for_medium_score_eligible_grant(classifier):
    grant = make_grant(
        id="TIER-002",
        title="Medium priority grant",
        source="eu",
        relevance_score=0.30,
    )
    grant.eligibility_status = "eligible"
    result = classifier.classify(grant)
    assert result.tier == "tier2"


def test_priority_tier2_for_uncertain_eligibility(classifier):
    grant = make_grant(
        id="TIER-002b",
        title="Uncertain eligibility grant",
        source="eu",
        relevance_score=0.30,
    )
    grant.eligibility_status = "uncertain"
    result = classifier.classify(grant)
    assert result.tier == "tier2"


def test_funding_type_institutional_for_capacity_keyword(classifier):
    grant = make_grant(
        id="FUND-005",
        title="Laboratory Infrastructure Upgrade",
        source="eu",
        description="Core facility and equipment capacity expansion.",
    )
    result = classifier.classify(grant)
    assert result.funding_type == "institutional"


def test_priority_tier3_for_moderate_score_grant(classifier):
    grant = make_grant(
        id="TIER-003",
        title="Moderate priority grant",
        source="eu",
        relevance_score=0.20,
    )
    grant.eligibility_status = "ineligible"
    result = classifier.classify(grant)
    assert result.tier == "tier3"


def test_priority_tier4_for_very_low_score_grant(classifier):
    grant = make_grant(
        id="TIER-004",
        title="Very low priority grant",
        source="eu",
        relevance_score=0.15,
    )
    grant.eligibility_status = "uncertain"
    result = classifier.classify(grant)
    assert result.tier == "tier4"


# ── BATCH CLASSIFICATION ──────────────────────────────────────────────────────

def test_classify_batch_returns_list_of_same_length(classifier):
    grants = [
        make_grant(id=f"BATCH-{i:03d}", title=f"Grant {i}", source="nih")
        for i in range(5)
    ]
    results = classifier.classify_batch(grants)
    assert isinstance(results, list)
    assert len(results) == len(grants)


# ── DISTRIBUTION CHECK ────────────────────────────────────────────────────────

def test_unclassified_research_stage_below_5_percent_across_varied_grants(classifier):
    grants = [
        make_grant(id="DIST-001", title="Molecular mechanism of resistance", source="nih",
                   description="Studying molecular mechanisms of beta-lactam resistance."),
        make_grant(id="DIST-002", title="Preclinical drug development study", source="nih",
                   description="Preclinical development of novel antibiotics."),
        make_grant(id="DIST-003", title="Phase I clinical trial results", source="nih",
                   description="Phase I clinical trial for compound ABC."),
        make_grant(id="DIST-004", title="AMR surveillance capacity building", source="eu",
                   description="Surveillance capacity building across African nations."),
        make_grant(id="DIST-005", title="Genomic basis of antibiotic resistance", source="nih",
                   description="Molecular mechanism and genomic basis of resistance."),
        make_grant(id="DIST-006", title="In vitro preclinical screening", source="carbx",
                   description="Preclinical drug development and in vitro efficacy screening."),
        make_grant(id="DIST-007", title="Phase II efficacy trial", source="nih",
                   description="Phase II clinical trial evaluating XYZ antibiotic."),
        make_grant(id="DIST-008", title="Laboratory capacity building programme", source="eu",
                   description="Surveillance and capacity building for AMR laboratories."),
        make_grant(id="DIST-009", title="Protein structure of resistance enzyme", source="nih",
                   description="Structural biology and molecular mechanism of carbapenemase."),
        make_grant(id="DIST-010", title="Translational antibiotic research", source="nih",
                   description="Preclinical drug development pipeline for novel scaffolds."),
        make_grant(id="DIST-011", title="Phase III confirmatory trial", source="grants_gov",
                   description="Phase III clinical trial for registration of antibiotic."),
        make_grant(id="DIST-012", title="National AMR surveillance network", source="eu",
                   description="Capacity building and surveillance network establishment."),
        make_grant(id="DIST-013", title="Biochemical mechanism of efflux pumps", source="nih",
                   description="Molecular mechanism of efflux-mediated antibiotic resistance."),
        make_grant(id="DIST-014", title="Animal model preclinical validation", source="carbx",
                   description="Preclinical drug development using murine infection models."),
        make_grant(id="DIST-015", title="Paediatric dosing clinical study", source="nih",
                   description="Phase I clinical trial of antibiotic dosing in children."),
        make_grant(id="DIST-016", title="AMR data surveillance platform", source="eu",
                   description="Digital surveillance capacity building for AMR data collection."),
        make_grant(id="DIST-017", title="CRISPR-based resistance mechanism", source="nih",
                   description="Investigating molecular mechanism via CRISPR interference."),
        make_grant(id="DIST-018", title="Combination therapy preclinical work", source="carbx",
                   description="Preclinical drug development for combination antibiotic regimens."),
        make_grant(id="DIST-019", title="Phase II randomised controlled trial", source="nih",
                   description="Phase II clinical trial: randomised controlled study design."),
        make_grant(id="DIST-020", title="One Health surveillance infrastructure", source="eu",
                   description="Surveillance capacity building using One Health approach."),
    ]

    results = classifier.classify_batch(grants)
    assert len(results) == 20

    unclassified_count = sum(
        1 for r in results if r.research_stage == "unclassified"
    )
    unclassified_pct = unclassified_count / len(results)
    assert unclassified_pct < 0.05, (
        f"Expected <5% unclassified, got {unclassified_pct:.0%} "
        f"({unclassified_count}/20 unclassified)"
    )
