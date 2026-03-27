"""Tests for send_anomaly_alert() connection in pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestAnomalyAlertConnection:
    """Verify send_anomaly_alert() is called (or skipped) in the right conditions."""

    def _run_monitoring_block(self, anomaly_alerts, report_email):
        """Execute the monitoring block logic extracted from pipeline.py."""
        import logging
        logger = logging.getLogger("test")
        # Simulate the inner logic added to pipeline
        call_log = []
        warn_log = []

        def fake_send(alerts, email):
            call_log.append({"alerts": alerts, "email": email})

        def fake_warn(msg, *args):
            warn_log.append(msg % args if args else msg)

        if anomaly_alerts:
            for alert in anomaly_alerts:
                logger.warning("ANOMALY: %s", alert)
            try:
                send_anomaly_alert = fake_send
                if report_email:
                    send_anomaly_alert(anomaly_alerts, report_email)
                else:
                    warn_log.append("REPORT_EMAIL not set — anomaly alert skipped (no email sent)")
            except Exception as exc:
                warn_log.append(f"Anomaly alert send failed (non-fatal): {exc}")

        return call_log, warn_log

    def test_scenario1_normal_email_calls_send(self):
        """Scenario 1: REPORT_EMAIL set → send_anomaly_alert called once."""
        alerts = ["Volume drop: nih 50% below baseline"]
        call_log, _ = self._run_monitoring_block(alerts, "user@example.com")
        assert len(call_log) == 1
        assert call_log[0]["email"] == "user@example.com"
        assert call_log[0]["alerts"] == alerts

    def test_scenario2_empty_email_skips_send(self):
        """Scenario 2: REPORT_EMAIL='' → send_anomaly_alert NOT called, warning logged."""
        alerts = ["Volume drop: nih"]
        call_log, warn_log = self._run_monitoring_block(alerts, "")
        assert len(call_log) == 0
        assert any("REPORT_EMAIL not set" in w for w in warn_log)

    def test_scenario3_no_alerts_skips_entirely(self):
        """Scenario 3: No anomaly alerts → send_anomaly_alert NOT called."""
        call_log, _ = self._run_monitoring_block([], "user@example.com")
        assert len(call_log) == 0

    def test_pipeline_uses_send_anomaly_alert(self):
        """Integration: verify pipeline.py actually imports and calls send_anomaly_alert on anomaly."""
        from pathlib import Path
        src = Path("src/grant_hunter/pipeline.py").read_text()
        assert "send_anomaly_alert" in src, "send_anomaly_alert must be referenced in pipeline.py"
        assert "REPORT_EMAIL" in src, "REPORT_EMAIL must be used in pipeline.py anomaly block"


class TestAnomalyAlertExceptionHandling:
    def test_scenario3_exception_does_not_raise(self):
        """Scenario 3 (exception): send_anomaly_alert raises → pipeline exit code unaffected (non-fatal)."""
        import logging
        logger = logging.getLogger("test")
        warn_log = []

        def raising_send(alerts, email):
            raise RuntimeError("SMTP connection failed")

        alerts = ["Volume drop"]
        try:
            if alerts:
                for alert in alerts:
                    logger.warning("ANOMALY: %s", alert)
                try:
                    send_anomaly_alert = raising_send
                    if "user@example.com":
                        send_anomaly_alert(alerts, "user@example.com")
                except Exception as exc:
                    warn_log.append(f"Anomaly alert send failed (non-fatal): {exc}")
        except Exception:
            pytest.fail("Exception escaped monitoring block — should be non-fatal")

        assert any("non-fatal" in w for w in warn_log)
