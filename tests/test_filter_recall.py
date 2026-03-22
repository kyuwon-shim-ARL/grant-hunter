"""Regression tests for filter recall — baseline for passes_keyword_gate and score_and_rank_grants.

These tests capture the current filter behavior so future changes to keyword
lists or scoring logic can be verified against a known baseline.
"""

import pytest
from grant_hunter.filters import (
    score_and_rank_grants,
    filter_grants,
    passes_keyword_gate,
    AMR_CORE_KEYWORDS,
    AMR_KEYWORDS,
    AI_KEYWORDS,
    DRUG_KEYWORDS,
)
from tests.conftest import make_grant


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tier1_grant():
    """AMR + AI — should always be tier1."""
    return make_grant(
        id="RECALL-TIER1-001",
        title="Machine learning for antimicrobial resistance detection",
        source="nih",
        description=(
            "We apply deep learning and artificial intelligence to predict "
            "antibiotic resistance phenotypes from whole-genome sequencing data."
        ),
    )


@pytest.fixture
def tier2_amr_only_grant():
    """Core AMR keyword, no AI — should always be tier2.

    Minimal description (identical base text to tier2_amr_drug_grant) so the
    scoring comparison is not confounded by different base scores.
    """
    return make_grant(
        id="RECALL-TIER2-001",
        title="Antimicrobial resistance in hospitals",
        source="nih",
        description="Study of antibiotic resistance and MRSA in healthcare settings.",
    )


@pytest.fixture
def tier2_amr_drug_grant():
    """Core AMR + drug_discovery keywords, no AI — tier2 with drug bonus.

    Identical base AMR text to tier2_amr_only_grant, plus drug-discovery terms.
    """
    return make_grant(
        id="RECALL-TIER2-DRUG-001",
        title="Antimicrobial resistance in hospitals",
        source="nih",
        description=(
            "Study of antibiotic resistance and MRSA in healthcare settings. "
            "Novel antibiotic drug discovery and lead optimization."
        ),
    )


@pytest.fixture
def skip_ai_only_grant():
    """AI keywords only, no AMR — classified skip."""
    return make_grant(
        id="RECALL-SKIP-AI-001",
        title="Deep learning for medical image segmentation",
        source="nih",
        description=(
            "Using convolutional neural networks and machine learning to "
            "segment CT images for oncology applications."
        ),
    )


@pytest.fixture
def skip_unrelated_grant():
    """No AMR or AI keywords — classified skip."""
    return make_grant(
        id="RECALL-SKIP-NONE-001",
        title="Vet-LIRN Capacity-Building Project and Equipment Grants (U18)",
        source="grants_gov",
        description=(
            "Funds veterinary laboratory capacity-building and procurement of "
            "diagnostic equipment for food safety programs."
        ),
    )


@pytest.fixture
def skip_broad_amr_single_hit_grant():
    """Single broad AMR hit ('surveillance') with no AI — must be skip, not tier2."""
    return make_grant(
        id="RECALL-SKIP-BROAD-001",
        title="Surveillance of infectious disease in community settings",
        source="nih",
        description=(
            "Epidemiological surveillance of respiratory and gastrointestinal "
            "infections across community health centers."
        ),
    )


# ---------------------------------------------------------------------------
# passes_keyword_gate — tier classification
# ---------------------------------------------------------------------------

class TestPassesKeywordGateTier:
    def test_amr_plus_ai_returns_tier1(self, tier1_grant):
        """Grant with both AMR core keyword and AI keyword is classified tier1."""
        assert passes_keyword_gate(tier1_grant) == "tier1"

    def test_amr_only_returns_tier2(self, tier2_amr_only_grant):
        """Grant with core AMR keyword but no AI keyword is classified tier2."""
        assert passes_keyword_gate(tier2_amr_only_grant) == "tier2"

    def test_amr_drug_no_ai_returns_tier2(self, tier2_amr_drug_grant):
        """Grant with AMR + drug keywords but no AI keyword is classified tier2."""
        assert passes_keyword_gate(tier2_amr_drug_grant) == "tier2"

    def test_ai_only_returns_skip(self, skip_ai_only_grant):
        """Grant with AI keywords but no AMR keyword is classified skip."""
        assert passes_keyword_gate(skip_ai_only_grant) == "skip"

    def test_unrelated_returns_skip(self, skip_unrelated_grant):
        """Grant with no AMR or AI keywords is classified skip."""
        assert passes_keyword_gate(skip_unrelated_grant) == "skip"

    def test_single_broad_amr_no_ai_returns_skip(self, skip_broad_amr_single_hit_grant):
        """Grant with one broad AMR term and no AI is classified skip (not tier2)."""
        assert passes_keyword_gate(skip_broad_amr_single_hit_grant) == "skip"


# ---------------------------------------------------------------------------
# passes_keyword_gate — tier2 requires a core AMR keyword
# ---------------------------------------------------------------------------

