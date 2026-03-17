"""Researcher profile presets for personalized grant scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ResearcherProfile:
    """Defines category weight overrides for a researcher type."""

    name: str
    description: str
    weights: Dict[str, float]  # Must have keys: amr, ai, drug, amount

    def __post_init__(self) -> None:
        required = {"amr", "ai", "drug", "amount"}
        if set(self.weights.keys()) != required:
            raise ValueError(
                f"Weights must have keys {required}, got {set(self.weights.keys())}"
            )
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


# Preset profiles for IPK researchers
PROFILES: Dict[str, ResearcherProfile] = {
    "default": ResearcherProfile(
        name="Default (Balanced)",
        description="Balanced AMR+AI scoring for general use",
        weights={"amr": 0.40, "ai": 0.30, "drug": 0.20, "amount": 0.10},
    ),
    "wetlab_amr": ResearcherProfile(
        name="Wet-lab AMR Researcher",
        description="Focus on antimicrobial resistance mechanisms, pathogens, susceptibility testing",
        weights={"amr": 0.60, "ai": 0.10, "drug": 0.25, "amount": 0.05},
    ),
    "computational": ResearcherProfile(
        name="Computational Biologist",
        description="Focus on AI/ML methods, bioinformatics, in silico approaches",
        weights={"amr": 0.15, "ai": 0.60, "drug": 0.20, "amount": 0.05},
    ),
    "translational": ResearcherProfile(
        name="Translational Researcher",
        description="Focus on drug discovery pipeline, from hit to lead to preclinical",
        weights={"amr": 0.25, "ai": 0.20, "drug": 0.45, "amount": 0.10},
    ),
    "clinical": ResearcherProfile(
        name="Clinical Researcher",
        description="Focus on clinical trials, diagnostics, surveillance, infection control",
        weights={"amr": 0.45, "ai": 0.15, "drug": 0.30, "amount": 0.10},
    ),
}


def get_profile(name: str) -> ResearcherProfile:
    """Get a profile by name. Raises KeyError if not found."""
    if name not in PROFILES:
        available = ", ".join(PROFILES.keys())
        raise KeyError(f"Unknown profile '{name}'. Available: {available}")
    return PROFILES[name]


def list_profiles() -> Dict[str, str]:
    """Return dict of profile name -> description."""
    return {name: p.description for name, p in PROFILES.items()}
