"""NIH Reporter API collector."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import List, Optional

import requests

from collectors.base import BaseCollector
from config import NIH_API_URL, NIH_PAGE_SIZE, NIH_MAX_PAGES, REQUEST_TIMEOUT
from models import Grant

logger = logging.getLogger(__name__)

# Keywords to search in NIH Reporter
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
                logger.info("[nih] Term '%s' -> %d new grants", term, len(fetched))
            except Exception as exc:
                logger.error("[nih] Error searching '%s': %s", term, exc)

        logger.info("[nih] Total collected: %d unique grants", len(grants))
        return grants

    def _search(self, term: str, seen_ids: set) -> List[Grant]:
        results: List[Grant] = []

        for page in range(NIH_MAX_PAGES):
            offset = page * NIH_PAGE_SIZE
            payload = {
                "criteria": {
                    "advanced_text_search": {
                        "operator": "and",
                        "search_field": "all",
                        "search_text": term,
                    }
                },
                "include_fields": [
                    "ProjectNum",
                    "ProjectTitle",
                    "AbstractText",
                    "Organization",
                    "AgencyCode",
                    "FiscalYear",
                    "AwardAmount",
                    "ProjectStartDate",
                    "ProjectEndDate",
                    "ProjectDetailUrl",
                    "Terms",
                    "PrincipalInvestigators",
                ],
                "offset": offset,
                "limit": NIH_PAGE_SIZE,
                "sort_field": "project_start_date",
                "sort_order": "desc",
            }

            resp = requests.post(
                NIH_API_URL,
                json=payload,
                timeout=REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            hits = data.get("results", [])
            if not hits:
                break

            for item in hits:
                grant = self._parse(item)
                if grant and grant.id not in seen_ids:
                    seen_ids.add(grant.id)
                    results.append(grant)

            total = data.get("meta", {}).get("total", 0)
            if offset + NIH_PAGE_SIZE >= total:
                break

        return results

    def _parse(self, item: dict) -> Optional[Grant]:
        try:
            project_num = item.get("project_num") or item.get("ProjectNum", "")
            if not project_num:
                return None

            title = item.get("project_title") or item.get("ProjectTitle", "") or ""
            abstract = item.get("abstract_text") or item.get("AbstractText", "") or ""

            org = item.get("organization", {}) or {}
            agency_name = org.get("org_name", "") or item.get("agency_code", "") or "NIH"

            award_amt = item.get("award_amount") or 0
            amount_val = float(award_amt) if award_amt else None

            end_date = self._parse_date(item.get("project_end_date"))
            start_date = self._parse_date(item.get("project_start_date"))

            duration = None
            if start_date and end_date:
                months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
                duration = max(1, months)

            url = item.get("project_detail_url") or f"https://reporter.nih.gov/project-details/{project_num}"

            terms_raw = item.get("terms", "") or ""
            kw_list = [t.strip() for t in terms_raw.split(";") if t.strip()]

            return Grant(
                id=project_num,
                title=title,
                agency=agency_name,
                source=self.name,
                deadline=end_date,
                amount_min=amount_val,
                amount_max=amount_val,
                duration_months=duration,
                url=url,
                description=abstract[:2000],
                keywords=kw_list[:20],
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
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(str(value)[:19], fmt).date()
            except ValueError:
                continue
        return None
