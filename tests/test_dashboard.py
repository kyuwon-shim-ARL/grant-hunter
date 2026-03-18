"""Tests for grant_hunter.dashboard — helper functions and HTML generation."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from tests.conftest import make_grant
import grant_hunter.dashboard as dashboard_mod
from grant_hunter.dashboard import (
    _deadline_label,
    _days_until,
    _esc,
    _fmt_amount,
    _source_label,
    _build_calendar,
    _grant_to_json_row,
    generate_dashboard,
)


# ── _esc ──────────────────────────────────────────────────────────────────────

def test_esc_plain_string():
    assert _esc("hello world") == "hello world"


def test_esc_html_characters():
    result = _esc('<script>alert("xss")</script>')
    assert "<script>" not in result
    assert "&lt;" in result


def test_esc_none():
    result = _esc(None)
    assert isinstance(result, str)


def test_esc_ampersand():
    assert "&amp;" in _esc("a & b")


# ── _fmt_amount ───────────────────────────────────────────────────────────────

def test_fmt_amount_none():
    assert _fmt_amount(None) == "N/A"


def test_fmt_amount_small():
    assert _fmt_amount(500) == "$500"


def test_fmt_amount_thousands():
    result = _fmt_amount(50_000)
    assert "K" in result
    assert "50" in result


def test_fmt_amount_millions():
    result = _fmt_amount(2_500_000)
    assert "M" in result
    assert "2.5" in result


def test_fmt_amount_exact_million():
    result = _fmt_amount(1_000_000)
    assert "M" in result


# ── _days_until ───────────────────────────────────────────────────────────────

def test_days_until_none():
    assert _days_until(None) is None


def test_days_until_future():
    future = date.today() + timedelta(days=10)
    assert _days_until(future) == 10


def test_days_until_past():
    past = date.today() - timedelta(days=5)
    assert _days_until(past) == -5


def test_days_until_today():
    assert _days_until(date.today()) == 0


# ── _deadline_label ───────────────────────────────────────────────────────────

def test_deadline_label_none():
    assert _deadline_label(None) == "N/A"


def test_deadline_label_expired():
    past = date.today() - timedelta(days=3)
    label = _deadline_label(past)
    assert "Expired" in label


def test_deadline_label_today():
    label = _deadline_label(date.today())
    assert "TODAY" in label


def test_deadline_label_within_7_days():
    soon = date.today() + timedelta(days=3)
    label = _deadline_label(soon)
    assert "3d" in label or "⚠" in label


def test_deadline_label_30_days():
    future = date.today() + timedelta(days=30)
    label = _deadline_label(future)
    # Should just be the date string
    assert str(future) in label


# ── _source_label ─────────────────────────────────────────────────────────────

def test_source_label_nih():
    assert _source_label("nih") == "NIH"


def test_source_label_eu():
    assert _source_label("eu") == "EU Portal"


def test_source_label_grants_gov():
    assert _source_label("grants_gov") == "Grants.gov"


def test_source_label_unknown():
    result = _source_label("mystery_source")
    # Unknown source should be uppercased or returned as-is
    assert isinstance(result, str)
    assert len(result) > 0


# ── _build_calendar ───────────────────────────────────────────────────────────

def test_build_calendar_empty_no_deadlines():
    grants = [make_grant(id="g1", deadline=None)]
    result = _build_calendar(grants)
    assert "No deadlines" in result


def test_build_calendar_with_future_deadline():
    future = date.today() + timedelta(days=15)
    g = make_grant(id="g1", title="Future Grant", deadline=future)
    result = _build_calendar([g])
    assert "cal-wrapper" in result
    assert "has-deadline" in result


def test_build_calendar_past_deadline_not_shown():
    past = date.today() - timedelta(days=10)
    g = make_grant(id="g1", deadline=past)
    result = _build_calendar([g])
    assert "No deadlines" in result


def test_build_calendar_deadline_beyond_90_days():
    far_future = date.today() + timedelta(days=120)
    g = make_grant(id="g1", deadline=far_future)
    result = _build_calendar([g])
    assert "No deadlines" in result


def test_build_calendar_multiple_grants_same_day():
    deadline = date.today() + timedelta(days=5)
    grants = [
        make_grant(id="g1", title="Grant A", deadline=deadline),
        make_grant(id="g2", title="Grant B", deadline=deadline),
    ]
    result = _build_calendar(grants)
    assert "2" in result  # badge count


# ── _grant_to_json_row ────────────────────────────────────────────────────────

def test_grant_to_json_row_structure():
    g = make_grant(
        id="row-001",
        title="Row Test Grant",
        agency="Test Agency",
        source="nih",
        url="https://example.com",
        amount_max=500_000,
        deadline=date.today() + timedelta(days=20),
    )
    row = _grant_to_json_row(g, "eligible", "Meets criteria", 0.75)
    assert row["id"] == "row-001"
    assert row["title"] == "Row Test Grant"
    assert row["agency"] == "Test Agency"
    assert row["source"] == "NIH"
    assert row["eligibility"] == "eligible"
    assert row["elig_reason"] == "Meets criteria"
    assert row["score"] == 75.0
    assert row["amount_label"] == "$500K"


def test_grant_to_json_row_no_deadline():
    g = make_grant(id="r2", deadline=None)
    row = _grant_to_json_row(g, "uncertain", "", 0.0)
    assert row["deadline"] == ""
    assert row["days_until"] is None


def test_grant_to_json_row_amount_uses_max_over_min():
    g = make_grant(id="r3", amount_min=100_000, amount_max=500_000)
    row = _grant_to_json_row(g, "", "", 0.0)
    assert "500" in row["amount_label"]


# ── generate_dashboard ────────────────────────────────────────────────────────

def test_generate_dashboard_creates_file(tmp_path):
    grants = [
        make_grant(id="d1", title="Eligible Grant", source="nih", relevance_score=0.8),
        make_grant(id="d2", title="Uncertain Grant", source="eu", relevance_score=0.5),
        make_grant(id="d3", title="Ineligible Grant", source="grants_gov", relevance_score=0.2),
    ]
    elig_map = {
        grants[0].fingerprint(): "eligible",
        grants[1].fingerprint(): "uncertain",
        grants[2].fingerprint(): "ineligible",
    }
    reason_map = {fp: "test reason" for fp in elig_map}
    score_map = {g.fingerprint(): g.relevance_score for g in grants}
    stats = {"nih": {"collected": 10, "filtered": 1}}
    run_date = datetime(2026, 3, 17, 12, 0, 0)

    original_dir = dashboard_mod.REPORTS_DIR
    dashboard_mod.REPORTS_DIR = tmp_path
    try:
        path = generate_dashboard(
            all_filtered=grants,
            eligibility_map=elig_map,
            eligibility_reason_map=reason_map,
            score_map=score_map,
            stats=stats,
            run_date=run_date,
        )
    finally:
        dashboard_mod.REPORTS_DIR = original_dir

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Grant Hunter Dashboard" in content
    assert "Eligible Grant" in content
    assert "Uncertain Grant" in content
    assert "var DATA" in content


def test_generate_dashboard_summary_cards(tmp_path):
    grants = [
        make_grant(id="e1", title="Grant E"),
        make_grant(id="e2", title="Grant U"),
    ]
    elig_map = {
        grants[0].fingerprint(): "eligible",
        grants[1].fingerprint(): "uncertain",
    }
    original_dir = dashboard_mod.REPORTS_DIR
    dashboard_mod.REPORTS_DIR = tmp_path
    try:
        path = generate_dashboard(
            all_filtered=grants,
            eligibility_map=elig_map,
            eligibility_reason_map={},
            score_map={},
            stats={},
            run_date=datetime(2026, 1, 1, 0, 0, 0),
        )
    finally:
        dashboard_mod.REPORTS_DIR = original_dir

    content = path.read_text(encoding="utf-8")
    assert "Eligible (IPK)" in content
    assert "Uncertain" in content