class TestTier2RequiresCoreAmrKeyword:
    def test_two_broad_amr_hits_plus_no_ai_not_always_tier2(self):
        """Two broad AMR hits (no core) with no AI stays skip unless both are broad."""
        # 'surveillance' + 'metagenomics' are both broad; together they hit amr_hits >= 2
        # but core_hits == 0, so tier2 check (amr_core_hits >= 1) fails -> skip
        grant = make_grant(
            id="RECALL-BROAD2-NOAI-001",
            title="Surveillance and metagenomics of soil microbiome",
            source="eu",
            description=(
                "Metagenomic sequencing combined with surveillance of soil "
                "microbiomes to assess biodiversity."
            ),
        )
        # With no AI and no core AMR, amr_pass may be True (>=2 broad) but
        # ai_pass is False, so result is NOT tier1. Core check for tier2 also fails.
        result = passes_keyword_gate(grant)
        assert result in ("skip", "tier2"), (
            f"Expected skip or tier2 for broad-only AMR grant, got {result}"
        )
        # The important constraint: must NOT be tier1 without AI
        assert result != "tier1"

    def test_core_amr_keyword_alone_qualifies_for_tier2(self):
        """A single core AMR keyword with no AI produces tier2."""
        grant = make_grant(
            id="RECALL-CORE-NOAI-001",
            title="Beta-lactamase resistance in E. coli",
            source="nih",
            description=(
                "Characterization of ESBL and beta-lactamase enzymes conferring "
                "antibiotic resistance in clinical isolates."
            ),
        )
        assert passes_keyword_gate(grant) == "tier2"


# ---------------------------------------------------------------------------
# passes_keyword_gate — keyword list health (non-empty sanity checks)
# ---------------------------------------------------------------------------

class TestKeywordListHealth:
    def test_amr_core_keywords_is_subset_of_amr_keywords(self):
        """AMR_CORE_KEYWORDS must be a non-empty subset of AMR_KEYWORDS."""
        assert len(AMR_CORE_KEYWORDS) > 0
        core_set = {kw.lower() for kw in AMR_CORE_KEYWORDS}
        amr_set = {kw.lower() for kw in AMR_KEYWORDS}
        assert core_set.issubset(amr_set), (
            "AMR_CORE_KEYWORDS contains terms not present in AMR_KEYWORDS"
        )

    def test_ai_keywords_non_empty(self):
        """AI_KEYWORDS must be loaded and non-empty."""
        assert len(AI_KEYWORDS) > 0

    def test_drug_keywords_non_empty(self):
        """DRUG_KEYWORDS must be loaded and non-empty."""
        assert len(DRUG_KEYWORDS) > 0


# ---------------------------------------------------------------------------
# score_and_rank_grants — inclusion (all grants returned)
# ---------------------------------------------------------------------------

