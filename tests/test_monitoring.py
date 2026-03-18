"""Tests for grant_hunter.monitoring module."""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grant_hunter.monitoring import (
    check_volume_anomaly,
    load_run_history,
    save_run_history,
    send_anomaly_alert,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_summary(total_collected=100, filtered=50, eligible=10, sources=None, run_at=None):
    if sources is None:
        sources = {
            "grants_gov": {"collected": 60, "success": True},
            "nih": {"collected": 40, "success": True},
        }
    return {
        "run_at": run_at or "2026-01-01T00:00:00",
        "total_collected": total_collected,
        "filtered": filtered,
        "eligible": eligible,
        "sources": sources,
    }


# ── save_run_history ───────────────────────────────────────────────────────────

def test_save_run_history_creates_file(tmp_path):
    history_file = tmp_path / "run_history.json"
    summary = _make_summary()
    save_run_history(summary, history_file)
    assert history_file.exists()


def test_save_run_history_appends(tmp_path):
    history_file = tmp_path / "run_history.json"
    save_run_history(_make_summary(total_collected=100), history_file)
    save_run_history(_make_summary(total_collected=200), history_file)
    history = json.loads(history_file.read_text())
    assert len(history) == 2
    assert history[0]["total_collected"] == 100
    assert history[1]["total_collected"] == 200


def test_save_run_history_caps_at_90(tmp_path):
    history_file = tmp_path / "run_history.json"
    for i in range(95):
        save_run_history(_make_summary(total_collected=i), history_file)
    history = json.loads(history_file.read_text())
    assert len(history) == 90
    # Last entry is the most recent
    assert history[-1]["total_collected"] == 94


def test_save_run_history_stores_correct_fields(tmp_path):
    history_file = tmp_path / "run_history.json"
    summary = _make_summary(total_collected=77, filtered=30, eligible=5)
    save_run_history(summary, history_file)
    history = json.loads(history_file.read_text())
    entry = history[0]
    assert entry["total_collected"] == 77
    assert entry["filtered"] == 30
    assert entry["eligible"] == 5
    assert "sources" in entry
    assert "run_at" in entry


def test_save_run_history_creates_parent_dirs(tmp_path):
    history_file = tmp_path / "nested" / "deep" / "run_history.json"
    save_run_history(_make_summary(), history_file)
    assert history_file.exists()


# ── load_run_history ───────────────────────────────────────────────────────────

def test_load_run_history_missing_file(tmp_path):
    history_file = tmp_path / "nonexistent.json"
    result = load_run_history(history_file)
    assert result == []


def test_load_run_history_corrupt_json(tmp_path):
    history_file = tmp_path / "run_history.json"
    history_file.write_text("not valid json {{{{", encoding="utf-8")
    result = load_run_history(history_file)
    assert result == []


def test_load_run_history_returns_list(tmp_path):
    history_file = tmp_path / "run_history.json"
    data = [{"total_collected": 10}, {"total_collected": 20}]
    history_file.write_text(json.dumps(data), encoding="utf-8")
    result = load_run_history(history_file)
    assert result == data


# ── check_volume_anomaly ───────────────────────────────────────────────────────

def test_check_volume_anomaly_no_history_no_alert(tmp_path):
    history_file = tmp_path / "run_history.json"
    summary = _make_summary(total_collected=100)
    alerts = check_volume_anomaly(summary, history_file)
    assert alerts == []


def test_check_volume_anomaly_source_failure(tmp_path):
    history_file = tmp_path / "run_history.json"
    summary = _make_summary(sources={
        "grants_gov": {"collected": 0, "success": False, "error": "timeout"},
    })
    alerts = check_volume_anomaly(summary, history_file)
    assert any("SOURCE_FAIL" in a and "grants_gov" in a for a in alerts)


def test_check_volume_anomaly_zero_collect_on_success(tmp_path):
    history_file = tmp_path / "run_history.json"
    summary = _make_summary(sources={
        "grants_gov": {"collected": 0, "success": True},
    })
    alerts = check_volume_anomaly(summary, history_file)
    assert any("ZERO_COLLECT" in a and "grants_gov" in a for a in alerts)


def test_check_volume_anomaly_zero_collect_on_failure_no_zero_alert(tmp_path):
    """Failed source should trigger SOURCE_FAIL but NOT ZERO_COLLECT."""
    history_file = tmp_path / "run_history.json"
    summary = _make_summary(sources={
        "nih": {"collected": 0, "success": False, "error": "HTTP 500"},
    })
    alerts = check_volume_anomaly(summary, history_file)
    assert not any("ZERO_COLLECT" in a for a in alerts)
    assert any("SOURCE_FAIL" in a for a in alerts)


def test_check_volume_anomaly_volume_drop(tmp_path):
    history_file = tmp_path / "run_history.json"
    # Build history with avg=100
    for i in range(7):
        save_run_history(_make_summary(total_collected=100), history_file)
    # Current run: only 40 (60% drop)
    summary = _make_summary(total_collected=40)
    alerts = check_volume_anomaly(summary, history_file)
    assert any("VOLUME_DROP" in a for a in alerts)


def test_check_volume_anomaly_no_volume_drop_when_above_threshold(tmp_path):
    history_file = tmp_path / "run_history.json"
    for i in range(7):
        save_run_history(_make_summary(total_collected=100), history_file)
    # Current: 60 (only 40% drop, threshold is >50%)
    summary = _make_summary(total_collected=60)
    alerts = check_volume_anomaly(summary, history_file)
    assert not any("VOLUME_DROP" in a for a in alerts)


def test_check_volume_anomaly_no_alert_when_normal(tmp_path):
    history_file = tmp_path / "run_history.json"
    for i in range(5):
        save_run_history(_make_summary(total_collected=100), history_file)
    summary = _make_summary(total_collected=95)
    alerts = check_volume_anomaly(summary, history_file)
    assert alerts == []


def test_check_volume_anomaly_volume_drop_needs_3_history(tmp_path):
    """Volume drop rule only applies when history has >=3 entries."""
    history_file = tmp_path / "run_history.json"
    for i in range(2):
        save_run_history(_make_summary(total_collected=100), history_file)
    # Only 2 history entries — volume drop rule should not trigger
    summary = _make_summary(total_collected=10)
    alerts = check_volume_anomaly(summary, history_file)
    assert not any("VOLUME_DROP" in a for a in alerts)


# ── send_anomaly_alert ─────────────────────────────────────────────────────────

def test_send_anomaly_alert_empty_returns_false():
    result = send_anomaly_alert([], "test@example.com")
    assert result is False


def test_send_anomaly_alert_calls_send_email():
    alerts = ["ZERO_COLLECT: nih collected 0 grants"]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = send_anomaly_alert(alerts, "test@example.com")
    assert result is True
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "send-email"
    assert call_args[1] == "test@example.com"
    assert "ALERT" in call_args[2]


def test_send_anomaly_alert_returns_false_on_nonzero_exit():
    alerts = ["SOURCE_FAIL: grants_gov failed"]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = send_anomaly_alert(alerts, "test@example.com")
    assert result is False


def test_send_anomaly_alert_handles_file_not_found():
    alerts = ["VOLUME_DROP: collected 10 vs avg 100"]
    with patch("subprocess.run", side_effect=FileNotFoundError("send-email not found")):
        result = send_anomaly_alert(alerts, "test@example.com")
    assert result is False


def test_send_anomaly_alert_subject_contains_count():
    alerts = ["alert1", "alert2", "alert3"]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        send_anomaly_alert(alerts, "test@example.com")
    subject = mock_run.call_args[0][0][2]
    assert "3" in subject
