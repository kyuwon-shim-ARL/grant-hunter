"""Grant data model - unified schema across all sources."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional, List, Dict, Any
import json


@dataclass
class Grant:
    id: str
    title: str
    agency: str
    source: str  # "nih" | "eu" | "grants_gov"
    url: str
    description: str
    deadline: Optional[date] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    duration_months: Optional[int] = None
    keywords: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    relevance_score: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.deadline is not None:
            d["deadline"] = self.deadline.isoformat()
        if self.fetched_at is not None:
            d["fetched_at"] = self.fetched_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Grant":
        d = dict(d)
        if d.get("deadline"):
            d["deadline"] = date.fromisoformat(d["deadline"])
        if d.get("fetched_at"):
            d["fetched_at"] = datetime.fromisoformat(d["fetched_at"])
        return cls(**d)

    def fingerprint(self) -> str:
        """Stable key for deduplication."""
        return f"{self.source}::{self.id}"


class GrantEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)
