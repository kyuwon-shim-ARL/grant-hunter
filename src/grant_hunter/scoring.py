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

# ── Keyword loading (lazy, reloadable) ───────────────────────────────────────


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


_keywords_cache: Optional[dict] = None


def _get_keywords() -> dict:
    global _keywords_cache
    if _keywords_cache is None:
        _keywords_cache = _load_keywords()
    return _keywords_cache


def _reload_keywords() -> dict:
    global _keywords_cache
    _keywords_cache = _load_keywords()
    return _keywords_cache


def _get_amr_kw() -> List[str]:
    return _flatten(_get_keywords(), "amr")


def _get_ai_kw() -> List[str]:
    return _flatten(_get_keywords(), "ai")


def _get_drug_kw() -> List[str]:
    return _flatten(_get_keywords(), "drug_discovery")


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
        count = len(re.findall(r'\b' + re.escape(phrase_str) + r's?\b', text_str))
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
        if profile is not None:
            self._weights = dict(profile.weights)
        else:
            from grant_hunter.profiles import get_default_profile
            self._weights = dict(get_default_profile().weights)

    def score(self, grant: Grant) -> float:
        """Return relevance score in [0.0, 1.0]."""
        searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"

        amr_s = _keyword_score(searchable, _get_amr_kw())
        ai_s = _keyword_score(searchable, _get_ai_kw())
        drug_s = _keyword_score(searchable, _get_drug_kw())
        amt_s = _amount_bonus(grant)

        kw_total = (
            self._weights["amr"] * amr_s
            + self._weights["ai"] * ai_s
            + self._weights["drug"] * drug_s
        )
        # Block amount-only boosting: no keyword relevance → no score
        if kw_total == 0:
            amt_s = 0.0

        score = kw_total + self._weights["amount"] * amt_s

        return round(min(score, 1.0), 4)

    def score_breakdown(self, grant: Grant) -> Dict[str, float]:
        """Return per-category scores for debugging/display."""
        searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"
        return {
            "amr": round(min(_keyword_score(searchable, _get_amr_kw()), 1.0), 4),
            "ai": round(min(_keyword_score(searchable, _get_ai_kw()), 1.0), 4),
            "drug": round(min(_keyword_score(searchable, _get_drug_kw()), 1.0), 4),
            "amount_bonus": round(min(_amount_bonus(grant), 1.0), 4),
            "total": self.score(grant),
        }


# ── Factory function (lazy load, reloadable) ─────────────────────────────────

_scorer_instance: Optional[RelevanceScorer] = None


def get_scorer(profile: Optional["ResearcherProfile"] = None, reload: bool = False) -> RelevanceScorer:
    """Get a RelevanceScorer instance.

    Args:
        profile: Researcher profile for weight customization. None uses default.
        reload: If True, reload keywords.json and create a fresh instance.

    Returns:
        RelevanceScorer instance.
    """
    global _scorer_instance
    if reload:
        _reload_keywords()
        _scorer_instance = None
    if profile is not None:
        return RelevanceScorer(profile)
    if _scorer_instance is None:
        _scorer_instance = RelevanceScorer()
    return _scorer_instance


def keyword_counts() -> Dict[str, int]:
    """Return current keyword counts per category."""
    return {
        "amr": len(_get_amr_kw()),
        "ai": len(_get_ai_kw()),
        "drug": len(_get_drug_kw()),
    }


def score_grant_normalized(grant: Grant) -> float:
    """Convenience function: return 0.0–1.0 relevance score."""
    return get_scorer().score(grant)
