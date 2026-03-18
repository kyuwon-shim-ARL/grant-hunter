"""Tests for scoring validation framework."""
import pytest
from grant_hunter.validation import (
    load_validation_set,
    grants_from_validation_set,
    evaluate_scoring,
)
from grant_hunter.scoring import RelevanceScorer


class TestValidationSet:
    def test_load_validation_set_has_30_entries(self):
        entries = load_validation_set()
        assert len(entries) == 30

    def test_all_entries_have_required_fields(self):
        entries = load_validation_set()
        for e in entries:
            assert "id" in e
            assert "title" in e
            assert "description" in e
            assert "relevance_label" in e
            assert e["relevance_label"] in ("high", "medium", "low", "irrelevant")

    def test_label_distribution(self):
        entries = load_validation_set()
        labels = [e["relevance_label"] for e in entries]
        assert labels.count("high") == 8
        assert labels.count("medium") == 8
        assert labels.count("low") == 7
        assert labels.count("irrelevant") == 7

    def test_grants_from_validation_set(self):
        entries = load_validation_set()
        grants = grants_from_validation_set(entries)
        assert len(grants) == 30
        assert all(g.title for g in grants)
        assert all(g.description for g in grants)


class TestScoringEvaluation:
    def test_evaluate_returns_expected_keys(self):
        result = evaluate_scoring()
        assert "precision_at_10" in result
        assert "precision_at_20" in result
        assert "label_avg_scores" in result
        assert "rank_order_correct" in result

    def test_precision_at_10_above_threshold(self):
        """Precision@10 should be >= 0.7 (7 of top 10 are high/medium)."""
        result = evaluate_scoring()
        assert result["precision_at_10"] >= 0.7, (
            f"precision@10 = {result['precision_at_10']}"
        )

    def test_rank_order_correct(self):
        """Average scores should follow: high >= medium >= low >= irrelevant."""
        result = evaluate_scoring()
        assert result["rank_order_correct"], f"Scores: {result['label_avg_scores']}"

    def test_high_label_avg_above_medium(self):
        result = evaluate_scoring()
        assert result["label_avg_scores"]["high"] > result["label_avg_scores"]["medium"]

    def test_few_misclassifications(self):
        """At most 2 high/medium grants should score at or below irrelevant average."""
        result = evaluate_scoring()
        assert len(result["misclassifications"]) <= 2, (
            f"{len(result['misclassifications'])} misclassifications: "
            f"{[m['title'][:40] for m in result['misclassifications']]}"
        )
