"""Tests for researcher profile presets and personalized scoring."""

import pytest
from grant_hunter.profiles import PROFILES, ResearcherProfile, get_profile, list_profiles, create_profile, get_default_profile, _CUSTOM_PROFILES
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


def test_list_profiles_returns_all_presets():
    result = list_profiles()
    preset_names = {"default", "wetlab_amr", "computational", "translational", "clinical"}
    assert preset_names.issubset(set(result.keys()))


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
    assert scorer._weights["amr"] == 0.40
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


# ── Custom profile creation (T1-3) ───────────────────────────────────────────

@pytest.fixture(autouse=False)
def clean_custom_profiles():
    """Clear custom profiles after each test that uses this fixture."""
    _CUSTOM_PROFILES.clear()
    yield
    _CUSTOM_PROFILES.clear()


def test_get_default_profile():
    profile = get_default_profile()
    assert profile.name == "Default (Balanced)"
    assert profile.weights["amr"] == 0.40


def test_create_profile_and_retrieve(clean_custom_profiles):
    weights = {"amr": 0.50, "ai": 0.20, "drug": 0.20, "amount": 0.10}
    profile = create_profile("my_custom", weights, "Test custom profile")
    assert profile.name == "my_custom"
    assert profile.weights == weights
    # Retrievable via get_profile
    retrieved = get_profile("my_custom")
    assert retrieved is profile


def test_create_profile_appears_in_list(clean_custom_profiles):
    create_profile("listed_profile", {"amr": 0.25, "ai": 0.25, "drug": 0.25, "amount": 0.25})
    result = list_profiles()
    assert "listed_profile" in result


def test_create_profile_rejects_preset_name(clean_custom_profiles):
    with pytest.raises(ValueError, match="Cannot override preset"):
        create_profile("default", {"amr": 0.40, "ai": 0.30, "drug": 0.20, "amount": 0.10})


def test_create_profile_rejects_invalid_weights(clean_custom_profiles):
    with pytest.raises(ValueError, match="Weights must sum to 1.0"):
        create_profile("bad_weights", {"amr": 0.50, "ai": 0.50, "drug": 0.50, "amount": 0.50})


# ── Keyword reload (T1-2) ────────────────────────────────────────────────────

def test_get_scorer_factory():
    from grant_hunter.scoring import get_scorer
    scorer = get_scorer()
    assert isinstance(scorer, RelevanceScorer)
    # Same instance returned for default profile
    scorer2 = get_scorer()
    assert scorer is scorer2


def test_get_scorer_reload():
    from grant_hunter.scoring import get_scorer, keyword_counts
    counts_before = keyword_counts()
    scorer = get_scorer(reload=True)
    counts_after = keyword_counts()
    assert isinstance(scorer, RelevanceScorer)
    assert counts_before == counts_after  # same file, same counts


def test_keyword_counts_returns_categories():
    from grant_hunter.scoring import keyword_counts
    counts = keyword_counts()
    assert "amr" in counts
    assert "ai" in counts
    assert "drug" in counts
    assert all(isinstance(v, int) for v in counts.values())


# ── Amount-only blocking (T0-3) ──────────────────────────────────────────────

def test_amount_only_grant_gets_zero_score():
    """Grant with funding but no keyword matches should score 0."""
    grant = make_grant(
        id="AMOUNT-ONLY",
        title="Infrastructure Development Project",
        source="grants_gov",
        description="General purpose building renovation and maintenance project.",
        amount_max=5_000_000,
    )
    scorer = RelevanceScorer()
    assert scorer.score(grant) == 0.0


# ── Breakdown clamp (T0-4) ───────────────────────────────────────────────────

def test_breakdown_components_clamped_to_one():
    """All score_breakdown components should be <= 1.0."""
    grant = _make_amr_grant()
    scorer = RelevanceScorer()
    bd = scorer.score_breakdown(grant)
    for key, value in bd.items():
        if key != "total":
            assert value <= 1.0, f"breakdown['{key}'] = {value} exceeds 1.0"
