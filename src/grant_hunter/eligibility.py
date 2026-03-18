"""IPK eligibility rules engine.

Determines whether Institut Pasteur Korea (IPK) — a non-profit private
research institute — is eligible to apply for a given grant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from grant_hunter.models import Grant


@dataclass
class EligibilityResult:
    status: str  # "eligible" | "ineligible" | "uncertain"
    confidence: float  # 0.0–1.0
    reason: str
    rules_matched: List[str] = field(default_factory=list)


# ── Rule helpers ──────────────────────────────────────────────────────────────

def _contains_any(text: str, patterns: List[str]) -> List[str]:
    """Return list of patterns found (case-insensitive)."""
    text_l = text.lower()
    matched = []
    for p in patterns:
        if re.search(r'\b' + re.escape(p.lower()) + r'\b', text_l):
            matched.append(p)
    return matched


# ── Keyword lists for each rule ───────────────────────────────────────────────

# Rule 1 – HIC exclusion: Korea is a high-income country
_HIC_EXCLUDE = [
    "lmic", "low-income", "lower-income", "low income",
    "developing countries", "developing country", "developing nations",
    "low- and middle-income", "low and middle income",
    "middle-income countries", "official development assistance", "oda",
    "least developed", "sub-saharan",
]

# Rule 2 – University / faculty only
_UNIVERSITY_ONLY = [
    "university only", "universities only", "academic institution only",
    "academic institutions only", "faculty only", "faculty member only",
    "faculty members only", "college or university", "colleges or universities",
    "degree-granting institution", "degree-granting institutions",
    "institution of higher education", "institutions of higher education",
    "higher education institution", "higher education institutions",
]

# Rule 3 – US domestic only (NIH R01/R21 are foreign-eligible → exempt)
_US_ONLY = [
    # Existing
    "us institutions only", "u.s. institutions only",
    "domestic applicants only", "domestic institutions only",
    "us domestic", "u.s. domestic",
    "must be a u.s.", "must be a us",
    "citizenship required", "us citizenship",
    # New: Standard RFP restriction language
    "applicants must be us-based",
    "must be us-based organizations",
    "only organizations in the united states",
    "restricted to american institutions",
    "must hold us permanent residency",
    "us permanent resident",
    "us citizen or permanent resident",
    "sbir eligible",
    "sttr eligible",
    "501(c)(3) us nonprofit",
    "united states-based",
    "located in the united states",
    "based in the united states",
    "u.s.-based organization",
    "us-based organization",
    "limited to us",
    "limited to u.s.",
    "open only to us",
    "open only to u.s.",
    "us entities only",
    "u.s. entities only",
    "american institutions only",
    "us organization",
    "u.s. organization",
]

# NIH programmes that explicitly allow foreign institutions
_NIH_FOREIGN_ELIGIBLE_IDS = {
    "r01", "r21", "r03", "r15", "r34", "r33", "r61", "r37",
    "u01", "u54", "u19", "ub1",
    "p01", "p50",
    "rm1",
}

# PAR/RFA prefixes matched separately with dash anchor to avoid substring FPs
_NIH_FOREIGN_ELIGIBLE_PREFIXES = ("par-", "rfa-")

# Rule 4 – Non-profit / research institute positive signals
_NONPROFIT_POSITIVE = [
    "non-profit", "nonprofit", "not-for-profit", "not for profit",
    "research institute", "research institution", "research center",
    "research centre", "independent research", "private research",
    "501(c)(3)", "charitable organization",
]

# Rule 5 – EU Horizon eligibility (Korea is Pillar II associate member since 2025-07)
_EU_HORIZON = [
    "horizon europe", "horizon 2020", "horizon 2021",
    "eu horizon", "european research council", "erc",
    "ihi ", "innovative health initiative",
    "msca", "marie skłodowska", "marie curie",
]

# Rule 6 – Industry / private sector only
_INDUSTRY_ONLY = [
    "private sector only", "industry only", "for-profit only",
    "companies only", "sme only", "small business only",
    "commercial entity only", "spin-off only", "startup only",
    "equity investment", "venture capital",
]

# Rule 7 – Specific named ineligible programmes / funds
_NAMED_INELIGIBLE = [
    "amr action fund",        # equity-investment vehicle
    "longitude prize",        # ended
    "openai people-first",    # US non-profit only
    "schmidt sciences",       # invitation only
]

# Rule 8 – LMIC country-level programmes
_LMIC_COUNTRY = [
    "national government only", "government of a developing",
    "eligible countries list", "oda recipient",
    "country programme", "country-level grant",
]


# ── Engine ────────────────────────────────────────────────────────────────────

class EligibilityEngine:
    """Apply IPK eligibility rules to a Grant and return an EligibilityResult."""

    def check(self, grant: Grant) -> EligibilityResult:
        text = f"{grant.title} {grant.description} {' '.join(grant.keywords)}".strip()
        title_l = grant.title.lower()
        source = grant.source.lower()

        ineligible_rules: List[str] = []
        eligible_rules: List[str] = []

        # ── INELIGIBLE rules ──────────────────────────────────────────────────

        # Rule 1: HIC exclusion
        hits = _contains_any(text, _HIC_EXCLUDE)
        if hits:
            ineligible_rules.append(f"HIC_EXCLUDE({', '.join(hits[:2])})")

        # Rule 2: University only
        hits = _contains_any(text, _UNIVERSITY_ONLY)
        if hits:
            ineligible_rules.append(f"UNIVERSITY_ONLY({hits[0]})")

        # Rule 3: US only — but check NIH foreign-eligible exemption first
        is_nih_foreign_eligible = False
        if source == "nih":
            grant_id_l = grant.id.lower()
            # Check mechanism codes (substring match OK for short codes like r01)
            for mech in _NIH_FOREIGN_ELIGIBLE_IDS:
                if mech in grant_id_l or mech in title_l:
                    is_nih_foreign_eligible = True
                    break
            # Check PAR/RFA prefixes with dash anchor to avoid substring FPs
            if not is_nih_foreign_eligible:
                for prefix in _NIH_FOREIGN_ELIGIBLE_PREFIXES:
                    if grant_id_l.startswith(prefix) or f" {prefix}" in f" {title_l}":
                        is_nih_foreign_eligible = True
                        break

        if not is_nih_foreign_eligible:
            hits = _contains_any(text, _US_ONLY)
            if hits:
                ineligible_rules.append(f"US_ONLY({hits[0]})")

        # Rule 6: Industry only
        hits = _contains_any(text, _INDUSTRY_ONLY)
        if hits:
            ineligible_rules.append(f"INDUSTRY_ONLY({hits[0]})")

        # Rule 7: Named ineligible
        hits = _contains_any(text, _NAMED_INELIGIBLE)
        if hits:
            ineligible_rules.append(f"NAMED_INELIGIBLE({hits[0]})")

        # Rule 8: LMIC country-level
        hits = _contains_any(text, _LMIC_COUNTRY)
        if hits:
            ineligible_rules.append(f"LMIC_COUNTRY({hits[0]})")

        # ── ELIGIBLE rules ────────────────────────────────────────────────────

        # Rule 4: Non-profit positive signal
        hits = _contains_any(text, _NONPROFIT_POSITIVE)
        if hits:
            eligible_rules.append(f"NONPROFIT_POSITIVE({hits[0]})")

        # Rule 5: EU Horizon (Korea is associate member since 2025-07)
        hits = _contains_any(text, _EU_HORIZON)
        if hits:
            eligible_rules.append("EU_HORIZON_ASSOCIATE")
        elif source == "eu":
            # EU source but no explicit Horizon language — mark as likely eligible
            # but with lower confidence (Korea is Pillar II associate)
            eligible_rules.append("EU_SOURCE_LIKELY_ELIGIBLE")

        # NIH foreign-eligible exemption counts as positive
        if is_nih_foreign_eligible:
            eligible_rules.append("NIH_FOREIGN_ELIGIBLE")

        # ── Decision ──────────────────────────────────────────────────────────
        all_rules = ineligible_rules + eligible_rules

        if ineligible_rules:
            # Even one hard ineligible rule is conclusive
            confidence = min(0.95, 0.7 + 0.1 * len(ineligible_rules))
            reason = "; ".join(ineligible_rules)
            return EligibilityResult(
                status="ineligible",
                confidence=confidence,
                reason=reason,
                rules_matched=all_rules,
            )

        if eligible_rules:
            # Lower confidence for EU source-only signals
            base_conf = 0.55 if eligible_rules == ["EU_SOURCE_LIKELY_ELIGIBLE"] else 0.6
            confidence = min(0.9, base_conf + 0.1 * len(eligible_rules))
            reason = "; ".join(eligible_rules)
            return EligibilityResult(
                status="eligible",
                confidence=confidence,
                reason=reason,
                rules_matched=all_rules,
            )

        # No strong signal either way
        return EligibilityResult(
            status="uncertain",
            confidence=0.5,
            reason="No decisive eligibility signal found",
            rules_matched=all_rules,
        )
