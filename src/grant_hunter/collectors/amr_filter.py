"""AMR+AI dual keyword post-filter for grant collectors."""
from __future__ import annotations

import re
from typing import List

from grant_hunter.models import Grant

# AMR keywords — at least one must match (case-insensitive, whole-word for abbreviations)
AMR_KEYWORDS = [
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

# AI keywords — at least one must match (case-insensitive)
# NOTE: bare "AI" excluded to prevent false positives (NIAID, CHAI, etc.)
AI_KEYWORDS = [
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "neural network",
    "natural language processing",
    "large language model",
    "computational biology",
]


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
