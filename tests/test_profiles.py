"""Tests for researcher profile presets and personalized scoring."""

import pytest
from grant_hunter.profiles import PROFILES, ResearcherProfile, get_profile, list_profiles
from grant_hunter.scoring import RelevanceScorer
from tests.conftest import make_grant


# ── Profile validation ─────────────────────────────────────────────────────────

def test_all_preset_profiles_have_valid_weights():
    for name, profile in PROFILES.items():
        total = sum(profile.weights.values())
        assert abs(total - 1.0) <= 0.01, (
            f"Profile '{name}' weights sum to {total}, expected 1.0"
        )


def test_all_preset_profiles_have_required_keys():
    required = {"amr", "ai", "drug", "amount"}
    for name, profile in PROFILES.items():
        assert set(profile.weights.keys()) == required, (
            f"Profile '{name}' missing keys"
        )


def test_list_profiles_returns_all_five():
    result = list_profiles()
    assert len(result) == 5
    assert set(result.keys()) == {"default", "wetlab_amr", "computational", "translational", "clinical"}


def test_list_profiles_returns_descriptions():
    result = list_profiles()
    for name, desc in result.items():
        assert isinstance(desc, str) and len(desc) > 0, (
            f"Profile '{name}' has empty description"
        )


def test_get_profile_returns_correct_profile():
    profile = get_profile("computational")
    assert profile.name == "Computational Biologist"
    assert profile.weights["ai"] == 0.60


def test_get_profile_raises_key_error_for_unknown():
    with pytest.raises(KeyError, match="unknown_profile"):
        get_profile("unknown_profile")


def test_researcher_profile_validates_weight_keys():
    with pytest.raises(ValueError, match="Weights must have keys"):
        ResearcherProfile(
            name="Bad",
            description="Missing keys",
            weights={"amr": 0.5, "ai": 0.5},  # missing drug, amount
        )


def test_researcher_profile_validates_weight_sum():
    with pytest.raises(ValueError, match="Weights must sum to 1.0"):
        ResearcherProfile(
            name="Bad",
            description="Weights don't sum to 1",
            weights={"amr": 0.5, "ai": 0.5, "drug": 0.5, "amount": 0.5},
        )


# ── Personalized scoring ───────────────────────────────────────────────────────

def _make_amr_grant(gid="AMR-001"):
    return make_grant(
        id=gid,
        title="Antimicrobial resistance pathogen susceptibility testing",
        source="nih",
        description=(
            "Study of antibiotic resistance mechanisms in bacteria. "
            "Focus on antimicrobial susceptibility and resistance gene detection."
        ),
    )


def _make_ai_grant(gid="AI-001"):
    return make_grant(
        id=gid,
        title="Deep learning neural network for biomedical informatics",
        source="nih",
        description=(
            "Machine learning and artificial intelligence methods for bioinformatics. "
            "In silico modeling using neural networks and large language models."
        ),
    )


def _make_drug_grant(gid="DRUG-001"):
    return make_grant(
        id=gid,
        title="Drug discovery hit-to-lead optimization medicinal chemistry",
        source="nih",
        description=(
            "Preclinical drug development pipeline, pharmacokinetics, and lead compound "
            "optimization for novel antibiotic candidates."
        ),
    )


def test_default_scorer_no_args():
    """RelevanceScorer() with no args uses default weights (backward compat)."""
    scorer = RelevanceScorer()
    assert scorer._weights["amr"] == 0.45 or scorer._weights["amr"] == 0.40
    # Key point: weights exist and sum to 1.0
    total = sum(scorer._weights.values())
    assert abs(total - 1.0) <= 0.01


def test_profile_scorer_uses_profile_weights():
    profile = get_profile("computational")
    scorer = RelevanceScorer(profile=profile)
    assert scorer._weights == dict(profile.weights)


def test_wetlab_profile_ranks_amr_grant_higher_than_ai_grant():
    profile = get_profile("wetlab_amr")
    scorer = RelevanceScorer(profile=profile)
    amr_score = scorer.score(_make_amr_grant())
    ai_score = scorer.score(_make_ai_grant())
    assert amr_score > ai_score, (
        f"wetlab_amr profile should rank AMR grant higher: {amr_score} vs {ai_score}"
    )


def test_computational_profile_ranks_ai_grant_higher_than_amr_grant():
    profile = get_profile("computational")
    scorer = RelevanceScorer(profile=profile)
    amr_score = scorer.score(_make_amr_grant())
    ai_score = scorer.score(_make_ai_grant())
    assert ai_score > amr_score, (
        f"computational profile should rank AI grant higher: {ai_score} vs {amr_score}"
    )


def test_translational_profile_ranks_drug_grant_highly():
    translational = RelevanceScorer(profile=get_profile("translational"))
    wetlab = RelevanceScorer(profile=get_profile("wetlab_amr"))
    drug_grant = _make_drug_grant()
    assert translational.score(drug_grant) > wetlab.score(drug_grant), (
        "translational profile should score drug grant higher than wetlab_amr profile"
    )


def test_different_profiles_produce_different_top20():
    """Jaccard distance between profiles' Top-20 rankings is > 0."""
    grants = [
        _make_amr_grant(f"AMR-{i}") for i in range(10)
    ] + [
        _make_ai_grant(f"AI-{i}") for i in range(10)
    ] + [
        _make_drug_grant(f"DRUG-{i}") for i in range(10)
    ]

    wetlab_scorer = RelevanceScorer(profile=get_profile("wetlab_amr"))
    comp_scorer = RelevanceScorer(profile=get_profile("computational"))

    def top20_ids(scorer):
        scored = sorted(grants, key=lambda g: scorer.score(g), reverse=True)
        return {g.id for g in scored[:20]}

    wetlab_top20 = top20_ids(wetlab_scorer)
    comp_top20 = top20_ids(comp_scorer)

    intersection = len(wetlab_top20 & comp_top20)
    union = len(wetlab_top20 | comp_top20)
    jaccard = intersection / union if union > 0 else 1.0

    assert jaccard < 1.0, (
        "wetlab_amr and computational profiles should produce different Top-20 rankings"
    )


def test_score_breakdown_uses_profile_weights():
    """score_breakdown total should reflect profile weights."""
    profile = get_profile("computational")
    scorer = RelevanceScorer(profile=profile)
    grant = _make_ai_grant()
    bd = scorer.score_breakdown(grant)
    # Manually compute expected total
    expected = (
        profile.weights["amr"] * bd["amr"]
        + profile.weights["ai"] * bd["ai"]
        + profile.weights["drug"] * bd["drug"]
        + profile.weights["amount"] * bd["amount_bonus"]
    )
    assert abs(bd["total"] - round(min(expected, 1.0), 4)) <= 0.001
