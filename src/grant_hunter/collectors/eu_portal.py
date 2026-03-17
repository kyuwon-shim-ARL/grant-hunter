"""EU Funding & Tenders Portal collector for open/forthcoming calls.

Uses the bulk grantsTenders.json reference data file (no auth needed).
Endpoint: https://ec.europa.eu/info/funding-tenders/opportunities/data/referenceData/grantsTenders.json
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

import requests

from grant_hunter.collectors.base import BaseCollector
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

GRANTS_TENDERS_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/data/referenceData/grantsTenders.json"
)

# Keywords for AMR / AI relevance filtering (case-insensitive)
AMR_AI_KEYWORDS = [
    "antimicrobial",
    "antibiotic",
    "AMR",
    "drug resistance",
    "drug discovery",
    "artificial intelligence",
    "machine learning",
    "infectious disease",
    "pathogen",
    "bacteria",
    "superbug",
    "sepsis",
    "One Health",
]

OPEN_STATUSES = {"open", "forthcoming"}


class EUPortalCollector(BaseCollector):
    name = "eu"

    def collect(self) -> List[Grant]:
        try:
            topics = self._fetch_topics()
        except Exception as exc:
            logger.error("[eu] Failed to fetch grantsTenders.json: %s", exc)
            return []

        grants: List[Grant] = []
        for topic in topics:
            grant = self._parse(topic)
            if grant is not None:
                grants.append(grant)

        logger.info("[eu] Total collected: %d relevant open/forthcoming grants", len(grants))
        return grants

    def _fetch_topics(self) -> List[dict]:
        resp = requests.get(GRANTS_TENDERS_URL, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        topics = data["fundingData"]["GrantTenderObj"]

        # Filter by status
        filtered = []
        for topic in topics:
            status_abbr = ""
            status = topic.get("status")
            if isinstance(status, dict):
                status_abbr = status.get("abbreviation", "").lower()
            elif isinstance(status, str):
                status_abbr = status.lower()

            if status_abbr not in OPEN_STATUSES:
                continue

            # Keyword match on title + callTitle + objective
            title = topic.get("title", "") or ""
            call_title = topic.get("callTitle", "") or ""
            objective = topic.get("objective", "") or ""
            combined = f"{title} {call_title} {objective}".lower()

            if any(kw.lower() in combined for kw in AMR_AI_KEYWORDS):
                filtered.append(topic)

        logger.info(
            "[eu] %d topics in bulk file, %d match open/forthcoming + keywords",
            len(topics),
            len(filtered),
        )
        return filtered

    def _parse(self, topic: dict) -> Optional[Grant]:
        try:
            # Support new bulk JSON schema (identifier) and legacy test schema (reference)
            identifier = str(topic.get("identifier", topic.get("reference", ""))).strip()
            if not identifier:
                return None

            title = topic.get("title", "") or ""
            call_title = topic.get("callTitle", "") or ""
            acronym = topic.get("acronym", "") or ""
            objective = topic.get("objective", "") or ""

            # Programme info (legacy field)
            programmes = topic.get("programme") or []
            programme_name = "Horizon Europe"
            if programmes:
                programme_name = programmes[0].get("title", programme_name)

            # Build display title
            if call_title and title:
                full_title = f"{call_title} — {title}"
            elif acronym and title:
                full_title = f"{acronym}: {title}"
            else:
                full_title = title or call_title

            description = objective or call_title or title

            # Deadline: bulk format uses deadlineDatesLong (ms epoch)
            deadline: Optional[date] = None
            deadline_dates = topic.get("deadlineDatesLong") or []
            if deadline_dates:
                try:
                    ts_ms = int(deadline_dates[0])
                    deadline = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).date()
                except (TypeError, ValueError, OSError):
                    pass
            elif topic.get("endDate"):
                for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
                    try:
                        deadline = datetime.strptime(topic["endDate"][:19], fmt).date()
                        break
                    except ValueError:
                        continue

            # Budget: legacy CORDIS totalCost field
            amount_max: Optional[float] = None
            cost = topic.get("totalCost")
            if cost:
                try:
                    amount_max = float(str(cost).replace(",", ""))
                except ValueError:
                    pass

            # URL
            if topic.get("identifier"):
                url = (
                    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/"
                    f"opportunities/topic-details/{identifier.lower()}"
                )
            else:
                url = f"https://cordis.europa.eu/project/id/{identifier}"

            agency = f"European Commission / {programme_name}" if programmes else "European Commission"

            return Grant(
                id=f"eu-{identifier}",
                title=full_title,
                agency=agency,
                source=self.name,
                deadline=deadline,
                amount_min=None,
                amount_max=amount_max,
                duration_months=None,
                url=url,
                description=str(description)[:5000],
                keywords=[],
                raw_data=topic,
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[eu] parse error: %s", exc)
            return None
