"""NIH funding opportunity collector via Grants.gov API (NIH agency filter)."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import List, Optional

import requests

from grant_hunter.collectors.base import BaseCollector
from grant_hunter.config import REQUEST_TIMEOUT
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

GRANTS_GOV_SEARCH_URL = "https://api.grants.gov/v1/api/search2"
GRANTS_GOV_DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity"

NIH_AGENCY_CODE = "HHS-NIH11"
ROWS_PER_PAGE = 25
MAX_RESULTS_PER_TERM = 250
DETAIL_RATE_LIMIT = 0.5  # seconds between detail fetches

NIH_SEARCH_TERMS = [
    "antimicrobial resistance",
    "antibiotic resistance",
    "drug-resistant bacteria",
    "machine learning antibiotic",
    "artificial intelligence AMR",
    "deep learning antimicrobial",
]


class NIHCollector(BaseCollector):
    name = "nih"

    def collect(self) -> List[Grant]:
        grants: List[Grant] = []
        seen_ids: set = set()

        for term in NIH_SEARCH_TERMS:
            try:
                fetched = self._search(term, seen_ids)
                grants.extend(fetched)
                logger.info("[nih] Term '%s' -> %d new opportunities", term, len(fetched))
            except Exception as exc:
                logger.error("[nih] Error searching '%s': %s", term, exc)

        logger.info("[nih] Total collected: %d unique opportunities", len(grants))
        return grants

    def _search(self, term: str, seen_ids: set) -> List[Grant]:
        results: List[Grant] = []
        start = 0

        while start < MAX_RESULTS_PER_TERM:
            payload = {
                "rows": ROWS_PER_PAGE,
                "startRecordNum": start,
                "agencies": NIH_AGENCY_CODE,
                "oppStatuses": "posted|forecasted",
                "keyword": term,
            }

            resp = requests.post(
                GRANTS_GOV_SEARCH_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            hits = (data.get("data") or {}).get("oppHits", [])
            if not hits:
                break

            for item in hits:
                opp_number = item.get("number", "")
                if not opp_number or opp_number in seen_ids:
                    continue

                grant = self._fetch_and_parse(item)
                if grant:
                    seen_ids.add(opp_number)
                    results.append(grant)
                    time.sleep(DETAIL_RATE_LIMIT)

            if len(hits) < ROWS_PER_PAGE:
                break

            start += ROWS_PER_PAGE

        return results

    def _fetch_and_parse(self, summary: dict) -> Optional[Grant]:
        """Fetch detail for one opportunity and return a Grant."""
        opp_id = summary.get("id")
        if not opp_id:
            return self._parse(summary, detail=None)

        try:
            resp = requests.post(
                GRANTS_GOV_DETAIL_URL,
                json={"opportunityId": int(opp_id)},
                timeout=REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            detail_data = resp.json().get("data", {})
        except Exception as exc:
            logger.debug("[nih] detail fetch error for id=%s: %s", opp_id, exc)
            detail_data = None

        return self._parse(summary, detail=detail_data)

    def _parse(self, item: dict, detail: Optional[dict] = None) -> Optional[Grant]:
        try:
            opp_number = item.get("number", "")
            if not opp_number:
                return None

            title = item.get("title", "") or ""
            agency_code = item.get("agencyCode", "") or "NIH"

            synopsis = detail.get("synopsis", {}) if detail else {}
            forecast = detail.get("forecast", {}) if detail else {}

            # Try synopsis first (posted), then forecast (forecasted)
            description = (
                synopsis.get("synopsisDesc", "")
                or forecast.get("forecastDesc", "")
                or ""
            )
            # Strip HTML tags for cleaner text
            if "<" in description:
                import re
                description = re.sub(r'<[^>]+>', ' ', description)
                description = re.sub(r'\s+', ' ', description).strip()

            award_floor = synopsis.get("awardFloor") if synopsis else None
            award_ceiling = synopsis.get("awardCeiling") if synopsis else None
            # Also check forecast for award info
            if not award_floor and forecast:
                award_floor = forecast.get("awardFloor")
            if not award_ceiling and forecast:
                award_ceiling = forecast.get("awardCeiling")
            amount_min = float(award_floor) if award_floor else None
            amount_max = float(award_ceiling) if award_ceiling else None

            close_date_str = item.get("closeDate", "")
            deadline = self._parse_date(close_date_str)

            url = f"https://www.grants.gov/search-results-detail/{opp_number}"

            return Grant(
                id=opp_number,
                title=title,
                agency=agency_code,
                source=self.name,
                deadline=deadline,
                amount_min=amount_min,
                amount_max=amount_max,
                duration_months=None,
                url=url,
                description=description[:2000],
                keywords=[],
                raw_data=item,
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[nih] parse error: %s | item: %s", exc, str(item)[:200])
            return None

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        if not value:
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value)[:19], fmt).date()
            except ValueError:
                continue
        return None
