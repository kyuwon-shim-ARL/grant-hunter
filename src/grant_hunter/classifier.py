"""MECE 3-axis classification + priority tiering for grants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from grant_hunter.models import Grant


@dataclass
class GrantClassification:
    research_stage: str  # basic | translational | clinical | infrastructure | unclassified
    funding_type: str    # project_grant | fellowship | consortium | challenge | institutional
    urgency: str         # urgent | upcoming | open | rolling | expired
    tier: str            # tier1 | tier2 | tier3 | tier4
    tier_label: str      # "Must Apply" | "Strong Fit" | "Worth Monitoring" | "Low Priority"


_STAGE_PATTERNS: list[tuple[str, list[str]]] = [
    ("clinical", [
        r"clinical trial", r"phase\s+i+", r"\bpatient\b", r"\bhospital\b",
        r"clinical study", r"regulatory",
    ]),
    ("translational", [
        r"translational", r"preclinical", r"animal model", r"lead optimization",
        r"drug development", r"drug discovery", r"\bcandidate\b", r"therapeutic",
    ]),
    ("basic", [
        r"mechanism", r"genomic", r"molecular", r"fundamental", r"discovery",
        r"basic research", r"in vitro", r"model organism",
    ]),
    ("infrastructure", [
        r"surveillance", r"capacity building", r"\btraining\b", r"\bnetwork\b",
        r"\bpolicy\b", r"stewardship", r"one health",
    ]),
]

_FUNDING_PATTERNS: list[tuple[str, list[str]]] = [
    ("fellowship", [
        r"fellowship", r"\btraining\b", r"\bcareer\b", r"postdoc",
        r"k.award", r"f.award",
    ]),
    ("consortium", [
        r"consortium", r"\bnetwork\b", r"multi.site", r"collaborative", r"partnership",
    ]),
    ("institutional", [
        r"capacity", r"infrastructure", r"equipment", r"core facility",
    ]),
]

_CHALLENGE_KEYWORDS = ["challenge", "prize", "competition", "award"]


def _search_text(patterns: list[str], text: str) -> bool:
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


class GrantClassifier:
    def classify(self, grant: Grant, today: Optional[date] = None) -> GrantClassification:
        if today is None:
            today = date.today()

        text = f"{grant.title} {grant.description} {' '.join(grant.keywords)}"

        # --- Axis 1: Research Stage ---
        research_stage = "unclassified"
        for stage, patterns in _STAGE_PATTERNS:
            if _search_text(patterns, text):
                research_stage = stage
                break

        # --- Axis 2: Funding Type ---
        if _search_text(_CHALLENGE_KEYWORDS, text):
            funding_type = "challenge"
        else:
            funding_type = "project_grant"
            for ftype, patterns in _FUNDING_PATTERNS:
                if _search_text(patterns, text):
                    funding_type = ftype
                    break

        # --- Axis 3: Urgency ---
        if grant.deadline is None:
            urgency = "rolling"
        else:
            days = (grant.deadline - today).days
            if days < 0:
                urgency = "expired"
            elif days <= 30:
                urgency = "urgent"
            elif days <= 90:
                urgency = "upcoming"
            else:
                urgency = "open"

        # --- Priority Tier ---
        # Calibrated to real score distribution (max ~0.60, std ~0.09)
        # Target: T1 < T2 < T3 < T4 (ascending count)
        # T4 investigation (2026-03-30): No eligibility integration bug found at this location.
        # Investigated: Grant model (no eligibility_status field), EligibilityEngine.check() return values,
        # pipeline.py eligibility flow, and all 45 classifier/eligibility tests.
        # Design: callers attach eligibility_status as a dynamic attribute before classify(); pipeline
        # stores results in eligibility_map separately and does not write back onto Grant objects.
        # The getattr default of "uncertain" is correct fallback behaviour when no status is attached.
        eligibility = getattr(grant, "eligibility_status", "uncertain")
        score = grant.relevance_score

        if score >= 0.40 and eligibility == "eligible":
            tier, tier_label = "tier1", "Must Apply"
        elif score >= 0.28 and eligibility in ("eligible", "uncertain"):
            tier, tier_label = "tier2", "Strong Fit"
        elif score >= 0.20:
            tier, tier_label = "tier3", "Worth Monitoring"
        else:
            tier, tier_label = "tier4", "Low Priority"

        return GrantClassification(
            research_stage=research_stage,
            funding_type=funding_type,
            urgency=urgency,
            tier=tier,
            tier_label=tier_label,
        )

    def classify_batch(
        self, grants: list[Grant], today: Optional[date] = None
    ) -> list[GrantClassification]:
        if today is None:
            today = date.today()
        return [self.classify(g, today) for g in grants]
