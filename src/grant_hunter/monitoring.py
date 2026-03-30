"""Pipeline run history and volume anomaly detection."""
import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def save_run_history(summary: dict, history_file: Path) -> None:
    """Append pipeline run summary to JSON history file."""
    history = load_run_history(history_file)
    entry = {
        "run_at": summary.get("run_at", datetime.utcnow().isoformat()),
        "total_collected": summary.get("total_collected", 0),
        "filtered": summary.get("filtered", 0),
        "eligible": summary.get("eligible", 0),
        "sources": {
            src: {"collected": info.get("collected", 0), "success": info.get("success", False)}
            for src, info in summary.get("sources", {}).items()
        },
    }
    history.append(entry)
    history = history[-90:]  # Keep last 90 runs

    # Atomic write
    history_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=history_file.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, default=str)
        os.replace(tmp_path, str(history_file))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_run_history(history_file: Path) -> list:
    """Load run history from JSON file."""
    if history_file.exists():
        try:
            return json.loads(history_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def check_volume_anomaly(summary: dict, history_file: Path) -> list[str]:
    """Check for volume anomalies against recent history.

    Returns list of alert messages (empty = no anomalies).

    Anomaly rules:
    1. Any source collected 0 grants (and was previously successful)
    2. Total collected dropped >50% vs average of last 7 runs
    3. Any source failed (success=False)
    """
    alerts = []
    history = load_run_history(history_file)

    # Rule 1 & 3: Per-source checks
    for src, info in summary.get("sources", {}).items():
        if info.get("collected", 0) == 0 and info.get("success", False):
            alerts.append(f"ZERO_COLLECT: {src} collected 0 grants")
        if not info.get("success", True):
            alerts.append(f"SOURCE_FAIL: {src} failed: {info.get('error', 'unknown')}")

    # Rule 2: Volume drop vs 7-day average
    if len(history) >= 3:
        recent = history[-7:] if len(history) >= 7 else history
        avg_collected = sum(r.get("total_collected", 0) for r in recent) / len(recent)
        current = summary.get("total_collected", 0)
        if avg_collected > 0 and current < avg_collected * 0.5:
            alerts.append(
                f"VOLUME_DROP: collected {current} vs 7-day avg {avg_collected:.0f} "
                f"({current / avg_collected * 100:.0f}% of average)"
            )

    return alerts


def send_anomaly_alert(alerts: list[str], email: str, history_file: Path = None) -> bool:
    """Send anomaly alert email. Returns True if email was sent successfully.

    If history_file is provided, records alert_sent_at in the latest run entry.
    """
    if not alerts:
        return False
    subject = f"[Grant Hunter ALERT] {len(alerts)} anomalies detected"
    body = "Pipeline volume anomalies detected:\n\n" + "\n".join(f"- {a}" for a in alerts)
    try:
        result = subprocess.run(
            ["send-email", email, subject, body],
            capture_output=True,
            text=True,
            timeout=30,
        )
        sent = result.returncode == 0
        if sent and history_file is not None:
            _record_alert_timestamp(history_file)
        return sent
    except (FileNotFoundError, Exception) as e:
        logger.warning("Could not send alert email: %s", e)
        return False


def _record_alert_timestamp(history_file: Path) -> None:
    """Add alert_sent_at to the latest entry in run_history."""
    history = load_run_history(history_file)
    if not history:
        return
    history[-1]["alert_sent_at"] = datetime.utcnow().isoformat()
    # Atomic write (same pattern as save_run_history)
    history_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=history_file.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, default=str)
        os.replace(tmp_path, str(history_file))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
