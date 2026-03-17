"""Keyword matching and relevance filtering for grants."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Tuple

from grant_hunter.config import KEYWORDS_FILE, MIN_AMR_HITS, MIN_AI_HITS
from grant_hunter.models import Grant
from grant_hunter.scoring import RelevanceScorer

logger = logging.getLogger(__name__)

_scorer = RelevanceScorer()


def _load_keywords() -> dict:
    if KEYWORDS_FILE.exists():
        with open(KEYWORDS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


_KEYWORDS = _load_keywords()


def _flatten(category: str) -> List[str]:
    cat = _KEYWORDS.get(category, {})
    words = []
    for lang_list in cat.values():
        words.extend(lang_list)
    return words


AMR_KEYWORDS: List[str] = _flatten("amr")
AI_KEYWORDS: List[str] = _flatten("ai")
DRUG_KEYWORDS: List[str] = _flatten("drug_discovery")


def _count_hits(text: str, keywords: List[str]) -> Tuple[int, List[str]]:
    """Return (hit_count, matched_keywords) for case-insensitive whole-word search."""
    text_lower = text.lower()
    matched = []
    for kw in keywords:
        pattern = r'\b' + re.escape(kw.lower()) + r'\b'
        if re.search(pattern, text_lower):
            matched.append(kw)
    return len(matched), matched


def passes_keyword_gate(grant: Grant) -> bool:
    """Check if grant passes the AMR AND AI keyword threshold."""
    searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"
    amr_hits, _ = _count_hits(searchable, AMR_KEYWORDS)
    ai_hits, _ = _count_hits(searchable, AI_KEYWORDS)
    return amr_hits >= MIN_AMR_HITS and ai_hits >= MIN_AI_HITS


def filter_grants(grants: List[Grant]) -> List[Grant]:
    """Return only grants that pass AMR+AI keyword filter, scored by RelevanceScorer.

    Uses the unified RelevanceScorer (0.0–1.0 normalized) for scoring.
    Gate: grant must contain at least MIN_AMR_HITS AMR keywords AND
    MIN_AI_HITS AI keywords.
    """
    result: List[Grant] = []
    for grant in grants:
        if not passes_keyword_gate(grant):
            continue
        grant.relevance_score = _scorer.score(grant)
        result.append(grant)

    result.sort(key=lambda g: g.relevance_score, reverse=True)
    logger.info(
        "Filter: %d/%d grants passed (AMR>=%d AND AI>=%d)",
        len(result),
        len(grants),
        MIN_AMR_HITS,
        MIN_AI_HITS,
    )
    return result


def diff_grants(
    current: List[Grant], previous: List[Grant]
) -> Tuple[List[Grant], List[Grant]]:
    """Return (new_grants, changed_grants) compared to previous snapshot."""
    prev_map = {g.fingerprint(): g for g in previous}
    new_grants: List[Grant] = []
    changed_grants: List[Grant] = []

    for g in current:
        fp = g.fingerprint()
        if fp not in prev_map:
            new_grants.append(g)
        else:
            old = prev_map[fp]
            if g.title != old.title or g.deadline != old.deadline or g.amount_max != old.amount_max:
                changed_grants.append(g)

    return new_grants, changed_grants
