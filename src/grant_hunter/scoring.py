"""Relevance scoring module using TF-IDF-style keyword weighting.

Scores a Grant on a 0.0–1.0 scale based on keyword presence in
title + description, weighted by category importance to IPK.
"""

from __future__ import annotations

import json
import math
import re
from typing import TYPE_CHECKING, Dict, List, Optional

from grant_hunter.config import KEYWORDS_FILE
from grant_hunter.models import Grant

if TYPE_CHECKING:
    from grant_hunter.profiles import ResearcherProfile

# ── Keyword loading ───────────────────────────────────────────────────────────


def _load_keywords() -> dict:
    if KEYWORDS_FILE.exists():
        with open(KEYWORDS_FILE, encoding="utf-8") as fh:
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

# Category weights must sum to 1.0
_WEIGHTS = {
    "amr": 0.40,
    "ai": 0.30,
    "drug": 0.20,
    "amount": 0.10,
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
    """Term frequency for a keyword phrase in a token list.

    For single-token phrases of 2 characters or fewer, require exact token
    match to avoid false positives (e.g. 'AI' matching inside 'training').
    """
    phrase_tokens = re.findall(r"\b\w+\b", phrase.lower())
    if not phrase_tokens or not tokens:
        return 0.0
    n = len(tokens)
    # For short single-token keywords, require exact token match
    if len(phrase_tokens) == 1 and len(phrase_tokens[0]) <= 2:
        count = tokens.count(phrase_tokens[0])
    else:
        phrase_str = " ".join(phrase_tokens)
        text_str = " ".join(tokens)
        count = len(re.findall(re.escape(phrase_str), text_str))
    # Log-normalized TF: dampens both raw count and document length
    return math.log1p(count) / math.log1p(n)


def _keyword_score(text: str, keywords: List[str]) -> float:
    """Return a normalised [0,1] score for keyword coverage.

    Combines:
    - breadth: sqrt-normalised fraction of distinct keywords matched
      (capped at 10 keywords so matching 3 out of 50 still gives reasonable score)
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

    # Use sqrt normalization: cap denominator at 10 so 3 matches = 0.3 breadth
    # instead of 3/50 = 0.06 with the old formula
    breadth = min(1.0, len(matched_kw) / max(1, min(len(keywords), 10)))
    depth = math.log1p(tf_sum * 100) / math.log1p(100)  # normalised 0–1

    return 0.5 * breadth + 0.5 * depth


def _amount_bonus(grant: Grant) -> float:
    """Return a [0,1] bonus based on funding amount.

    Returns 0.0 for unknown amounts (no free bonus for missing data).
    """
    amount = grant.amount_max or grant.amount_min
    if amount is None:
        return 0.0  # no bonus for unknown amount
    for threshold, score in _AMOUNT_TIERS:
        if amount >= threshold:
            return score
    return 0.0


# ── Public interface ──────────────────────────────────────────────────────────

class RelevanceScorer:
    """Score a Grant on 0.0–1.0 relevance to IPK's AMR+AI research focus."""

    def __init__(self, profile: Optional["ResearcherProfile"] = None) -> None:
        self._weights = dict(_WEIGHTS)
        if profile is not None:
            self._weights = dict(profile.weights)

    def score(self, grant: Grant) -> float:
        """Return relevance score in [0.0, 1.0]."""
        searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"

        amr_s = _keyword_score(searchable, _AMR_KW)
        ai_s = _keyword_score(searchable, _AI_KW)
        drug_s = _keyword_score(searchable, _DRUG_KW)
        amt_s = _amount_bonus(grant)

        score = (
            self._weights["amr"] * amr_s
            + self._weights["ai"] * ai_s
            + self._weights["drug"] * drug_s
            + self._weights["amount"] * amt_s
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
