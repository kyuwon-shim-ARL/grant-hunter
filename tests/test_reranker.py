"""Tests for grant_hunter.reranker module."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_grant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grants(n: int):
    return [
        make_grant(
            id=f"GR-{i:03d}",
            title=f"Grant {i}",
            description=f"Description {i}",
            relevance_score=round(0.1 * i, 2),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# test_llm_reranker_disabled
# ---------------------------------------------------------------------------


def test_llm_reranker_disabled():
    """When LLM_RERANK is False, rerank() sorts by relevance_score, no API calls."""
    from grant_hunter import reranker as rk

    grants = _make_grants(5)
    # Shuffle scores by re-assigning relevance_score to reverse order
    for i, g in enumerate(grants):
        object.__setattr__(g, "relevance_score", 1.0 - i * 0.1)

    with (
        patch.object(rk, "LLM_RERANK_ENABLED", False),
        patch.object(rk, "_ANTHROPIC_AVAILABLE", True),
    ):
        reranker = rk.LLMReranker()
        result = reranker.rerank(grants)

    # Should be sorted descending by relevance_score
    scores = [g.relevance_score for g in result]
    assert scores == sorted(scores, reverse=True)

    # No API call — client must not have been created
    assert reranker._client is None


# ---------------------------------------------------------------------------
# test_prompt_version_hash_stability
# ---------------------------------------------------------------------------


def test_prompt_version_hash_stability():
    """Same template produces same hash; mutated template produces different hash."""
    from grant_hunter.reranker import _prompt_version_hash, SCORING_PROMPT_TEMPLATE

    h1 = _prompt_version_hash()
    h2 = _prompt_version_hash()
    assert h1 == h2
    assert len(h1) == 16  # first 16 hex chars of SHA-256

    # Different content → different hash
    other = hashlib.sha256(b"different template").hexdigest()[:16]
    assert h1 != other


# ---------------------------------------------------------------------------
# test_cache_key_changes_with_description
# ---------------------------------------------------------------------------


def test_cache_key_changes_with_description():
    """Different descriptions produce different cache keys."""
    from grant_hunter.reranker import _cache_key

    g1 = make_grant(id="CK-001", title="Same Title", description="Version A")
    g2 = make_grant(id="CK-001", title="Same Title", description="Version B")

    k1 = _cache_key(g1, "default")
    k2 = _cache_key(g2, "default")
    assert k1 != k2


# ---------------------------------------------------------------------------
# test_cache_key_changes_with_prompt
# ---------------------------------------------------------------------------


def test_cache_key_changes_with_prompt():
    """Different prompt versions produce different cache keys."""
    from grant_hunter import reranker as rk

    g = make_grant(id="CK-002", title="T", description="D")

    original_template = rk.SCORING_PROMPT_TEMPLATE

    key_original = rk._cache_key(g, "default")

    # Temporarily mutate the module-level template
    with patch.object(rk, "SCORING_PROMPT_TEMPLATE", "COMPLETELY DIFFERENT TEMPLATE {grants_json}"):
        key_mutated = rk._cache_key(g, "default")

    assert key_original != key_mutated


# ---------------------------------------------------------------------------
# test_score_result_math
# ---------------------------------------------------------------------------


def test_score_result_math():
    """LLMScoreResult weighted average matches hand-calculated value."""
    from grant_hunter.reranker import LLMScoreResult

    # weights: research_alignment=0.40, institutional_fit=0.25,
    #          strategic_value=0.20, feasibility=0.15
    result = LLMScoreResult(
        grant_id="MATH-001",
        research_alignment=5,
        institutional_fit=4,
        strategic_value=3,
        feasibility=2,
        rationale="Test",
    )

    expected = round(5 * 0.40 + 4 * 0.25 + 3 * 0.20 + 2 * 0.15, 4)
    assert result.llm_score == expected  # 2.0 + 1.0 + 0.6 + 0.3 = 3.9

    # Additional known values
    result2 = LLMScoreResult(
        grant_id="MATH-002",
        research_alignment=1,
        institutional_fit=1,
        strategic_value=1,
        feasibility=1,
        rationale="Min",
    )
    assert result2.llm_score == 1.0

    result3 = LLMScoreResult(
        grant_id="MATH-003",
        research_alignment=5,
        institutional_fit=5,
        strategic_value=5,
        feasibility=5,
        rationale="Max",
    )
    assert result3.llm_score == 5.0


# ---------------------------------------------------------------------------
# test_batch_splitting
# ---------------------------------------------------------------------------


def test_batch_splitting():
    """12 grants processed in batches of [5, 5, 2] — no API calls made."""
    from grant_hunter import reranker as rk

    grants = _make_grants(12)

    call_sizes = []

    def fake_score_batch(batch, profile):
        call_sizes.append(len(batch))
        # Return empty results so rerank falls back to relevance_score
        return {}

    with (
        patch.object(rk, "LLM_RERANK_ENABLED", True),
        patch.object(rk, "_ANTHROPIC_AVAILABLE", True),
        patch.object(rk, "load_external_scores", return_value={}),
    ):
        reranker = rk.LLMReranker()
        with patch.object(reranker, "_score_batch", side_effect=fake_score_batch):
            reranker.rerank(grants)

    assert call_sizes == [5, 5, 2]


# ---------------------------------------------------------------------------
# test_fallback_no_anthropic
# ---------------------------------------------------------------------------


def test_fallback_no_anthropic():
    """When anthropic is unavailable, reranker degrades to relevance_score sort."""
    from grant_hunter import reranker as rk

    grants = _make_grants(4)
    for i, g in enumerate(grants):
        object.__setattr__(g, "relevance_score", round(0.9 - i * 0.2, 2))

    with patch.object(rk, "_ANTHROPIC_AVAILABLE", False):
        reranker = rk.LLMReranker()
        result = reranker.rerank(grants)

    scores = [g.relevance_score for g in result]
    assert scores == sorted(scores, reverse=True)
    # llm_score should be None for all
    for g in result:
        assert g.llm_score is None


# ---------------------------------------------------------------------------
# test_cache_ttl
# ---------------------------------------------------------------------------


def test_cache_ttl():
    """Expired cache entries (older than 90 days) are not returned."""
    from grant_hunter.reranker import _cache_read, _cache_write, LLMScoreResult

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)

        # Write a result with a timestamp 91 days ago
        old_time = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
        result = LLMScoreResult(
            grant_id="TTL-001",
            research_alignment=3,
            institutional_fit=3,
            strategic_value=3,
            feasibility=3,
            rationale="Old",
            scored_at=old_time,
        )
        # Force the scored_at to old_time (it's set in __post_init__ so override)
        result.scored_at = old_time

        _cache_write(cache_dir, "ttl-key", result)

        # Should return None because entry is expired
        cached = _cache_read(cache_dir, "ttl-key")
        assert cached is None

    # Fresh entry (scored_at = now) should be returned
    with tempfile.TemporaryDirectory() as tmpdir2:
        cache_dir2 = Path(tmpdir2)

        fresh_result = LLMScoreResult(
            grant_id="TTL-002",
            research_alignment=3,
            institutional_fit=3,
            strategic_value=3,
            feasibility=3,
            rationale="Fresh",
        )
        _cache_write(cache_dir2, "fresh-key", fresh_result)
        cached2 = _cache_read(cache_dir2, "fresh-key")
        assert cached2 is not None
        assert cached2.grant_id == "TTL-002"


# ---------------------------------------------------------------------------
# T7: load_external_scores tests
# ---------------------------------------------------------------------------


def _write_scores_json(scores_dir: Path, grants_data: list, date_str: str = "2026-03-25"):
    """Helper to write a subagent_scores JSON file."""
    scores_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "scored_at": f"{date_str}T12:00:00",
        "scorer": "subagent:sonnet",
        "prompt_version": "test",
        "grants": grants_data,
    }
    path = scores_dir / f"subagent_scores_{date_str}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_external_scores_valid():
    """load_external_scores returns correct LLMScoreResult objects."""
    from grant_hunter.reranker import load_external_scores, LLMScoreResult

    with tempfile.TemporaryDirectory() as tmpdir:
        scores_dir = Path(tmpdir) / "scores"
        _write_scores_json(scores_dir, [
            {
                "grant_id": "EXT-001",
                "research_alignment": 5,
                "institutional_fit": 4,
                "strategic_value": 3,
                "feasibility": 2,
                "rationale": "Test grant",
            },
            {
                "grant_id": "EXT-002",
                "research_alignment": 1,
                "institutional_fit": 1,
                "strategic_value": 1,
                "feasibility": 1,
                "rationale": "Low score",
            },
        ])

        result = load_external_scores(scores_dir)

    assert len(result) == 2
    assert "EXT-001" in result
    assert "EXT-002" in result
    assert isinstance(result["EXT-001"], LLMScoreResult)
    assert result["EXT-001"].research_alignment == 5
    assert result["EXT-001"].feasibility == 2
    assert result["EXT-001"].llm_score == round(5*0.4 + 4*0.25 + 3*0.2 + 2*0.15, 4)
    assert result["EXT-002"].llm_score == 1.0


def test_load_external_scores_empty_dir():
    """Returns empty dict when scores directory doesn't exist."""
    from grant_hunter.reranker import load_external_scores

    with tempfile.TemporaryDirectory() as tmpdir:
        result = load_external_scores(Path(tmpdir) / "nonexistent")

    assert result == {}


