"""Tests for Grant model v4.0 — llm_score and llm_details fields."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from grant_hunter.models import Grant
from tests.conftest import make_grant


# ---------------------------------------------------------------------------
# test_llm_fields_default_none
# ---------------------------------------------------------------------------


def test_llm_fields_default_none():
    """New Grant() has llm_score=None and llm_details=None by default."""
    g = make_grant(id="V4-001")
    assert g.llm_score is None
    assert g.llm_details is None


# ---------------------------------------------------------------------------
# test_llm_fields_roundtrip
# ---------------------------------------------------------------------------


def test_llm_fields_roundtrip():
    """to_dict/from_dict correctly preserves llm_score and llm_details."""
    g = Grant(
        id="V4-002",
        title="LLM Fields Test",
        agency="NIH",
        source="nih",
        url="https://example.com",
        description="Test description",
        llm_score=0.75,
        llm_details={
            "grant_id": "V4-002",
            "research_alignment": 4,
            "institutional_fit": 3,
            "strategic_value": 4,
            "feasibility": 3,
            "rationale": "Strong AMR-AI alignment",
            "llm_score": 3.65,
            "stale": False,
            "scored_at": "2026-03-25T00:00:00+00:00",
        },
    )

    d = g.to_dict()

    # to_dict should include llm fields
    assert "llm_score" in d
    assert "llm_details" in d
    assert d["llm_score"] == 0.75
    assert d["llm_details"]["research_alignment"] == 4

    restored = Grant.from_dict(d)
    assert restored.llm_score == 0.75
    assert restored.llm_details is not None
    assert restored.llm_details["research_alignment"] == 4
    assert restored.llm_details["rationale"] == "Strong AMR-AI alignment"


# ---------------------------------------------------------------------------
# test_backward_compat
# ---------------------------------------------------------------------------


def test_backward_compat():
    """from_dict with old-format dict (no llm fields) creates Grant with defaults."""
    old_format = {
        "id": "V4-003",
        "title": "Old Format Grant",
        "agency": "NSF",
        "source": "grants_gov",
        "url": "https://example.com/old",
        "description": "Legacy grant without LLM fields",
        "deadline": None,
        "amount_min": None,
        "amount_max": None,
        "duration_months": None,
        "keywords": ["AMR"],
        "raw_data": {},
        "fetched_at": "2025-01-01T00:00:00",
        "relevance_score": 0.3,
        # NOTE: no llm_score, no llm_details
    }

    g = Grant.from_dict(old_format)

    assert g.id == "V4-003"
    assert g.relevance_score == 0.3
    assert g.llm_score is None
    assert g.llm_details is None
