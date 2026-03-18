"""Integration tests for run_pipeline() end-to-end chain.

Covers:
1. Full collect → filter → score → report chain with mocked collectors.
2. Partial collector failure: pipeline completes despite one collector error.
3. First-run email skip: email is not sent when no previous snapshot exists.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_grant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _amr_ai_grant(id: str, source: str, agency: str) -> object:
    """Return a Grant that passes the AMR+AI keyword gate."""
    return make_grant(
        id=id,
        title="Machine learning approaches to antimicrobial resistance",
        agency=agency,
        source=source,
        url=f"https://example.com/{id}",
        description=(
            "This grant funds artificial intelligence and deep learning research "
            "on antimicrobial resistance and antibiotic resistance drug discovery. "
            "The project applies neural networks to identify novel drug targets against "
            "drug-resistant bacteria and AMR pathogens."
        ),
        deadline=date(2027, 6, 30),
        amount_min=500_000.0,
        amount_max=2_000_000.0,
        duration_months=36,
    )


def _patch_config_dirs(tmp_path: Path):
    """Return a dict of patch targets that redirect all config paths to tmp_path."""
    snapshots = tmp_path / "snapshots"
    reports = tmp_path / "reports"
    logs = tmp_path / "logs"
    run_history = tmp_path / "run_history.json"

    for d in (snapshots, reports, logs):
        d.mkdir(parents=True, exist_ok=True)

    return {
        "grant_hunter.pipeline.SNAPSHOTS_DIR": snapshots,
        "grant_hunter.pipeline.LOGS_DIR": logs,
        "grant_hunter.pipeline.RUN_HISTORY_FILE": run_history,
        "grant_hunter.collectors.base.SNAPSHOTS_DIR": snapshots,
        "grant_hunter.config.SNAPSHOTS_DIR": snapshots,
        "grant_hunter.config.REPORTS_DIR": reports,
        "grant_hunter.config.LOGS_DIR": logs,
        "grant_hunter.config.RUN_HISTORY_FILE": run_history,
    }


# ---------------------------------------------------------------------------
# Test 1: full collect → filter → score → report chain
# ---------------------------------------------------------------------------

class TestPipelineCollectFilterScoreChain:
    """run_pipeline() correctly chains collect, filter, eligibility, and report."""

    def test_pipeline_collect_filter_score_chain(self, tmp_path):
        """Pipeline produces filtered grants, computes eligibility, and generates a report."""
        nih_grants = [_amr_ai_grant("NIH-001", "nih", "NIH")]
        eu_grants = [_amr_ai_grant("EU-001", "eu", "EU Commission")]
        gg_grants = [_amr_ai_grant("GG-001", "grants_gov", "NSF")]

        mock_nih = MagicMock()
        mock_nih.name = "nih"
        mock_nih.collect.return_value = nih_grants
        mock_nih.has_previous_snapshot.return_value = True
        mock_nih.load_previous_snapshot.return_value = []
        mock_nih.save_snapshot.return_value = tmp_path / "snapshots" / "nih_20260318.json"

        mock_eu = MagicMock()
        mock_eu.name = "eu"
        mock_eu.collect.return_value = eu_grants
        mock_eu.has_previous_snapshot.return_value = True
        mock_eu.load_previous_snapshot.return_value = []
        mock_eu.save_snapshot.return_value = tmp_path / "snapshots" / "eu_20260318.json"

        mock_gg = MagicMock()
        mock_gg.name = "grants_gov"
        mock_gg.collect.return_value = gg_grants
        mock_gg.has_previous_snapshot.return_value = True
        mock_gg.load_previous_snapshot.return_value = []
        mock_gg.save_snapshot.return_value = tmp_path / "snapshots" / "grants_gov_20260318.json"

        config_patches = _patch_config_dirs(tmp_path)

        with patch("grant_hunter.pipeline.NIHCollector", return_value=mock_nih), \
             patch("grant_hunter.pipeline.EUPortalCollector", return_value=mock_eu), \
             patch("grant_hunter.pipeline.GrantsGovCollector", return_value=mock_gg), \
             patch("grant_hunter.pipeline._send_email_report", return_value=True), \
             patch("grant_hunter.pipeline.generate_html_report", return_value=tmp_path / "reports" / "report.html"), \
             patch("grant_hunter.pipeline.generate_dashboard", return_value=tmp_path / "reports" / "dashboard.html"), \
             patch("grant_hunter.pipeline.SNAPSHOTS_DIR", config_patches["grant_hunter.pipeline.SNAPSHOTS_DIR"]), \
             patch("grant_hunter.pipeline.LOGS_DIR", config_patches["grant_hunter.pipeline.LOGS_DIR"]):

            from grant_hunter.pipeline import run_pipeline
            summary = run_pipeline()

        # Pipeline should complete and return a dict with all expected keys
        assert isinstance(summary, dict)
        expected_keys = {
            "run_at", "total_collected", "after_dedup", "filtered",
            "eligible", "uncertain", "ineligible", "new", "changed",
            "email_sent", "report_path", "dashboard_path", "sources",
            "validation_passed", "validation_rejected",
        }
        assert expected_keys.issubset(summary.keys())

        # At least some grants should survive filtering (they carry AMR+AI keywords)
        assert summary["filtered"] > 0, "Expected AMR+AI grants to pass the keyword filter"

        # Eligibility should have been computed (eligible + uncertain + ineligible == filtered)
        total_elig = summary["eligible"] + summary["uncertain"] + summary["ineligible"]
        assert total_elig == summary["filtered"], (
            f"Eligibility totals {total_elig} != filtered {summary['filtered']}"
        )

        # Report path should be set
        assert summary["report_path"] != ""

        # Per-source stats must be present
        for source_name in ("nih", "eu", "grants_gov"):
            assert source_name in summary["sources"], f"Missing stats for {source_name}"
            assert summary["sources"][source_name]["success"] is True


# ---------------------------------------------------------------------------
# Test 2: partial collector failure
# ---------------------------------------------------------------------------

class TestPipelinePartialCollectorFailure:
    """Pipeline completes even when one collector raises an exception."""

    def test_pipeline_partial_collector_failure(self, tmp_path):
        """NIH collector failure is recorded in stats; EU and GrantsGov still succeed."""
        eu_grants = [_amr_ai_grant("EU-002", "eu", "EU Commission")]
        gg_grants = [_amr_ai_grant("GG-002", "grants_gov", "NSF")]

        mock_nih = MagicMock()
        mock_nih.name = "nih"
        mock_nih.collect.side_effect = RuntimeError("NIH API unavailable")
        mock_nih.has_previous_snapshot.return_value = True
        mock_nih.load_previous_snapshot.return_value = []
        mock_nih.save_snapshot.return_value = tmp_path / "snapshots" / "nih_fail.json"

        mock_eu = MagicMock()
        mock_eu.name = "eu"
        mock_eu.collect.return_value = eu_grants
        mock_eu.has_previous_snapshot.return_value = True
        mock_eu.load_previous_snapshot.return_value = []
        mock_eu.save_snapshot.return_value = tmp_path / "snapshots" / "eu_20260318.json"

        mock_gg = MagicMock()
        mock_gg.name = "grants_gov"
        mock_gg.collect.return_value = gg_grants
        mock_gg.has_previous_snapshot.return_value = True
        mock_gg.load_previous_snapshot.return_value = []
        mock_gg.save_snapshot.return_value = tmp_path / "snapshots" / "grants_gov_20260318.json"

        config_patches = _patch_config_dirs(tmp_path)

        with patch("grant_hunter.pipeline.NIHCollector", return_value=mock_nih), \
             patch("grant_hunter.pipeline.EUPortalCollector", return_value=mock_eu), \
             patch("grant_hunter.pipeline.GrantsGovCollector", return_value=mock_gg), \
             patch("grant_hunter.pipeline._send_email_report", return_value=True), \
             patch("grant_hunter.pipeline.generate_html_report", return_value=tmp_path / "reports" / "report.html"), \
             patch("grant_hunter.pipeline.generate_dashboard", return_value=tmp_path / "reports" / "dashboard.html"), \
             patch("grant_hunter.pipeline.SNAPSHOTS_DIR", config_patches["grant_hunter.pipeline.SNAPSHOTS_DIR"]), \
             patch("grant_hunter.pipeline.LOGS_DIR", config_patches["grant_hunter.pipeline.LOGS_DIR"]):

            from grant_hunter.pipeline import run_pipeline
            summary = run_pipeline()

        # Pipeline must not raise and must return a summary
        assert isinstance(summary, dict)

        # NIH stats should reflect failure
        nih_stats = summary["sources"]["nih"]
        assert nih_stats["success"] is False, "NIH should be marked as failed"
        assert nih_stats["collected"] == 0

        # EU and GrantsGov should have succeeded
        assert summary["sources"]["eu"]["success"] is True
        assert summary["sources"]["eu"]["collected"] == 1

        assert summary["sources"]["grants_gov"]["success"] is True
        assert summary["sources"]["grants_gov"]["collected"] == 1

        # Total collected reflects only the two successful sources
        assert summary["total_collected"] == 2


# ---------------------------------------------------------------------------
# Test 3: skip email on first run
# ---------------------------------------------------------------------------

class TestPipelineSkipEmailFirstRun:
    """Email is not sent when all collectors report no previous snapshot."""

    def test_pipeline_skip_email_first_run(self, tmp_path):
        """email_sent is False in summary when SKIP_EMAIL_ON_FIRST_RUN is True and no prior snapshot."""
        # All three collectors return grants so no anomaly alerts are triggered
        nih_grants = [_amr_ai_grant("NIH-003", "nih", "NIH")]
        eu_grants = [_amr_ai_grant("EU-003", "eu", "EU Commission")]
        gg_grants = [_amr_ai_grant("GG-003", "grants_gov", "NSF")]

        mock_nih = MagicMock()
        mock_nih.name = "nih"
        mock_nih.collect.return_value = nih_grants
        mock_nih.has_previous_snapshot.return_value = False  # first run
        mock_nih.load_previous_snapshot.return_value = []
        mock_nih.save_snapshot.return_value = tmp_path / "snapshots" / "nih_20260318.json"

        mock_eu = MagicMock()
        mock_eu.name = "eu"
        mock_eu.collect.return_value = eu_grants
        mock_eu.has_previous_snapshot.return_value = False  # first run
        mock_eu.load_previous_snapshot.return_value = []
        mock_eu.save_snapshot.return_value = tmp_path / "snapshots" / "eu_20260318.json"

        mock_gg = MagicMock()
        mock_gg.name = "grants_gov"
        mock_gg.collect.return_value = gg_grants
        mock_gg.has_previous_snapshot.return_value = False  # first run
        mock_gg.load_previous_snapshot.return_value = []
        mock_gg.save_snapshot.return_value = tmp_path / "snapshots" / "grants_gov_20260318.json"

        config_patches = _patch_config_dirs(tmp_path)

        with patch("grant_hunter.pipeline.NIHCollector", return_value=mock_nih), \
             patch("grant_hunter.pipeline.EUPortalCollector", return_value=mock_eu), \
             patch("grant_hunter.pipeline.GrantsGovCollector", return_value=mock_gg), \
             patch("grant_hunter.pipeline._send_email_report") as mock_send_email, \
             patch("grant_hunter.pipeline.generate_html_report", return_value=tmp_path / "reports" / "report.html"), \
             patch("grant_hunter.pipeline.generate_dashboard", return_value=tmp_path / "reports" / "dashboard.html"), \
             patch("grant_hunter.pipeline.SKIP_EMAIL_ON_FIRST_RUN", True), \
             patch("grant_hunter.pipeline.SNAPSHOTS_DIR", config_patches["grant_hunter.pipeline.SNAPSHOTS_DIR"]), \
             patch("grant_hunter.pipeline.LOGS_DIR", config_patches["grant_hunter.pipeline.LOGS_DIR"]):

            from grant_hunter.pipeline import run_pipeline
            summary = run_pipeline()

        # Pipeline must complete without error
        assert isinstance(summary, dict)

        # Email must NOT have been sent on first run
        assert summary["email_sent"] is False, (
            "Email should be skipped on first run when SKIP_EMAIL_ON_FIRST_RUN=True"
        )

        # _send_email_report must not have been called at all
        mock_send_email.assert_not_called()

        # Pipeline should still produce a report path
        assert summary["report_path"] != ""
