"""Tests for grant_hunter.keyword_audit module."""

from __future__ import annotations

from typing import Dict, List
from unittest.mock import patch

import pytest

from tests.conftest import make_grant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grants_with_text(specs: list) -> list:
    """specs is a list of (id, title, description, llm_score) tuples."""
    grants = []
    for i, (gid, title, desc, llm_score) in enumerate(specs):
        g = make_grant(
            id=gid,
            title=title,
            description=desc,
            relevance_score=0.1 * (i + 1),
        )
        object.__setattr__(g, "llm_score", llm_score)
        grants.append(g)
    return grants


_AMR_AI_DESC = (
    "Antimicrobial resistance and machine learning approaches to drug discovery. "
    "Deep learning models for antibiotic resistance prediction using bioinformatics."
)

_UNRELATED_DESC = (
    "Study of ancient pottery fragments and geological soil composition analysis "
    "in Mediterranean archaeological sites."
)


# ---------------------------------------------------------------------------
# test_keyword_coverage_structure
# ---------------------------------------------------------------------------


def test_keyword_coverage_structure():
    """keyword_coverage returns dict with all required top-level keys."""
    from grant_hunter.keyword_audit import keyword_coverage

    grants = [
        make_grant(id="KC-001", title="AMR drug discovery", description=_AMR_AI_DESC),
    ]

    result = keyword_coverage(grants)

    # Required top-level keys
    assert "amr" in result
    assert "ai" in result
    assert "drug_discovery" in result
    assert "overall" in result
    assert "top_keywords" in result
    assert "zero_hit_keywords" in result

    # Per-category keys
    for cat in ("amr", "ai", "drug_discovery"):
        assert "total" in result[cat]
        assert "matched" in result[cat]
        assert "unmatched" in result[cat]
        assert "match_rate" in result[cat]

    # Overall keys
    assert "total" in result["overall"]
    assert "matched" in result["overall"]
    assert "match_rate" in result["overall"]

    # top_keywords entries have required fields
    for entry in result["top_keywords"]:
        assert "keyword" in entry
        assert "category" in entry
        assert "hit_count" in entry


# ---------------------------------------------------------------------------
# test_zero_hit_keywords
# ---------------------------------------------------------------------------


def test_zero_hit_keywords():
    """Keywords not present in any grant text appear in zero_hit_keywords."""
    from grant_hunter.keyword_audit import keyword_coverage

    # Use a grant with unrelated text so keyword hits will be low
    grants = [make_grant(id="ZH-001", title="pottery", description=_UNRELATED_DESC)]

    result = keyword_coverage(grants)

    zero_hit = result["zero_hit_keywords"]
    assert isinstance(zero_hit, list)
    # With unrelated content, there should be at least some zero-hit keywords
    assert len(zero_hit) > 0
    for entry in zero_hit:
        assert entry["hit_count"] == 0


# ---------------------------------------------------------------------------
# test_false_negative_detection
# ---------------------------------------------------------------------------


def test_false_negative_detection():
    """Grant with high llm_score but low keyword_score is detected as false negative."""
    from grant_hunter.keyword_audit import detect_false_negatives

    # Grant with high LLM score but no AMR/AI keywords in text
    specs = [
        ("FN-001", "Rare earth mineral extraction", _UNRELATED_DESC, 0.85),
        ("FN-002", "AMR research with AI", _AMR_AI_DESC, 0.90),
    ]
    grants = _make_grants_with_text(specs)

    # threshold_kw=0.20 means keyword score must be below 0.20
    # threshold_llm=0.60 means llm_score must be >= 0.60
    results = detect_false_negatives(grants, threshold_kw=0.20, threshold_llm=0.60)

    # The unrelated grant (FN-001) with high llm_score should be detected
    ids_detected = [r["grant_id"] for r in results]
    assert "FN-001" in ids_detected

    # Each result has required fields
    for r in results:
        assert "grant_id" in r
        assert "keyword_score" in r
        assert "llm_score" in r
        assert "gap" in r
        assert "missing_terms" in r
        assert r["gap"] >= 0


# ---------------------------------------------------------------------------
# test_suggest_keywords_excludes_existing
# ---------------------------------------------------------------------------


def test_suggest_keywords_excludes_existing():
    """suggest_keywords does not return terms already in keywords.json."""
    from grant_hunter.keyword_audit import suggest_keywords, _get_category_keywords

    # Collect all existing keywords (lowercased)
    cat_kw = _get_category_keywords()
    existing = set()
    for kw_list in cat_kw.values():
        existing.update(k.lower() for k in kw_list)

    grants = [
        make_grant(
            id="SK-001",
            title="Phage therapy against drug resistant bacteria",
            description=(
                "This study investigates phage therapy for multidrug resistant infections. "
                "We apply transformer neural networks for genomic sequence analysis. "
                "Novel scaffold design for peptidomimetic compounds targeting biofilm."
            ),
            relevance_score=0.5,
        )
    ]
    # Give grant a high llm_score so it's targeted
    object.__setattr__(grants[0], "llm_score", 0.80)

    suggestions = suggest_keywords(grants)

    for s in suggestions:
        term = s["term"].lower()
        assert term not in existing, f"Existing keyword '{term}' should not be suggested"


# ---------------------------------------------------------------------------
# test_audit_report_completeness
# ---------------------------------------------------------------------------


def test_audit_report_completeness():
    """generate_audit_report has coverage, false_negatives, suggestions, and summary."""
    from grant_hunter.keyword_audit import generate_audit_report

    grants = [
        make_grant(
            id="AR-001",
            title="Machine learning for AMR",
            description=_AMR_AI_DESC,
            relevance_score=0.5,
        ),
        make_grant(
            id="AR-002",
            title="Pottery fragments study",
            description=_UNRELATED_DESC,
            relevance_score=0.1,
        ),
    ]
    # Give one grant a high llm_score
    object.__setattr__(grants[0], "llm_score", 0.75)

    report = generate_audit_report(grants)

    assert "coverage" in report
    assert "false_negatives" in report
    assert "suggestions" in report
    assert "summary" in report

    summary = report["summary"]
    assert "total_grants" in summary
    assert "grants_with_llm_score" in summary
    assert "false_negative_count" in summary
    assert "suggestion_count" in summary
    assert "overall_match_rate" in summary

    assert summary["total_grants"] == 2
    assert summary["grants_with_llm_score"] == 1
