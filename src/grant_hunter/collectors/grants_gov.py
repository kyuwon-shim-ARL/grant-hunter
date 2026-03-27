"""grants.gov API collector with graceful degradation."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import List, Optional

import requests

from grant_hunter.collectors.amr_filter import amr_ai_post_filter as _amr_ai_post_filter
from grant_hunter.collectors.base import BaseCollector
from grant_hunter.config import GRANTS_GOV_API_URL, GRANTS_GOV_PAGE_SIZE, GRANTS_GOV_MAX_PAGES, REQUEST_TIMEOUT
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity"

SEARCH_KEYWORDS = [
    "antimicrobial resistance",
    "antibiotic resistance",
    "drug resistant bacteria",
    "AMR machine learning",
]

# Agencies of interest (exclude NIH — handled by nih.py via Grants.gov HHS-NIH11 filter)
TARGET_AGENCIES = {"HHS", "BARDA", "NSF", "DOD"}
EXCLUDED_AGENCIES = {"HHS-NIH", "HHS-NIH11", "NIH", "NIAID"}


class GrantsGovCollector(BaseCollector):
    name = "grants_gov"

    def collect(self) -> List[Grant]:
        grants: List[Grant] = []
        seen_ids: set = set()

        for keyword in SEARCH_KEYWORDS:
            try:
                fetched = self._search(keyword, seen_ids)
                grants.extend(fetched)
                logger.info("[grants_gov] Keyword '%s' -> %d new grants", keyword, len(fetched))
            except Exception as exc:
                logger.error("[grants_gov] Error searching '%s': %s", keyword, exc)

        # Second pass: enrich each grant with full description from detail endpoint
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "grant_hunter/1.0",
        })
        for grant in grants:
            try:
                detail = self._fetch_detail(session, grant.id)
                if detail:
                    synopsis_desc = detail.get("synopsis", {}).get("synopsisDesc", "")
                    if synopsis_desc and len(synopsis_desc) > len(grant.description or ""):
                        grant.description = str(synopsis_desc)[:5000]

                    award_floor = self._safe_float(detail.get("synopsis", {}).get("awardFloor", 0))
                    award_ceiling = self._safe_float(detail.get("synopsis", {}).get("awardCeiling", 0))
                    if award_floor and not grant.amount_min:
                        grant.amount_min = award_floor
                    if award_ceiling and not grant.amount_max:
                        grant.amount_max = award_ceiling
            except Exception as exc:
                logger.debug("[grants_gov] Detail enrich failed for %s: %s", grant.id, exc)
            time.sleep(0.3)

        raw_count = len(grants)
        grants = _amr_ai_post_filter(grants)
        logger.info("[grants_gov] Total collected: %d unique grants (%d passed AMR+AI filter)", raw_count, len(grants))
        return grants

    def _fetch_detail(self, session: requests.Session, opp_id: str) -> Optional[dict]:
        """Fetch full opportunity detail from the fetchOpportunity endpoint."""
        try:
            # opportunityId must be an integer; skip non-numeric IDs
            int_id = int(opp_id)
        except (ValueError, TypeError):
            return None
        try:
            resp = session.post(
                DETAIL_URL,
                json={"opportunityId": int_id},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except Exception as exc:
            logger.debug("[grants_gov] fetchOpportunity failed for %s: %s", opp_id, exc)
            return None

    def _search(self, keyword: str, seen_ids: set) -> List[Grant]:
        results: List[Grant] = []

        for page in range(1, GRANTS_GOV_MAX_PAGES + 1):
            payload = {
                "keyword": keyword,
                "rows": GRANTS_GOV_PAGE_SIZE,
                "startRecordNum": (page - 1) * GRANTS_GOV_PAGE_SIZE,
                "oppStatuses": "posted|forecasted",
            }
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "grant_hunter/1.0",
            }

            try:
                resp = requests.post(
                    GRANTS_GOV_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response else None
                if status in (401, 403):
                    logger.warning("[grants_gov] Auth required (HTTP %s) – skipping", status)
                else:
                    logger.error("[grants_gov] HTTP error page %d: %s", page, exc)
                break
            except Exception as exc:
                logger.error("[grants_gov] Request failed page %d: %s", page, exc)
                break

            # API returns either {"data": {"oppHits": [...]}} or {"oppHits": [...]}
            hits = (
                data.get("data", {}).get("oppHits", [])
                or data.get("oppHits", [])
                or []
            )
            if not hits:
                break

            for item in hits:
                grant = self._parse(item)
                if grant and grant.id not in seen_ids:
                    seen_ids.add(grant.id)
                    results.append(grant)

            total = (
                data.get("data", {}).get("hitCount", 0)
                or data.get("hitCount", 0)
                or 0
            )
            if page * GRANTS_GOV_PAGE_SIZE >= total:
                break

        return results

    def _parse(self, item: dict) -> Optional[Grant]:
        try:
            opp_id = str(item.get("id") or item.get("oppNumber") or "")
            if not opp_id:
                return None

            # Skip NIH grants — handled by nih.py collector
            agency_code = item.get("agencyCode") or ""
            if any(agency_code.startswith(exc) for exc in EXCLUDED_AGENCIES):
                return None

            title = item.get("title") or ""
            agency = item.get("agencyName") or agency_code or "US Government"
            description = item.get("synopsis") or item.get("description") or ""

            close_date = self._parse_date(item.get("closeDate") or item.get("deadlineDate"))
            award_floor = self._safe_float(item.get("awardFloor"))
            award_ceiling = self._safe_float(item.get("awardCeiling"))

            url = (
                item.get("oppNumber")
                and f"https://www.grants.gov/search-results-detail/{item['oppNumber']}"
            ) or f"https://www.grants.gov/search-results-detail/{opp_id}"

            return Grant(
                id=opp_id,
                title=title,
                agency=agency,
                source=self.name,
                deadline=close_date,
                amount_min=award_floor,
                amount_max=award_ceiling,
                duration_months=None,
                url=url,
                description=str(description)[:5000],
                keywords=[],
                raw_data=item,
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[grants_gov] parse error: %s", exc)
            return None

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        if not value:
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(str(value)[:19], fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
