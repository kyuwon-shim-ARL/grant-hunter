"""Keyword matching and relevance filtering for grants."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Tuple

from grant_hunter.config import KEYWORDS_FILE, MIN_AMR_HITS, MIN_AI_HITS
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)


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


def score_grant(grant: Grant) -> float:
    """Compute relevance score; returns 0.0 if below threshold."""
    searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"

    amr_hits, amr_matched = _count_hits(searchable, AMR_KEYWORDS)
    ai_hits, ai_matched = _count_hits(searchable, AI_KEYWORDS)
    drug_hits, _ = _count_hits(searchable, DRUG_KEYWORDS)

    # Must pass minimum threshold
    if amr_hits < MIN_AMR_HITS or ai_hits < MIN_AI_HITS:
        return 0.0

    # Weighted score: AMR=3, AI=2, drug=1
    score = amr_hits * 3.0 + ai_hits * 2.0 + drug_hits * 1.0

    logger.debug(
        "PASS '%s' score=%.1f amr=%d(%s) ai=%d(%s)",
        grant.title[:60],
        score,
        amr_hits,
        amr_matched[:3],
        ai_hits,
        ai_matched[:3],
    )
    return score


def filter_grants(grants: List[Grant]) -> List[Grant]:
    """Return only grants that pass AMR+AI keyword filter, sorted by relevance."""
    scored: List[Tuple[float, Grant]] = []
    for grant in grants:
        s = score_grant(grant)
        if s > 0:
            grant.relevance_score = s
            scored.append((s, grant))

    scored.sort(key=lambda x: x[0], reverse=True)
    result = [g for _, g in scored]
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
