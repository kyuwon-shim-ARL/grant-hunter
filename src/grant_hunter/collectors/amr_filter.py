"""AMR+AI dual keyword post-filter for grant collectors."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from grant_hunter.models import Grant

_KEYWORDS_FILE = Path(__file__).parent.parent / "data" / "keywords.json"

# Fallback hardcoded defaults (used if keywords.json is missing or malformed)
_DEFAULT_AMR_KEYWORDS = [
    "antimicrobial resistance",
    "antibiotic resistance",
    "antimicrobial resistant",
    "drug-resistant",
    r"\bAMR\b",           # whole-word only
    "ESKAPE",
    "carbapenem",
    r"\bMRSA\b",          # whole-word only
    "multidrug resistant",
    "antibacterial",
]

# NOTE: bare "AI" excluded to prevent false positives (NIAID, CHAI, etc.)
_DEFAULT_AI_KEYWORDS = [
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "neural network",
    "natural language processing",
    "large language model",
    "computational biology",
]


def _load_filter_keywords() -> tuple[List[str], List[str]]:
    """Load precision filter keywords from keywords.json."""
    try:
        with open(_KEYWORDS_FILE, encoding="utf-8") as f:
            kw = json.load(f)
        amr = kw.get("amr_precision_filter", {}).get("en", [])
        ai = kw.get("ai_precision_filter", {}).get("en", [])
        if amr and ai:
            return amr, ai
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # Fallback to hardcoded defaults
    return _DEFAULT_AMR_KEYWORDS, _DEFAULT_AI_KEYWORDS


AMR_KEYWORDS, AI_KEYWORDS = _load_filter_keywords()


def _matches_any(text: str, patterns: List[str]) -> bool:
    """Return True if text matches at least one regex pattern (case-insensitive)."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def is_amr_ai_relevant(grant: Grant) -> bool:
    """Return True if grant contains at least one AMR keyword AND one AI keyword."""
    searchable = " ".join(filter(None, [grant.title, grant.description]))
    return _matches_any(searchable, AMR_KEYWORDS) and _matches_any(searchable, AI_KEYWORDS)


def amr_ai_post_filter(grants: List[Grant]) -> List[Grant]:
    """Filter grants to only those relevant to both AMR and AI topics."""
    return [g for g in grants if is_amr_ai_relevant(g)]
