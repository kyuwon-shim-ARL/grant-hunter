"""Tests for grant_hunter.report_generator — helper functions and HTML generation."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from tests.conftest import make_grant
import grant_hunter.report_generator as rg_mod
from grant_hunter.report_generator import (
    _deadline_class,
    _fmt_amount,
    _fmt_deadline,
    _grant_row,
    _is_urgent,
    _source_badge,
    generate_html_report,
)
from grant_hunter.config import DEADLINE_WARN_DAYS


# ── _fmt_amount ───────────────────────────────────────────────────────────────

def test_fmt_amount_none():
    assert _fmt_amount(None) == "N/A"


def test_fmt_amount_small():
    assert _fmt_amount(999) == "$999"


def test_fmt_amount_thousands():
    result = _fmt_amount(75_000)
    assert "K" in result
    assert "75" in result


def test_fmt_amount_millions():
    result = _fmt_amount(3_000_000)
    assert "M" in result
    assert "3.0" in result


# ── _fmt_deadline ─────────────────────────────────────────────────────────────

def test_fmt_deadline_none():
    assert _fmt_deadline(None) == "N/A"


def test_fmt_deadline_real_date():
    d = date(2026, 6, 15)
    result = _fmt_deadline(d)
    assert result == "2026-06-15"


# ── _is_urgent ────────────────────────────────────────────────────────────────

def test_is_urgent_none():
    assert _is_urgent(None) is False


def test_is_urgent_within_warn_days():
    soon = date.today() + timedelta(days=DEADLINE_WARN_DAYS - 1)
    assert _is_urgent(soon) is True


def test_is_urgent_today():
    assert _is_urgent(date.today()) is True


def test_is_urgent_outside_warn_days():
    far = date.today() + timedelta(days=DEADLINE_WARN_DAYS + 5)
    assert _is_urgent(far) is False


def test_is_urgent_past():
    past = date.today() - timedelta(days=1)
    assert _is_urgent(past) is False


# ── _deadline_class ───────────────────────────────────────────────────────────

def test_deadline_class_none():
    assert _deadline_class(None) == ""


def test_deadline_class_expired():
    past = date.today() - timedelta(days=3)
    assert _deadline_class(past) == "expired"


def test_deadline_class_urgent():
    soon = date.today() + timedelta(days=2)
    assert _deadline_class(soon) == "urgent"


def test_deadline_class_normal():
    future = date.today() + timedelta(days=DEADLINE_WARN_DAYS + 10)
    assert _deadline_class(future) == ""


# ── _source_badge ─────────────────────────────────────────────────────────────

def test_source_badge_nih():
    result = _source_badge("nih")
    assert "NIH" in result
    assert "#1a73e8" in result
    assert "badge" in result


def test_source_badge_eu():
    result = _source_badge("eu")
    assert "EU Portal" in result
    assert "#34a853" in result


def test_source_badge_grants_gov():
    result = _source_badge("grants_gov")
    assert "Grants.gov" in result


def test_source_badge_unknown():
    result = _source_badge("custom_source")
    assert "CUSTOM_SOURCE" in result
    assert "#888" in result


# ── _grant_row ────────────────────────────────────────────────────────────────

def test_grant_row_contains_title():
    g = make_grant(id="row-1", title="Test Row Grant", agency="NIH", source="nih")
    row = _grant_row(g)
    assert "Test Row Grant" in row


def test_grant_row_contains_agency():
    g = make_grant(id="row-2", title="Grant", agency="EPA", source="grants_gov")
    row = _grant_row(g)
    assert "EPA" in row


def test_grant_row_contains_eligibility():
    g = make_grant(id="row-3", title="Elig Grant", source="nih")
    row = _grant_row(g, eligibility="eligible", reason="Meets all criteria")
    assert "eligible" in row
    assert "Meets all criteria" in row


def test_grant_row_no_eligibility():
    g = make_grant(id="row-4", title="Plain Grant", source="nih")
    row = _grant_row(g)
    # Should contain the dash placeholder for no eligibility
    assert "—" in row or "aaa" in row


def test_grant_row_urgent_class():
    g = make_grant(
        id="row-5",
        title="Urgent Grant",
        source="nih",
        deadline=date.today() + timedelta(days=2),
    )
    row = _grant_row(g)
    assert "urgent" in row


def test_grant_row_expired_class():
    g = make_grant(
        id="row-6",
        title="Expired Grant",
        source="nih",
        deadline=date.today() - timedelta(days=10),
    )
    row = _grant_row(g)
    assert "expired" in row


def test_grant_row_new_tag():
    g = make_grant(id="row-7", title="New Grant", source="nih")
    row = _grant_row(g, tag="new")
    assert "NEW" in row
    assert "tag-new" in row


# ── generate_html_report ──────────────────────────────────────────────────────

def test_generate_html_report_creates_file(tmp_path):
    grants = [
        make_grant(id="rpt-1", title="AMR Research Grant", agency="NIH", source="nih",
                   relevance_score=0.8, deadline=date.today() + timedelta(days=30)),
        make_grant(id="rpt-2", title="AI for Genomics", agency="BARDA", source="grants_gov",
                   relevance_score=0.6),
    ]
    elig_map = {
        grants[0].fingerprint(): "eligible",
        grants[1].fingerprint(): "uncertain",
    }
    reason_map = {
        grants[0].fingerprint(): "IPK is eligible",
        grants[1].fingerprint(): "Not sure",
    }
    stats = {
        "nih": {"success": True, "collected": 50, "filtered": 2},
    }
    run_date = datetime(2026, 3, 17, 10, 0, 0)

    original_dir = rg_mod.REPORTS_DIR
    rg_mod.REPORTS_DIR = tmp_path
    try:
        path = generate_html_report(
            new_grants=grants,
            changed_grants=[],
            all_filtered=grants,
            stats=stats,
            run_date=run_date,
            eligibility_map=elig_map,
            eligibility_reason_map=reason_map,
        )
    finally:
        rg_mod.REPORTS_DIR = original_dir

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Grant Hunter Report" in content
    assert "AMR Research Grant" in content
    assert "AI for Genomics" in content


def test_generate_html_report_stats_included(tmp_path):
    grants = [make_grant(id="s1", title="Stat Grant", source="nih")]
    stats = {"nih": {"success": True, "collected": 100, "filtered": 5}}
    run_date = datetime(2026, 3, 17, 10, 0, 0)

    original_dir = rg_mod.REPORTS_DIR
    rg_mod.REPORTS_DIR = tmp_path
    try:
        path = generate_html_report(
            new_grants=grants,
            changed_grants=[],
            all_filtered=grants,
            stats=stats,
            run_date=run_date,
        )
    finally:
        rg_mod.REPORTS_DIR = original_dir

    content = path.read_text(encoding="utf-8")
    assert "100" in content  # collected count
    assert "nih" in content.lower()


def test_generate_html_report_eligibility_shown(tmp_path):
    g = make_grant(id="e1", title="Elig Report Grant", source="nih")
    elig_map = {g.fingerprint(): "eligible"}
    reason_map = {g.fingerprint(): "Fully meets IPK criteria"}

    original_dir = rg_mod.REPORTS_DIR
    rg_mod.REPORTS_DIR = tmp_path
    try:
        path = generate_html_report(
            new_grants=[g],
            changed_grants=[],
            all_filtered=[g],
            stats={},
            run_date=datetime(2026, 3, 17, 0, 0, 0),
            eligibility_map=elig_map,
            eligibility_reason_map=reason_map,
        )
    finally:
        rg_mod.REPORTS_DIR = original_dir

    content = path.read_text(encoding="utf-8")
    assert "eligible" in content
    assert "Fully meets IPK criteria" in content


def test_generate_html_report_no_grants(tmp_path):
    original_dir = rg_mod.REPORTS_DIR
    rg_mod.REPORTS_DIR = tmp_path
    try:
        path = generate_html_report(
            new_grants=[],
            changed_grants=[],
            all_filtered=[],
            stats={},
            run_date=datetime(2026, 3, 17, 0, 0, 0),
        )
    finally:
        rg_mod.REPORTS_DIR = original_dir

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Grant Hunter Report" in content
