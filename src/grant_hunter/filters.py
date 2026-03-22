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

# Core AMR keywords that are highly specific to antimicrobial resistance
# (vs broad terms like "surveillance" that appear in many contexts)
AMR_CORE_KEYWORDS: List[str] = [
    kw for kw in AMR_KEYWORDS
    if kw.lower() in {
        "antimicrobial resistance", "antibiotic resistance", "drug-resistant",
        "amr", "multidrug-resistant", "mdr", "xdr", "mrsa", "eskape",
        "resistant pathogen", "resistant bacteria", "antibiotic stewardship",
        "antimicrobial stewardship", "beta-lactamase", "esbl",
        "extended-spectrum beta-lactamase", "carbapenemase", "ndm-1",
        "oxa-48", "kpc", "vim", "imp", "ctx-m", "bacteriophage",
        "phage therapy", "antimicrobial peptide", "resistance gene",
        "resistome", "colistin", "carbapenem", "polymyxin",
        # Expanded: clinically specific AMR terms (v2.7)
        "sepsis", "bacteremia", "nosocomial", "gram-negative", "gram-positive",
        "항생제 내성", "항균제 내성", "다제내성", "슈퍼박테리아", "내성균",
        "카바페넴 내성", "내성유전자",
    }
]


def _count_hits(text: str, keywords: List[str]) -> Tuple[int, List[str]]:
    """Return (hit_count, matched_keywords) for case-insensitive whole-word search."""
    text_lower = text.lower()
    matched = []
    for kw in keywords:
        pattern = r'\b' + re.escape(kw.lower()) + r's?\b'
        if re.search(pattern, text_lower):
            matched.append(kw)
    return len(matched), matched


def passes_keyword_gate(grant: Grant) -> str:
    """Check grant against AMR/AI keyword thresholds.

    Returns:
        "tier1" - AMR AND AI (both present)
        "tier2" - AMR-only (core AMR keyword, no AI)
        "skip"  - neither criterion met
    """
    searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"
    amr_hits, _ = _count_hits(searchable, AMR_KEYWORDS)
    amr_core_hits, _ = _count_hits(searchable, AMR_CORE_KEYWORDS)
    ai_hits, _ = _count_hits(searchable, AI_KEYWORDS)

    amr_pass = amr_core_hits >= MIN_AMR_HITS or amr_hits >= 2
    ai_pass = ai_hits >= MIN_AI_HITS

    if amr_pass and ai_pass:
        return "tier1"
    if amr_core_hits >= 1:
        return "tier2"
    return "skip"


def score_and_rank_grants(grants: List[Grant], profile=None) -> List[Grant]:
    """Score all grants and return sorted by relevance (descending).

    Every grant receives a relevance score (0.0–1.0) based on keyword
    matching across AMR, AI, drug-discovery, and funding-amount axes.
    No binary gate — users judge from the ranked list.
    """
    scorer = RelevanceScorer(profile)
    for grant in grants:
        grant.relevance_score = scorer.score(grant)

    result = sorted(grants, key=lambda g: g.relevance_score, reverse=True)
    top_score = result[0].relevance_score if result else 0.0
    logger.info(
        "Scored: %d grants, top score: %.2f",
        len(result),
        top_score,
    )
    return result


# Backward compatibility alias
filter_grants = score_and_rank_grants


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
