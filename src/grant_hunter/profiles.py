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

# Runtime custom profiles (created via MCP tool, not persisted across restarts)
_CUSTOM_PROFILES: Dict[str, ResearcherProfile] = {}


def create_profile(name: str, weights: Dict[str, float], description: str = "") -> ResearcherProfile:
    """Create and register a custom researcher profile at runtime.

    Args:
        name: Profile name (must not collide with preset names).
        weights: Dict with keys amr, ai, drug, amount summing to 1.0.
        description: Optional description.

    Returns:
        The created ResearcherProfile.

    Raises:
        ValueError: If name collides with preset or weights are invalid.
    """
    if name in PROFILES:
        raise ValueError(f"Cannot override preset profile '{name}'")
    profile = ResearcherProfile(
        name=name,
        description=description or f"Custom profile: {name}",
        weights=weights,
    )
    _CUSTOM_PROFILES[name] = profile
    return profile


def get_default_profile() -> ResearcherProfile:
    """Return the default profile."""
    return PROFILES["default"]


def get_profile(name: str) -> ResearcherProfile:
    """Get a profile by name. Checks custom profiles first, then presets."""
    if name in _CUSTOM_PROFILES:
        return _CUSTOM_PROFILES[name]
    if name in PROFILES:
        return PROFILES[name]
    available = ", ".join(list(PROFILES.keys()) + list(_CUSTOM_PROFILES.keys()))
    raise KeyError(f"Unknown profile '{name}'. Available: {available}")


def list_profiles() -> Dict[str, str]:
    """Return dict of profile name -> description (presets + custom)."""
    result = {name: p.description for name, p in PROFILES.items()}
    result.update({name: p.description for name, p in _CUSTOM_PROFILES.items()})
    return result
