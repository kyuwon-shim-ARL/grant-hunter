"""Smoke test for run_pipeline() - mocks all HTTP calls."""

import pytest
from unittest.mock import patch, MagicMock


def _make_mock_response(json_data, status_code=200):
    """Create a mock requests.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.text = ""
    mock_resp.raise_for_status.return_value = None
    return mock_resp


@patch("requests.get")
@patch("requests.post")
def test_run_pipeline_completes_without_exception(mock_post, mock_get, tmp_path):
    """Pipeline should complete without raising, even with empty HTTP responses."""
    # NIH POST returns empty results
    nih_response = _make_mock_response({
        "results": [],
        "meta": {"total": 0},
    })
    # Grants.gov POST returns empty results
    grants_gov_response = _make_mock_response({
        "data": {"oppHits": [], "hitCount": 0},
    })
    mock_post.return_value = nih_response

    # EU CORDIS GET returns empty
    eu_response = _make_mock_response({
        "payload": {"results": [], "total": 0},
    })

    def get_side_effect(url, **kwargs):
        return eu_response

    def post_side_effect(url, **kwargs):
        if "grants.gov" in url:
            return grants_gov_response
        return nih_response

    mock_get.side_effect = get_side_effect
    mock_post.side_effect = post_side_effect

    with patch("grant_hunter.config.RUN_HISTORY_FILE", tmp_path / "run_history.json"):
        from grant_hunter.pipeline import run_pipeline
        summary = run_pipeline()

    assert isinstance(summary, dict)
    expected_keys = {
        "run_at", "total_collected", "after_dedup", "filtered",
        "eligible", "uncertain", "ineligible", "new", "changed",
        "email_sent", "report_path", "dashboard_path", "sources",
    }
    assert expected_keys.issubset(summary.keys())
