"""Tests for grant validation, retry logic, and staleness detection."""

import time
import pytest
from unittest.mock import patch, MagicMock

from grant_hunter.pipeline import validate_grant, _collect_with_retry


# ── validate_grant ────────────────────────────────────────────────────────────

def test_validate_grant_rejects_missing_title():
    grant = {"title": "", "description": "A" * 50}
    ok, reason = validate_grant(grant)
    assert not ok
    assert "missing title" in reason


def test_validate_grant_rejects_missing_title_key():
    grant = {"description": "A" * 50}
    ok, reason = validate_grant(grant)
    assert not ok
    assert "missing title" in reason


def test_validate_grant_rejects_short_description():
    grant = {"title": "Valid Title", "description": "Too short"}
    ok, reason = validate_grant(grant)
    assert not ok
    assert "description too short" in reason


def test_validate_grant_rejects_description_exactly_49_chars():
    grant = {"title": "Valid Title", "description": "A" * 49}
    ok, reason = validate_grant(grant)
    assert not ok
    assert "description too short" in reason


def test_validate_grant_accepts_valid_grant():
    grant = {"title": "Valid AMR Grant", "description": "A" * 50}
    ok, reason = validate_grant(grant)
    assert ok
    assert reason == "ok"


def test_validate_grant_accepts_description_exactly_50_chars():
    grant = {"title": "Valid Title", "description": "A" * 50}
    ok, reason = validate_grant(grant)
    assert ok


def test_validate_grant_strips_whitespace_from_title():
    grant = {"title": "   ", "description": "A" * 50}
    ok, reason = validate_grant(grant)
    assert not ok
    assert "missing title" in reason


# ── _collect_with_retry ───────────────────────────────────────────────────────

def test_collect_with_retry_succeeds_on_first_attempt():
    collector_fn = MagicMock(return_value=[{"title": "Grant 1"}])
    result = _collect_with_retry(collector_fn, "test_source", max_retries=3)
    assert result == [{"title": "Grant 1"}]
    assert collector_fn.call_count == 1


def test_collect_with_retry_succeeds_after_failure():
    results = [Exception("network error"), [{"title": "Grant 1"}]]

    def side_effect():
        val = results.pop(0)
        if isinstance(val, Exception):
            raise val
        return val

    with patch("time.sleep"):
        result = _collect_with_retry(side_effect, "test_source", max_retries=3)

    assert result == [{"title": "Grant 1"}]


def test_collect_with_retry_returns_empty_after_max_retries():
    collector_fn = MagicMock(side_effect=Exception("always fails"))

    with patch("time.sleep"):
        result = _collect_with_retry(collector_fn, "test_source", max_retries=3)

    assert result == []
    assert collector_fn.call_count == 3


def test_collect_with_retry_uses_exponential_backoff():
    collector_fn = MagicMock(side_effect=Exception("fail"))
    sleep_calls = []

    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        _collect_with_retry(collector_fn, "test_source", max_retries=3)

    # Should sleep after attempt 0 (1s) and attempt 1 (2s), not after final attempt
    assert sleep_calls == [1, 2]