def test_load_external_scores_picks_latest():
    """When multiple score files exist, the latest by filename is used."""
    from grant_hunter.reranker import load_external_scores

    with tempfile.TemporaryDirectory() as tmpdir:
        scores_dir = Path(tmpdir) / "scores"
        # Write older file with grant A
        _write_scores_json(scores_dir, [
            {"grant_id": "OLD-001", "research_alignment": 1, "institutional_fit": 1,
             "strategic_value": 1, "feasibility": 1, "rationale": "old"},
        ], date_str="2026-03-20")
        # Write newer file with grant B
        _write_scores_json(scores_dir, [
            {"grant_id": "NEW-001", "research_alignment": 5, "institutional_fit": 5,
             "strategic_value": 5, "feasibility": 5, "rationale": "new"},
        ], date_str="2026-03-25")

        result = load_external_scores(scores_dir)

    assert "NEW-001" in result
    assert "OLD-001" not in result


def test_load_external_scores_clamps_values():
    """Dimension values are clamped to 1-5 range."""
    from grant_hunter.reranker import load_external_scores

    with tempfile.TemporaryDirectory() as tmpdir:
        scores_dir = Path(tmpdir) / "scores"
        _write_scores_json(scores_dir, [
            {"grant_id": "CLAMP-001", "research_alignment": 10, "institutional_fit": 0,
             "strategic_value": -1, "feasibility": 99, "rationale": "out of range"},
        ])

        result = load_external_scores(scores_dir)

    sr = result["CLAMP-001"]
    assert sr.research_alignment == 5
    assert sr.institutional_fit == 1
    assert sr.strategic_value == 1
    assert sr.feasibility == 5


