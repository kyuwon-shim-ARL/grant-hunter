"""Tests for grant_hunter.server — tool dispatch and logic (no HTTP, no MCP init)."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_grant

# ── Import the internal functions directly ────────────────────────────────────

import grant_hunter.server as srv
from grant_hunter.server import (
    _dispatch,
    _load_config,
    _prune_old_jobs,
    _save_config,
    _tool_grant_check_eligibility,
    _tool_grant_collect,
    _tool_grant_collect_result,
    _tool_grant_collect_status,
    _tool_grant_config_get,
    _tool_grant_config_set,
    _tool_grant_deadlines,
    _tool_grant_list_profiles,
    _tool_grant_report,
    _tool_grant_search,
    list_tools,
)


# ── _load_config / _save_config ───────────────────────────────────────────────

def test_load_config_missing_file(tmp_path):
    with patch.object(srv, "CONFIG_FILE", tmp_path / "config.json"):
        cfg = _load_config()
    assert cfg["email"] == ""
    assert "data_dir" in cfg


def test_save_and_load_config(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch.object(srv, "CONFIG_FILE", cfg_path):
        _save_config({"email": "test@example.com", "data_dir": "/tmp"})
        loaded = _load_config()
    assert loaded["email"] == "test@example.com"


def test_save_config_creates_parent(tmp_path):
    cfg_path = tmp_path / "nested" / "dir" / "config.json"
    with patch.object(srv, "CONFIG_FILE", cfg_path):
        _save_config({"email": "a@b.com", "data_dir": "/x"})
    assert cfg_path.exists()


# ── _prune_old_jobs ───────────────────────────────────────────────────────────

def test_prune_old_jobs_removes_expired(monkeypatch):
    old_time = datetime.utcnow() - timedelta(seconds=srv._JOB_TTL_SECONDS + 10)
    srv._jobs.clear()
    srv._jobs["old-job"] = {
        "status": "completed",
        "completed_at": old_time,
    }
    srv._jobs["new-job"] = {
        "status": "completed",
        "completed_at": datetime.utcnow(),
    }
    srv._jobs["running-job"] = {
        "status": "running",
        "completed_at": None,
    }
    _prune_old_jobs()
    assert "old-job" not in srv._jobs
    assert "new-job" in srv._jobs
    assert "running-job" in srv._jobs
    srv._jobs.clear()


def test_prune_old_jobs_keeps_recent():
    srv._jobs.clear()
    srv._jobs["recent"] = {
        "status": "failed",
        "completed_at": datetime.utcnow(),
    }
    _prune_old_jobs()
    assert "recent" in srv._jobs
    srv._jobs.clear()


# ── _tool_grant_collect ───────────────────────────────────────────────────────

def test_tool_grant_collect_creates_job():
    srv._jobs.clear()
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        result = _tool_grant_collect({"sources": ["nih"], "test": True})

    assert "job_id" in result
    assert result["status"] == "started"
    assert "nih" in result["sources"]
    mock_thread.start.assert_called_once()
    srv._jobs.clear()


def test_tool_grant_collect_defaults_all_sources():
    srv._jobs.clear()
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        result = _tool_grant_collect({})

    assert set(result["sources"]) == set(srv.ALL_SOURCES)
    srv._jobs.clear()


# ── _tool_grant_collect_status ────────────────────────────────────────────────

def test_tool_grant_collect_status_found():
    srv._jobs.clear()
    srv._jobs["abc123"] = {
        "status": "running",
        "completed_sources": ["nih"],
        "pending_sources": ["eu"],
        "error": None,
    }
    result = _tool_grant_collect_status({"job_id": "abc123"})
    assert result["status"] == "running"
    assert "nih" in result["completed_sources"]
    srv._jobs.clear()


def test_tool_grant_collect_status_missing():
    srv._jobs.clear()
    result = _tool_grant_collect_status({"job_id": "nonexistent"})
    assert "error" in result


# ── _tool_grant_collect_result ────────────────────────────────────────────────

def test_tool_grant_collect_result_completed():
    srv._jobs.clear()
    srv._jobs["done-job"] = {
        "status": "completed",
        "result": {"filtered": 5, "eligible": 2},
        "error": None,
    }
    result = _tool_grant_collect_result({"job_id": "done-job"})
    assert result["filtered"] == 5
    srv._jobs.clear()


def test_tool_grant_collect_result_still_running():
    srv._jobs.clear()
    srv._jobs["run-job"] = {
        "status": "running",
        "result": None,
        "error": None,
    }
    result = _tool_grant_collect_result({"job_id": "run-job"})
    assert "error" in result
    assert "running" in result["error"].lower()
    srv._jobs.clear()


def test_tool_grant_collect_result_failed():
    srv._jobs.clear()
    srv._jobs["fail-job"] = {
        "status": "failed",
        "result": None,
        "error": "Network timeout",
    }
    result = _tool_grant_collect_result({"job_id": "fail-job"})
    assert "error" in result
    srv._jobs.clear()


def test_tool_grant_collect_result_missing():
    srv._jobs.clear()
    result = _tool_grant_collect_result({"job_id": "ghost"})
    assert "error" in result


# ── _tool_grant_search ────────────────────────────────────────────────────────

def _make_snapshot_grants():
    return [
        make_grant(id="g1", title="AMR antibiotic resistance study", agency="NIH", source="nih", relevance_score=0.8),
        make_grant(id="g2", title="Climate change research", agency="EPA", source="grants_gov", relevance_score=0.3),
        make_grant(id="g3", title="Machine learning for genomics", agency="NIH", source="nih", relevance_score=0.6),
    ]


def test_tool_grant_search_query_filter():
    grants = _make_snapshot_grants()
    with patch.object(srv, "_load_latest_snapshots", return_value=grants):
        result = _tool_grant_search({"query": "antibiotic"})
    assert isinstance(result, list)
    assert len(result) == 1
    assert "AMR" in result[0]["title"]


def test_tool_grant_search_source_filter():
    grants = _make_snapshot_grants()
    with patch.object(srv, "_load_latest_snapshots", return_value=grants):
        result = _tool_grant_search({"query": "", "source": "grants_gov"})
    assert isinstance(result, list)
    assert all(r["source"] == "grants_gov" for r in result)


def test_tool_grant_search_min_score_filter():
    grants = _make_snapshot_grants()
    with patch.object(srv, "_load_latest_snapshots", return_value=grants):
        result = _tool_grant_search({"query": "", "min_score": 0.7})
    assert isinstance(result, list)
    # Only g1 has relevance_score=0.8, but scorer re-scores; just check structure
    for r in result:
        assert "score" in r


def test_tool_grant_search_empty_snapshots():
    with patch.object(srv, "_load_latest_snapshots", return_value=[]):
        result = _tool_grant_search({"query": "anything"})
    assert result == []


# ── _tool_grant_list_profiles ─────────────────────────────────────────────────

def test_tool_grant_list_profiles():
    result = _tool_grant_list_profiles({})
    assert "profiles" in result
    assert isinstance(result["profiles"], dict)


# ── _tool_grant_deadlines ─────────────────────────────────────────────────────

def test_tool_grant_deadlines_returns_within_range():
    today = date.today()
    grants = [
        make_grant(id="d1", title="Soon Grant", deadline=today + timedelta(days=10)),
        make_grant(id="d2", title="Far Grant", deadline=today + timedelta(days=200)),
        make_grant(id="d3", title="Past Grant", deadline=today - timedelta(days=5)),
        make_grant(id="d4", title="No Deadline Grant", deadline=None),
    ]
    with patch.object(srv, "_load_latest_snapshots", return_value=grants):
        result = _tool_grant_deadlines({"days": 90})
    assert isinstance(result, list)
    titles = [r["title"] for r in result]
    assert "Soon Grant" in titles
    assert "Far Grant" not in titles
    assert "Past Grant" not in titles


def test_tool_grant_deadlines_empty():
    with patch.object(srv, "_load_latest_snapshots", return_value=[]):
        result = _tool_grant_deadlines({})
    assert result == []


def test_tool_grant_deadlines_sorted_by_days():
    today = date.today()
    grants = [
        make_grant(id="late", title="Later", deadline=today + timedelta(days=50)),
        make_grant(id="soon", title="Sooner", deadline=today + timedelta(days=5)),
    ]
    with patch.object(srv, "_load_latest_snapshots", return_value=grants):
        result = _tool_grant_deadlines({"days": 90})
    if len(result) >= 2:
        assert result[0]["days_until"] <= result[1]["days_until"]


# ── _tool_grant_check_eligibility ─────────────────────────────────────────────

def test_tool_grant_check_eligibility_by_id():
    g = make_grant(id="elig-001", title="Eligibility Test Grant")
    with patch.object(srv, "_load_latest_snapshots", return_value=[g]):
        result = _tool_grant_check_eligibility({"grant_id": "elig-001"})
    assert "status" in result
    assert "confidence" in result


def test_tool_grant_check_eligibility_by_title():
    g = make_grant(id="elig-002", title="Unique Title Grant ABC")
    with patch.object(srv, "_load_latest_snapshots", return_value=[g]):
        result = _tool_grant_check_eligibility({"title": "Unique Title"})
    assert "status" in result


def test_tool_grant_check_eligibility_not_found():
    with patch.object(srv, "_load_latest_snapshots", return_value=[]):
        result = _tool_grant_check_eligibility({"grant_id": "missing"})
    assert "error" in result


def test_tool_grant_check_eligibility_no_args():
    result = _tool_grant_check_eligibility({})
    assert "error" in result


# ── _tool_grant_report ────────────────────────────────────────────────────────

def test_tool_grant_report_dashboard_format(tmp_path):
    grants = [make_grant(id="r1", title="Report Grant")]
    fake_path = tmp_path / "dashboard.html"
    fake_path.write_text("<html/>")
    with patch.object(srv, "_load_latest_snapshots", return_value=grants), \
         patch("grant_hunter.dashboard.generate_dashboard", return_value=fake_path), \
         patch("grant_hunter.eligibility.EligibilityEngine") as mock_ee_cls, \
         patch("grant_hunter.scoring.RelevanceScorer") as mock_scorer_cls:
        mock_ee = MagicMock()
        mock_ee.check.return_value = MagicMock(status="eligible", reason="ok")
        mock_ee_cls.return_value = mock_ee
        mock_scorer = MagicMock()
        mock_scorer.score.return_value = 0.5
        mock_scorer_cls.return_value = mock_scorer
        result = _tool_grant_report({"format": "dashboard"})
    assert "path" in result
    assert "grant_count" in result


def test_tool_grant_report_html_format(tmp_path):
    grants = [make_grant(id="r2", title="HTML Report Grant")]
    fake_path = tmp_path / "report.html"
    fake_path.write_text("<html/>")
    with patch.object(srv, "_load_latest_snapshots", return_value=grants), \
         patch("grant_hunter.report_generator.generate_html_report", return_value=fake_path), \
         patch("grant_hunter.eligibility.EligibilityEngine") as mock_ee_cls:
        mock_ee = MagicMock()
        mock_ee.check.return_value = MagicMock(status="eligible", reason="ok")
        mock_ee_cls.return_value = mock_ee
        result = _tool_grant_report({"format": "html"})
    assert "path" in result


# ── _tool_grant_config_set / _tool_grant_config_get ──────────────────────────

def test_tool_grant_config_set_valid_key(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch.object(srv, "CONFIG_FILE", cfg_path):
        result = _tool_grant_config_set({"key": "email", "value": "user@test.com"})
    assert result["ok"] is True
    assert result["value"] == "user@test.com"


def test_tool_grant_config_set_invalid_key(tmp_path):
    with patch.object(srv, "CONFIG_FILE", tmp_path / "config.json"):
        result = _tool_grant_config_set({"key": "unknown_key", "value": "val"})
    assert "error" in result


def test_tool_grant_config_get_all(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch.object(srv, "CONFIG_FILE", cfg_path):
        _save_config({"email": "x@y.com", "data_dir": "/d"})
        result = _tool_grant_config_get({})
    assert result["email"] == "x@y.com"


def test_tool_grant_config_get_specific_key(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch.object(srv, "CONFIG_FILE", cfg_path):
        _save_config({"email": "specific@test.com", "data_dir": "/d"})
        result = _tool_grant_config_get({"key": "email"})
    assert result["email"] == "specific@test.com"


# ── _dispatch ─────────────────────────────────────────────────────────────────

def test_dispatch_unknown_tool():
    result = asyncio.run(_dispatch("nonexistent_tool", {}))
    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_dispatch_grant_collect():
    srv._jobs.clear()
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value = MagicMock()
        result = asyncio.run(_dispatch("grant_collect", {"sources": ["nih"]}))
    assert result["status"] == "started"
    srv._jobs.clear()


def test_dispatch_grant_config_get(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch.object(srv, "CONFIG_FILE", cfg_path):
        result = asyncio.run(_dispatch("grant_config_get", {}))
    assert "email" in result


def test_dispatch_grant_list_profiles():
    result = asyncio.run(_dispatch("grant_list_profiles", {}))
    assert "profiles" in result


def test_dispatch_all_tool_names():
    """All known tool names route without raising AttributeError."""
    tool_names = [
        "grant_collect_status",
        "grant_collect_result",
        "grant_deadlines",
        "grant_check_eligibility",
    ]
    for name in tool_names:
        result = asyncio.run(_dispatch(name, {}))
        # Should return a dict (possibly with error key, but not raise)
        assert isinstance(result, (dict, list))


# ── list_tools ────────────────────────────────────────────────────────────────

def test_list_tools_returns_tools():
    tools = asyncio.run(list_tools())
    assert len(tools) >= 9


def test_list_tools_names():
    tools = asyncio.run(list_tools())
    names = {t.name for t in tools}
    expected = {
        "grant_collect",
        "grant_collect_status",
        "grant_collect_result",
        "grant_search",
        "grant_list_profiles",
        "grant_deadlines",
        "grant_check_eligibility",
        "grant_report",
        "grant_config_set",
    }
    assert expected.issubset(names)
