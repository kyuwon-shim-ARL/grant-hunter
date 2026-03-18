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
    if amr_pass:
        return "tier2"
    return "skip"


def filter_grants(grants: List[Grant]) -> List[Grant]:
    """Return grants that pass keyword filter, with two tiers.

    Tier 1: AMR AND AI keywords present (full relevance score).
    Tier 2: AMR-only (score penalized by 0.5x to rank below Tier 1).
    """
    result: List[Grant] = []
    tier1_count = 0
    tier2_count = 0
    for grant in grants:
        tier = passes_keyword_gate(grant)
        if tier == "skip":
            continue
        grant.relevance_score = _scorer.score(grant)
        if tier == "tier2":
            searchable = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"
            drug_hits, _ = _count_hits(searchable, DRUG_KEYWORDS)
            if drug_hits >= 1:
                grant.relevance_score *= 0.7  # reduced penalty for AMR+drug_discovery
            else:
                grant.relevance_score *= 0.5  # standard tier2 penalty
            tier2_count += 1
        else:
            tier1_count += 1
        result.append(grant)

    result.sort(key=lambda g: g.relevance_score, reverse=True)
    logger.info(
        "Filter: %d/%d grants passed (tier1=%d AMR+AI, tier2=%d AMR-only)",
        len(result),
        len(grants),
        tier1_count,
        tier2_count,
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
