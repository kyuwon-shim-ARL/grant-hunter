"""Relevance scoring module using TF-IDF-style keyword weighting.

Scores a Grant on a 0.0–1.0 scale based on keyword presence in
title + description, weighted by category importance to IPK.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Dict, List, Tuple

from models import Grant

# ── Keyword loading ───────────────────────────────────────────────────────────

_KEYWORDS_FILE = Path(__file__).parent / "data" / "keywords.json"


def _load_keywords() -> dict:
    if _KEYWORDS_FILE.exists():
        with open(_KEYWORDS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _flatten(kw: dict, category: str) -> List[str]:
    cat = kw.get(category, {})
    words: List[str] = []
    for lang_list in cat.values():
        words.extend(lang_list)
    return words


_KW = _load_keywords()
_AMR_KW: List[str] = _flatten(_KW, "amr")
_AI_KW: List[str] = _flatten(_KW, "ai")
_DRUG_KW: List[str] = _flatten(_KW, "drug_discovery")

# Category weights must sum to 1.0 (amount bonus is additive after)
_WEIGHTS = {
    "amr": 0.4,
    "ai": 0.3,
    "drug": 0.2,
    "amount": 0.1,
}

# Amount thresholds for bonus (USD)
_AMOUNT_TIERS = [
    (10_000_000, 1.0),   # $10M+
    (5_000_000, 0.8),    # $5M+
    (1_000_000, 0.6),    # $1M+
    (500_000, 0.4),      # $500K+
    (100_000, 0.2),      # $100K+
    (0, 0.05),           # any amount
]


# ── TF-IDF helpers ────────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    return re.findall(r"\b\w+\b", text.lower())


def _tf(tokens: List[str], phrase: str) -> float:
    """Term frequency for a keyword phrase in a token list."""
    phrase_tokens = re.findall(r"\b\w+\b", phrase.lower())
    if not phrase_tokens:
        return 0.0
    n = len(tokens)
    if n == 0:
        return 0.0
    # Count non-overlapping phrase occurrences
    phrase_str = " ".join(phrase_tokens)
    text_str = " ".join(tokens)
    count = len(re.findall(re.escape(phrase_str), text_str))
    return count / n


def _keyword_score(text: str, keywords: List[str]) -> float:
    """Return a normalised [0,1] score for keyword coverage.

    Combines:
    - breadth: fraction of distinct keywords matched
    - depth: log-scaled TF sum (more occurrences help, with diminishing returns)
    """
    if not keywords or not text:
        return 0.0

    tokens = _tokenize(text)
    matched_kw = []
    tf_sum = 0.0
    for kw in keywords:
        tf_val = _tf(tokens, kw)
        if tf_val > 0:
            matched_kw.append(kw)
            tf_sum += tf_val

    if not matched_kw:
        return 0.0

    breadth = len(matched_kw) / len(keywords)
    depth = math.log1p(tf_sum * 100) / math.log1p(100)  # normalised 0–1

    return 0.6 * breadth + 0.4 * depth


def _amount_bonus(grant: Grant) -> float:
    """Return a [0,1] bonus based on funding amount."""
    amount = grant.amount_max or grant.amount_min
    if amount is None:
        return 0.1  # neutral; unknown amount
    for threshold, score in _AMOUNT_TIERS:
        if amount >= threshold:
            return score
    return 0.0


# ── Public interface ──────────────────────────────────────────────────────────

class RelevanceScorer:
    """Score a Grant on 0.0–1.0 relevance to IPK's AMR+AI research focus."""

    def score(self, grant: Grant) -> float:
        """Return relevance score in [0.0, 1.0]."""
        searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"

        amr_s = _keyword_score(searchable, _AMR_KW)
        ai_s = _keyword_score(searchable, _AI_KW)
        drug_s = _keyword_score(searchable, _DRUG_KW)
        amt_s = _amount_bonus(grant)

        score = (
            _WEIGHTS["amr"] * amr_s
            + _WEIGHTS["ai"] * ai_s
            + _WEIGHTS["drug"] * drug_s
            + _WEIGHTS["amount"] * amt_s
        )

        return round(min(score, 1.0), 4)

    def score_breakdown(self, grant: Grant) -> Dict[str, float]:
        """Return per-category scores for debugging/display."""
        searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"
        return {
            "amr": round(_keyword_score(searchable, _AMR_KW), 4),
            "ai": round(_keyword_score(searchable, _AI_KW), 4),
            "drug": round(_keyword_score(searchable, _DRUG_KW), 4),
            "amount_bonus": round(_amount_bonus(grant), 4),
            "total": self.score(grant),
        }


# Module-level singleton for convenience
_scorer = RelevanceScorer()


def score_grant_normalized(grant: Grant) -> float:
    """Convenience function: return 0.0–1.0 relevance score."""
    return _scorer.score(grant)
