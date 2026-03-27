"""Tests for AMR+AI dual keyword post-filter."""
from __future__ import annotations

import pytest
from tests.conftest import make_grant
from grant_hunter.collectors.amr_filter import amr_ai_post_filter, is_amr_ai_relevant


def _g(title: str = "", description: str = ""):
    return make_grant(title=title, description=description)


class TestIsAmrAiRelevant:
    def test_amr_and_ai_both_present(self):
        g = _g(title="Machine learning for antimicrobial resistance prediction")
        assert is_amr_ai_relevant(g) is True

    def test_amr_only_fails(self):
        g = _g(title="Novel antibiotic resistance mechanisms study")
        assert is_amr_ai_relevant(g) is False

    def test_ai_only_fails(self):
        g = _g(title="Deep learning for protein structure prediction")
        assert is_amr_ai_relevant(g) is False

    def test_neither_fails(self):
        g = _g(title="Clinical trial for hypertension treatment")
        assert is_amr_ai_relevant(g) is False

    def test_amr_abbreviation_whole_word(self):
        # \bAMR\b should match AMR as standalone
        g = _g(title="AMR detection using machine learning")
        assert is_amr_ai_relevant(g) is True

    def test_niaid_false_positive_avoided(self):
        # "AI" in "NIAID" should NOT match AI keyword
        g = _g(title="NIAID funding for antibiotic resistance ESKAPE", description="NIAID program")
        # AMR matched (antibiotic resistance), AI not matched → False
        assert is_amr_ai_relevant(g) is False

    def test_ai_bare_excluded(self):
        # bare "AI" should not trigger AI keyword match
        g = _g(title="AMR AI funding opportunity carbapenem resistant")
        # "AI" alone is not in AI_KEYWORDS — should fail AI check
        assert is_amr_ai_relevant(g) is False

    def test_description_searched(self):
        g = _g(title="Research Grant", description="Antimicrobial resistance prediction using deep learning models")
        assert is_amr_ai_relevant(g) is True

    def test_mrsa_whole_word(self):
        g = _g(title="MRSA infection treatment using neural network classifiers")
        assert is_amr_ai_relevant(g) is True

    def test_large_language_model(self):
        g = _g(title="Large language model applications in drug-resistant pathogen genomics")
        assert is_amr_ai_relevant(g) is True


class TestAmrAiPostFilter:
    def test_filters_irrelevant(self):
        grants = [
            _g(title="Hypertension treatment trial"),
            _g(title="Machine learning antimicrobial resistance"),
            _g(title="Deep learning cardiology"),
        ]
        result = amr_ai_post_filter(grants)
        assert len(result) == 1
        assert result[0].title == "Machine learning antimicrobial resistance"

    def test_empty_input(self):
        assert amr_ai_post_filter([]) == []

    def test_all_pass(self):
        grants = [
            _g(title="Antibiotic resistance deep learning prediction"),
            _g(title="MRSA neural network detection"),
        ]
        assert len(amr_ai_post_filter(grants)) == 2

    def test_nih_ratio_mock(self):
        """Simulate NIH collection: ≥10% should pass AMR+AI filter."""
        # Create 20 grants, 3 AMR+AI relevant (15%)
        irrelevant = [_g(title=f"Cancer immunotherapy study {i}") for i in range(17)]
        relevant = [
            _g(title="Machine learning for antimicrobial resistance"),
            _g(title="Deep learning ESKAPE pathogen detection"),
            _g(title="Artificial intelligence carbapenem resistance"),
        ]
        all_grants = irrelevant + relevant
        filtered = amr_ai_post_filter(all_grants)
        ratio = len(filtered) / len(all_grants)
        assert ratio >= 0.10, f"AMR+AI ratio {ratio:.1%} < 10%"
