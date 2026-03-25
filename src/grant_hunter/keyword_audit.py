"""Keyword audit module — coverage analysis, false negative detection, and keyword suggestions.

Provides tools to understand how well the keywords.json file covers the grant corpus,
identify grants that may be relevant but missed by keyword scoring, and suggest new
keywords based on term frequency in high-LLM-scored grants.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from grant_hunter.models import Grant
from grant_hunter.scoring import _get_keywords, _flatten, _tf, _tokenize

# ── Constants ────────────────────────────────────────────────────────────────

_STOPWORDS: frozenset = frozenset(
    """
    a about above after again against all also am an and any are aren't as at
    be because been before being below between both but by can't cannot could
    couldn't did didn't do does doesn't doing don't down during each few for
    from further get got had hadn't has hasn't have haven't having he he'd he'll
    he's her here here's hers herself him himself his how how's i i'd i'll i'm
    i've if in into is isn't it it's its itself let's me more most mustn't my
    myself no nor not of off on once only or other ought our ours ourselves out
    over own same shan't she she'd she'll she's should shouldn't so some such
    than that that's the their theirs them themselves then there there's these
    they they'd they'll they're they've this those through to too under until up
    very was wasn't we we'd we'll we're we've were weren't what what's when
    when's where where's which while who who's whom why why's will with won't
    would wouldn't you you'd you'll you're you've your yours yourself yourselves
    also among used using within without across including provide provides
    support supports funded funding fund new may well upon
    """.split()
)

# Categories recognized by this module (must match keywords.json top-level keys)
_CATEGORIES = ("amr", "ai", "drug_discovery")

# ── Internal helpers ─────────────────────────────────────────────────────────


def _searchable(grant: Grant) -> str:
    """Combine title + description + grant keywords into one searchable string."""
    return f"{grant.title} {grant.description} {' '.join(grant.keywords)}"


def _get_category_keywords() -> Dict[str, List[str]]:
    """Return {category: [keyword, ...]} for all recognized categories."""
    kw = _get_keywords()
    return {cat: _flatten(kw, cat) for cat in _CATEGORIES}


def _matches_keyword(tokens: List[str], keyword: str) -> bool:
    """Return True if keyword is found in token list (reuses scoring._tf logic)."""
    return _tf(tokens, keyword) > 0


def _extract_ngrams(tokens: List[str], n: int) -> List[str]:
    """Yield n-grams from token list as space-joined strings."""
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _is_relevant_term(term: str) -> bool:
    """Return True if term is not a stopword and has meaningful length."""
    parts = term.split()
    if not parts:
        return False
    # All unigram parts must not be stopwords
    if all(p in _STOPWORDS for p in parts):
        return False
    # Filter very short or purely numeric terms
    if all(len(p) <= 2 for p in parts):
        return False
    if re.fullmatch(r"[\d\s]+", term):
        return False
    return True


def _categorize_suggestion(term: str) -> str:
    """Heuristically assign a suggested category to an extracted term."""
    amr_hints = {
        "resist", "antibiotic", "antimicrobial", "pathogen", "bacteria",
        "bacterial", "infection", "phage", "bacteriophage", "plasmid",
        "virulence", "nosocomial", "sepsis", "biofilm", "efflux", "microbiome",
        "microorganism", "clinical", "susceptib", "carbapenem", "colistin",
        "methicillin", "vancomycin", "beta-lactam", "gram",
    }
    ai_hints = {
        "machine", "learning", "deep", "neural", "model", "predict",
        "algorithm", "computational", "bioinformat", "cheminformat",
        "classification", "regression", "cluster", "embedding", "training",
        "inference", "automat", "data-driven", "generative", "transformer",
        "language", "network",
    }
    drug_hints = {
        "drug", "compound", "scaffold", "synthesis", "assay", "screen",
        "pharmacok", "pharmacod", "therapeut", "inhibit", "ligand", "binding",
        "toxic", "potency", "selectiv", "clinical", "trial", "repurpos",
        "peptide", "antibody", "antifung", "antivir", "antibiotic",
    }

    term_lower = term.lower()
    amr_score = sum(1 for h in amr_hints if h in term_lower)
    ai_score = sum(1 for h in ai_hints if h in term_lower)
    drug_score = sum(1 for h in drug_hints if h in term_lower)

    best = max(amr_score, ai_score, drug_score)
    if best == 0:
        return "amr"  # default to primary focus
    if amr_score == best:
        return "amr"
    if drug_score == best:
        return "drug_discovery"
    return "ai"


# ── Public API ───────────────────────────────────────────────────────────────


def keyword_coverage(grants: List[Grant], keywords: Optional[dict] = None) -> dict:
    """Analyze which keywords actually match across the grant corpus.

    Args:
        grants:   List of Grant objects to analyse.
        keywords: Optional override for the keywords dict (defaults to keywords.json).

    Returns:
        Dict with per-category and overall coverage stats, plus top_keywords and
        zero_hit_keywords lists.  Structure::

            {
                "amr": {"total": 113, "matched": 45, "unmatched": [...], "match_rate": 0.398},
                "ai":  {"total": 77,  "matched": 30, "unmatched": [...], "match_rate": 0.390},
                "drug_discovery": {...},
                "overall": {"total": 259, "matched": 100, "match_rate": 0.386},
                "top_keywords": [
                    {"keyword": "...", "category": "amr", "hit_count": 150}, ...
                ],  # top 20 by corpus-level hit count
                "zero_hit_keywords": [
                    {"keyword": "...", "category": "amr"}, ...
                ],
            }
    """
    if keywords is None:
        keywords = _get_keywords()

    cat_kw = {cat: _flatten(keywords, cat) for cat in _CATEGORIES}

    # hit_count[cat][kw] = number of grants that match this keyword
    hit_counts: Dict[str, Counter] = {cat: Counter() for cat in _CATEGORIES}

    for grant in grants:
        text = _searchable(grant)
        tokens = _tokenize(text)
        for cat, kw_list in cat_kw.items():
            for kw in kw_list:
                if _matches_keyword(tokens, kw):
                    hit_counts[cat][kw] += 1

    result: dict = {}
    overall_total = 0
    overall_matched = 0
    all_keyword_hits: List[dict] = []

    for cat, kw_list in cat_kw.items():
        total = len(kw_list)
        matched_kws = [kw for kw in kw_list if hit_counts[cat][kw] > 0]
        unmatched_kws = [kw for kw in kw_list if hit_counts[cat][kw] == 0]
        matched = len(matched_kws)
        result[cat] = {
            "total": total,
            "matched": matched,
            "unmatched": unmatched_kws,
            "match_rate": round(matched / total, 4) if total > 0 else 0.0,
        }
        overall_total += total
        overall_matched += matched

        for kw in kw_list:
            all_keyword_hits.append(
                {"keyword": kw, "category": cat, "hit_count": hit_counts[cat][kw]}
            )

    result["overall"] = {
        "total": overall_total,
        "matched": overall_matched,
        "match_rate": round(overall_matched / overall_total, 4) if overall_total > 0 else 0.0,
    }

    all_keyword_hits.sort(key=lambda x: x["hit_count"], reverse=True)
    result["top_keywords"] = all_keyword_hits[:20]
    result["zero_hit_keywords"] = [e for e in all_keyword_hits if e["hit_count"] == 0]

    return result


def detect_false_negatives(
    grants: List[Grant],
    threshold_kw: float = 0.20,
    threshold_llm: float = 0.60,
) -> List[dict]:
    """Find grants where LLM score is high but keyword score is low.

    These grants likely represent topic areas that keywords.json doesn't cover well.
    Grants without a ``llm_score`` attribute (or where it is ``None``) are skipped.

    Args:
        grants:        List of Grant objects.
        threshold_kw:  Keyword score ceiling — grant must score below this.
        threshold_llm: LLM score floor — grant must score at or above this.

    Returns:
        List of dicts sorted by gap (desc)::

            [
                {
                    "grant_id": "...",
                    "title": "...",
                    "keyword_score": 0.05,
                    "llm_score": 0.80,
                    "gap": 0.75,
                    "missing_terms": ["term1", "term2"],
                },
                ...
            ]
    """
    all_kw_flat: List[str] = []
    cat_kw = _get_category_keywords()
    for kw_list in cat_kw.values():
        all_kw_flat.extend(kw_list)
    kw_set_lower = {kw.lower() for kw in all_kw_flat}

    from grant_hunter.scoring import _keyword_score, _get_amr_kw, _get_ai_kw, _get_drug_kw
    from grant_hunter.profiles import get_default_profile

    profile = get_default_profile()
    weights = dict(profile.weights)

    results: List[dict] = []

    for grant in grants:
        llm_score: Optional[float] = getattr(grant, "llm_score", None)
        if llm_score is None:
            continue
        if llm_score < threshold_llm:
            continue

        text = _searchable(grant)
        amr_s = _keyword_score(text, _get_amr_kw())
        ai_s = _keyword_score(text, _get_ai_kw())
        drug_s = _keyword_score(text, _get_drug_kw())
        kw_score = (
            weights["amr"] * amr_s
            + weights["ai"] * ai_s
            + weights.get("drug", weights.get("drug_discovery", 0.0)) * drug_s
        )
        kw_score = round(min(kw_score, 1.0), 4)

        if kw_score >= threshold_kw:
            continue

        # Find frequent terms in this grant's text not already in keywords.json
        tokens = _tokenize(text)
        term_freq: Counter = Counter()
        for n in (1, 2, 3):
            for ngram in _extract_ngrams(tokens, n):
                if ngram not in kw_set_lower and _is_relevant_term(ngram):
                    term_freq[ngram] += 1

        missing_terms = [term for term, _ in term_freq.most_common(10)]

        results.append(
            {
                "grant_id": grant.id,
                "title": grant.title,
                "keyword_score": kw_score,
                "llm_score": round(float(llm_score), 4),
                "gap": round(float(llm_score) - kw_score, 4),
                "missing_terms": missing_terms,
            }
        )

    results.sort(key=lambda x: x["gap"], reverse=True)
    return results


def suggest_keywords(grants: List[Grant], top_n: int = 20) -> List[dict]:
    """Extract frequent terms from grant descriptions not already in keywords.json.

    Focuses on AMR/AI/Drug-related terminology by analysing grants that have a
    high ``llm_score`` (>= 0.60).  Falls back to all grants if none have
    ``llm_score`` set.

    Args:
        grants: List of Grant objects.
        top_n:  Maximum number of suggestions to return.

    Returns:
        List of dicts sorted by frequency (desc)::

            [
                {
                    "term": "phage therapy",
                    "frequency": 12,
                    "suggested_category": "amr",
                    "source_grants": ["id1", "id2"],
                },
                ...
            ]
    """
    all_kw_flat: List[str] = []
    cat_kw = _get_category_keywords()
    for kw_list in cat_kw.values():
        all_kw_flat.extend(kw_list)
    kw_set_lower = {kw.lower() for kw in all_kw_flat}

    # Prefer high-LLM-score grants; fall back to full corpus
    high_score_grants = [
        g for g in grants if getattr(g, "llm_score", None) is not None
        and float(g.llm_score) >= 0.60  # type: ignore[arg-type]
    ]
    target_grants = high_score_grants if high_score_grants else grants

    # term -> list of grant ids
    term_grants: Dict[str, List[str]] = defaultdict(list)
    term_freq: Counter = Counter()

    for grant in target_grants:
        text = _searchable(grant)
        tokens = _tokenize(text)
        seen_in_grant: set = set()
        for n in (1, 2, 3):
            for ngram in _extract_ngrams(tokens, n):
                if ngram in kw_set_lower:
                    continue
                if not _is_relevant_term(ngram):
                    continue
                if ngram in seen_in_grant:
                    continue
                seen_in_grant.add(ngram)
                term_freq[ngram] += 1
                term_grants[ngram].append(grant.id)

    suggestions: List[dict] = []
    for term, freq in term_freq.most_common(top_n):
        suggestions.append(
            {
                "term": term,
                "frequency": freq,
                "suggested_category": _categorize_suggestion(term),
                "source_grants": term_grants[term],
            }
        )

    return suggestions


def generate_audit_report(grants: List[Grant]) -> dict:
    """Generate a complete keyword audit combining coverage, false negatives, and suggestions.

    Args:
        grants: List of Grant objects to audit.

    Returns:
        Dict with three top-level keys::

            {
                "coverage": { ... },           # from keyword_coverage()
                "false_negatives": [ ... ],     # from detect_false_negatives()
                "suggestions": [ ... ],         # from suggest_keywords()
                "summary": {
                    "total_grants": 259,
                    "grants_with_llm_score": 50,
                    "false_negative_count": 7,
                    "suggestion_count": 20,
                    "overall_match_rate": 0.386,
                },
            }
    """
    coverage = keyword_coverage(grants)
    false_negatives = detect_false_negatives(grants)
    suggestions = suggest_keywords(grants)

    grants_with_llm = sum(
        1 for g in grants if getattr(g, "llm_score", None) is not None
    )

    return {
        "coverage": coverage,
        "false_negatives": false_negatives,
        "suggestions": suggestions,
        "summary": {
            "total_grants": len(grants),
            "grants_with_llm_score": grants_with_llm,
            "false_negative_count": len(false_negatives),
            "suggestion_count": len(suggestions),
            "overall_match_rate": coverage["overall"]["match_rate"],
        },
    }
