"""EU CORDIS API collector for Horizon Europe funding opportunities.

Uses the public CORDIS search API (no auth needed).
Endpoint: https://cordis.europa.eu/api/search/results
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import List, Optional

import requests

from grant_hunter.collectors.base import BaseCollector
from grant_hunter.config import REQUEST_TIMEOUT
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

CORDIS_API_URL = "https://cordis.europa.eu/api/search/results"

EU_SEARCH_TERMS = [
    "antimicrobial resistance",
    "antibiotic resistance AI",
    "AMR drug discovery",
]

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


class EUPortalCollector(BaseCollector):
    name = "eu"

    def collect(self) -> List[Grant]:
        grants: List[Grant] = []
        seen_ids: set = set()

        for term in EU_SEARCH_TERMS:
            try:
                fetched = self._search(term, seen_ids)
                grants.extend(fetched)
                logger.info("[eu] Term '%s' -> %d new grants", term, len(fetched))
            except Exception as exc:
                logger.error("[eu] Error searching '%s': %s", term, exc)

        logger.info("[eu] Total collected: %d unique grants", len(grants))
        return grants

    def _search(self, term: str, seen_ids: set) -> List[Grant]:
        results: List[Grant] = []

        for page in range(1, 4):  # max 3 pages
            params = {
                "query": term,
                "type": "/project",
                "page": page,
                "pageSize": 50,
                "format": "json",
            }
            headers = {
                "Accept": "application/json",
                "User-Agent": "grant_hunter/1.0",
            }

            try:
                resp = requests.get(
                    CORDIS_API_URL,
                    params=params,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error("[eu] Request failed page %d: %s", page, exc)
                break

            payload = data.get("payload", {})
            hits = payload.get("results", [])
            if not hits:
                break

            for item in hits:
                grant = self._parse(item)
                if grant and grant.id not in seen_ids:
                    seen_ids.add(grant.id)
                    results.append(grant)

            total = payload.get("total", 0)
            if page * 50 >= total:
                break

        return results

    def _parse(self, item: dict) -> Optional[Grant]:
        try:
            ref = str(item.get("reference", item.get("id", "")))
            if not ref:
                return None

            acronym = item.get("acronym", "")
            title_text = item.get("title", "")
            title = f"{acronym}: {title_text}" if acronym else title_text
            description = item.get("objective", title_text) or ""

            # Programme info
            programmes = item.get("programme", [])
            programme_name = "Horizon Europe"
            if programmes:
                programme_name = programmes[0].get("title", programme_name)

            # Dates
            end_date = self._parse_cordis_date(item.get("endDate", ""))
            start_date = self._parse_cordis_date(item.get("startDate", ""))

            # Budget
            amount_max = None
            cost = item.get("totalCost")
            if cost:
                try:
                    amount_max = float(str(cost).replace(",", ""))
                except ValueError:
                    pass

            url = f"https://cordis.europa.eu/project/id/{ref}"

            return Grant(
                id=f"eu-{ref}",
                title=title,
                agency=f"European Commission / {programme_name}",
                source=self.name,
                deadline=end_date,
                amount_min=None,
                amount_max=amount_max,
                duration_months=None,
                url=url,
                description=str(description)[:2000],
                keywords=[],
                raw_data=item,
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[eu] parse error: %s", exc)
            return None

    @staticmethod
    def _parse_cordis_date(value: str) -> Optional[date]:
        if not value:
            return None

        # Handle template vars like "1 {{month_03}} 2026"
        m = re.match(r"(\d{1,2})\s+\{\{month_(\d{2})\}\}\s+(\d{4})", value)
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass

        # Handle "1 March 2026"
        m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", value)
        if m:
            month_num = MONTH_MAP.get(m.group(2).lower())
            if month_num:
                try:
                    return date(int(m.group(3)), month_num, int(m.group(1)))
                except ValueError:
                    pass

        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value[:19], fmt).date()
            except ValueError:
                continue
        return None
