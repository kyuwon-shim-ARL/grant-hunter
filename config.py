"""Configuration for grant_hunter pipeline."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"
KEYWORDS_FILE = DATA_DIR / "keywords.json"

# Email
REPORT_EMAIL = os.environ.get("GRANT_REPORT_EMAIL", "kyuwon.song@ip-korea.org")

# Pipeline behaviour
# On first run (no previous snapshot) just save baseline, do not send email
SKIP_EMAIL_ON_FIRST_RUN = True

# Relevance thresholds
# A grant must match ≥1 AMR keyword AND ≥1 AI keyword to pass the filter
MIN_AMR_HITS = 1
MIN_AI_HITS = 1

# Deadline warning window (days)
DEADLINE_WARN_DAYS = 7

# API settings
NIH_API_URL = "https://api.reporter.nih.gov/v2/projects/search"
NIH_PAGE_SIZE = 500
NIH_MAX_PAGES = 4

GRANTS_GOV_API_URL = "https://apply07.grants.gov/grantsws/rest/opportunities/search"
GRANTS_GOV_PAGE_SIZE = 25
GRANTS_GOV_MAX_PAGES = 4

REQUEST_TIMEOUT = 30  # seconds
