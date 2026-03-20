"""Configuration for grant_hunter pipeline."""

import os
from pathlib import Path

# Data directory: <project>/data/ by default, overridable via env var
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_HOME = Path(os.environ.get("GRANT_HUNTER_DATA_DIR", _PROJECT_ROOT / "data"))

# Package data (shipped with package)
_PKG_DIR = Path(__file__).parent
KEYWORDS_FILE = _PKG_DIR / "data" / "keywords.json"

# User data (runtime, created on demand)
SNAPSHOTS_DIR = DATA_HOME / "snapshots"
REPORTS_DIR = DATA_HOME / "reports"
LOGS_DIR = DATA_HOME / "logs"
CONFIG_FILE = DATA_HOME / "config.json"
RUN_HISTORY_FILE = DATA_HOME / "run_history.json"

def init_data_dirs():
    """Create runtime data directories on demand."""
    for d in [SNAPSHOTS_DIR, REPORTS_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

# Email
REPORT_EMAIL = os.environ.get("GRANT_REPORT_EMAIL", "kyuwon.shim@ip-korea.org")

# Pipeline behaviour
# On first run (no previous snapshot) just save baseline, do not send email
SKIP_EMAIL_ON_FIRST_RUN = True

# Relevance thresholds
# A grant must match >=1 AMR keyword AND >=1 AI keyword to pass the filter
MIN_AMR_HITS = 1
MIN_AI_HITS = 1

# Deadline warning window (days)
DEADLINE_WARN_DAYS = 7

# API settings
GRANTS_GOV_API_URL = "https://api.grants.gov/v1/api/search2"
GRANTS_GOV_PAGE_SIZE = 25
GRANTS_GOV_MAX_PAGES = 4

REQUEST_TIMEOUT = 30  # seconds
NIH_COLLECTOR_TIMEOUT = int(os.environ.get("NIH_COLLECTOR_TIMEOUT", "1800"))
GRANT_HUNTER_PROFILE = os.environ.get("GRANT_HUNTER_PROFILE", "default")