def test_load_external_scores_skips_invalid_entries():
    """Invalid entries are skipped, valid ones are kept."""
    from grant_hunter.reranker import load_external_scores

    with tempfile.TemporaryDirectory() as tmpdir:
        scores_dir = Path(tmpdir) / "scores"
        _write_scores_json(scores_dir, [
            {"grant_id": "VALID-001", "research_alignment": 3, "institutional_fit": 3,
             "strategic_value": 3, "feasibility": 3, "rationale": "ok"},
            {"grant_id": "BAD-001"},  # missing required fields
            {"no_grant_id": True},    # missing grant_id
        ])

        result = load_external_scores(scores_dir)

    assert len(result) == 1
    assert "VALID-001" in result


def test_external_scores_priority_in_rerank():
    """External scores take priority over API path in rerank()."""
    from grant_hunter import reranker as rk

    grants = _make_grants(3)

    fake_external = {
        "GR-000": rk.LLMScoreResult(grant_id="GR-000", research_alignment=5,
                                      institutional_fit=5, strategic_value=5,
                                      feasibility=5, rationale="top"),
        "GR-001": rk.LLMScoreResult(grant_id="GR-001", research_alignment=1,
                                      institutional_fit=1, strategic_value=1,
                                      feasibility=1, rationale="bottom"),
        "GR-002": rk.LLMScoreResult(grant_id="GR-002", research_alignment=3,
                                      institutional_fit=3, strategic_value=3,
                                      feasibility=3, rationale="mid"),
    }

    with patch.object(rk, "load_external_scores", return_value=fake_external):
        reranker = rk.LLMReranker()
        result = reranker.rerank(grants)

    # GR-000 should be first (llm=5.0, highest blended)
    assert result[0].id == "GR-000"
    # All should have llm_score set
    for g in result:
        assert g.llm_score is not None


def test_mcp_tool_score_with_subagent():
    """MCP tool loads external scores and filters by tier."""
    from grant_hunter import reranker as rk
    from grant_hunter.server import _tool_grant_score_with_subagent

    fake_scores = {
        "TIER-A": rk.LLMScoreResult(grant_id="TIER-A", research_alignment=5,
                                      institutional_fit=5, strategic_value=5,
                                      feasibility=5, rationale="tier A"),
        "TIER-C": rk.LLMScoreResult(grant_id="TIER-C", research_alignment=1,
                                      institutional_fit=1, strategic_value=1,
                                      feasibility=1, rationale="tier C"),
    }

    with patch.object(rk, "load_external_scores", return_value=fake_scores):
        result_all = _tool_grant_score_with_subagent({"tier": "all"})
        result_a = _tool_grant_score_with_subagent({"tier": "A"})

    assert result_all["status"] == "ok"
    assert result_all["total"] == 2
    assert result_a["total"] == 1
    assert result_a["grants"][0]["grant_id"] == "TIER-A"