class TestScoreAndRankInclusion:
    def test_tier1_grant_passes_filter(self, tier1_grant):
        """Tier1 (AMR+AI) grant is included in score_and_rank_grants output."""
        result = score_and_rank_grants([tier1_grant])
        assert len(result) == 1
        assert result[0].id == tier1_grant.id

    def test_tier2_grant_passes_filter(self, tier2_amr_only_grant):
        """Tier2 (AMR-only) grant is included in score_and_rank_grants output."""
        result = score_and_rank_grants([tier2_amr_only_grant])
        assert len(result) == 1
        assert result[0].id == tier2_amr_only_grant.id

    def test_skip_grant_included_with_low_score(self, skip_unrelated_grant):
        """Grant classified skip is still included but receives a near-zero score."""
        result = score_and_rank_grants([skip_unrelated_grant])
        assert len(result) == 1
        assert result[0].id == skip_unrelated_grant.id
        assert result[0].relevance_score >= 0.0
        # Score should be very low — well below any AMR-matching grant
        assert result[0].relevance_score < 0.2

    def test_ai_only_grant_included_with_lower_score_than_amr_ai(
        self, skip_ai_only_grant, tier1_grant
    ):
        """AI-only grant is included but scores below an AMR+AI grant."""
        result = score_and_rank_grants([tier1_grant, skip_ai_only_grant])
        tier1_score = next(g.relevance_score for g in result if g.id == tier1_grant.id)
        ai_only_score = next(g.relevance_score for g in result if g.id == skip_ai_only_grant.id)
        assert ai_only_score < tier1_score

    def test_mixed_batch_returns_all_four_grants_sorted_by_score(
        self, tier1_grant, tier2_amr_only_grant, skip_unrelated_grant, skip_ai_only_grant
    ):
        """score_and_rank_grants on a mixed batch returns ALL 4 grants, AMR+AI first."""
        all_grants = [tier1_grant, tier2_amr_only_grant, skip_unrelated_grant, skip_ai_only_grant]
        result = score_and_rank_grants(all_grants)
        assert len(result) == 4
        result_ids = [g.id for g in result]
        assert tier1_grant.id in result_ids
        assert tier2_amr_only_grant.id in result_ids
        assert skip_unrelated_grant.id in result_ids
        assert skip_ai_only_grant.id in result_ids
        # AMR+AI (tier1) must be ranked first
        assert result[0].id == tier1_grant.id
        # Scores must be in descending order
        scores = [g.relevance_score for g in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# score_and_rank_grants — score ranking
# ---------------------------------------------------------------------------

class TestScoreRanking:
    def test_amr_ai_scores_above_amr_only(self, tier1_grant, tier2_amr_only_grant):
        """AMR+AI grant (tier1) scores strictly above AMR-only grant (tier2)."""
        result = score_and_rank_grants([tier1_grant, tier2_amr_only_grant])
        tier1_score = next(g.relevance_score for g in result if g.id == tier1_grant.id)
        tier2_score = next(g.relevance_score for g in result if g.id == tier2_amr_only_grant.id)
        assert tier1_score > tier2_score

    def test_amr_only_scores_above_unrelated(self, tier2_amr_only_grant, skip_unrelated_grant):
        """AMR-only grant scores strictly above an unrelated (skip) grant."""
        result = score_and_rank_grants([tier2_amr_only_grant, skip_unrelated_grant])
        amr_score = next(g.relevance_score for g in result if g.id == tier2_amr_only_grant.id)
        unrelated_score = next(g.relevance_score for g in result if g.id == skip_unrelated_grant.id)
        assert amr_score > unrelated_score

    def test_all_grants_receive_scores(
        self, tier1_grant, tier2_amr_only_grant, skip_unrelated_grant, skip_ai_only_grant
    ):
        """Every grant returned by score_and_rank_grants has relevance_score set."""
        all_grants = [tier1_grant, tier2_amr_only_grant, skip_unrelated_grant, skip_ai_only_grant]
        result = score_and_rank_grants(all_grants)
        for grant in result:
            assert grant.relevance_score is not None, (
                f"Grant {grant.id} has no relevance_score"
            )
            assert isinstance(grant.relevance_score, float)


# ---------------------------------------------------------------------------
# score_and_rank_grants — output ordering
# ---------------------------------------------------------------------------

class TestFilterGrantsOrdering:
    def test_results_sorted_by_relevance_score_descending(
        self, tier1_grant, tier2_amr_only_grant, tier2_amr_drug_grant
    ):
        """score_and_rank_grants returns grants sorted by relevance_score descending."""
        result = score_and_rank_grants([tier2_amr_only_grant, tier1_grant, tier2_amr_drug_grant])
        scores = [g.relevance_score for g in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Real grant title smoke tests — baseline recall from known snapshot data
# ---------------------------------------------------------------------------

class TestRealGrantTitleRecall:
    """Smoke tests using titles from the 2026-03-17 snapshot.

    These verify that grants known to be in filtered output still pass,
    and grants that should not appear are still excluded.
    """

    def test_clinical_research_network_amr_passes(self):
        """'Clinical Research Network on Antimicrobial Resistance' (NIH RFA-AI-27-005) passes."""
        grant = make_grant(
            id="RFA-AI-27-005",
            title="Clinical Research Network on Antimicrobial Resistance",
            source="nih",
            description=(
                "Supports a clinical research network focused on antimicrobial resistance "
                "surveillance and antibiotic stewardship interventions."
            ),
        )
        assert passes_keyword_gate(grant) in ("tier1", "tier2")

    def test_carb_large_research_projects_passes(self):
        """'Large Research Projects for Combating Antibiotic-Resistant Bacteria' passes."""
        grant = make_grant(
            id="334655",
            title="Large Research Projects for Combating Antibiotic-Resistant Bacteria (CARB) (R01)",
            source="grants_gov",
            description=(
                "Supports large-scale research on drug-resistant bacteria, "
                "novel antibiotic development, and resistance gene surveillance."
            ),
        )
        assert passes_keyword_gate(grant) in ("tier1", "tier2")

    def test_narms_antibiotic_resistance_surveillance_passes(self):
        """'NARMS Cooperative Agreement Program to Strengthen Antibiotic Resistance Surveillance' passes."""
        grant = make_grant(
            id="360006",
            title="NARMS Cooperative Agreement Program to Strengthen Antibiotic Resistance Surveillance",
            source="grants_gov",
            description=(
                "Cooperative agreement to strengthen national surveillance of antibiotic "
                "resistance in enteric bacteria across food animals and humans."
            ),
        )
        assert passes_keyword_gate(grant) in ("tier1", "tier2")

    def test_vet_lirn_equipment_grant_skipped(self):
        """'Vet-LIRN Capacity-Building Project and Equipment Grants' is skipped (no AMR/AI)."""
        grant = make_grant(
            id="347990",
            title="Vet-LIRN Capacity-Building Project and Equipment Grants (U18)",
            source="grants_gov",
            description=(
                "Provides equipment and capacity-building support for veterinary "
                "laboratory networks for food safety testing."
            ),
        )
        assert passes_keyword_gate(grant) == "skip"
