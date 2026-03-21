"""EU Funding & Tenders Portal collector for open/forthcoming calls.

Uses the bulk grantsTenders.json reference data file (no auth needed).
Endpoint: https://ec.europa.eu/info/funding-tenders/opportunities/data/referenceData/grantsTenders.json
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timezone
from typing import List, Optional

import requests

from grant_hunter.collectors.base import BaseCollector
from grant_hunter.config import REQUEST_TIMEOUT
from grant_hunter.filters import AMR_KEYWORDS, AI_KEYWORDS
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

GRANTS_TENDERS_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/data/referenceData/grantsTenders.json"
)

# Single source of truth: combine AMR + AI keywords from filters.py
# Deduplicate and use as pre-filter for EU collection
AMR_AI_KEYWORDS = list(set(AMR_KEYWORDS + AI_KEYWORDS))

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
            time.sleep(0.3)  # rate-limit SEDIA API calls

        logger.info("[eu] Total collected: %d relevant open/forthcoming grants", len(grants))
        return grants

    def _fetch_topics(self) -> List[dict]:
        resp = requests.get(GRANTS_TENDERS_URL, timeout=REQUEST_TIMEOUT)
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

    def _fetch_topic_detail(self, identifier: str) -> str:
        """Fetch full topic description via the SEDIA search API.

        The bulk grantsTenders.json only has short stub descriptions.
        The SEDIA API returns ``descriptionByte`` with full HTML content.
        """
        url = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
        try:
            resp = requests.post(
                url,
                data={
                    "apiKey": "SEDIA",
                    "text": f'"{identifier}"',
                    "pageSize": "30",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            # Find the English result
            for r in results:
                if r.get("language") == "en":
                    meta = r.get("metadata", {})
                    # descriptionByte has the full topic description HTML
                    desc_list = meta.get("descriptionByte", [])
                    html = desc_list[0] if desc_list else ""
                    if not html:
                        # Fallback: destinationDetails
                        dest_list = meta.get("destinationDetails", [])
                        html = dest_list[0] if dest_list else ""
                    # Strip HTML tags and collapse whitespace
                    text = re.sub(r"<[^>]+>", " ", html)
                    text = re.sub(r"\s+", " ", text).strip()
                    logger.debug("[eu] SEDIA description for %s: %d chars", identifier, len(text))
                    return text
            logger.debug("[eu] no English result in SEDIA for %s", identifier)
            return ""
        except requests.HTTPError as exc:
            logger.warning("[eu] SEDIA HTTP error for %s: %s", identifier, exc)
            return ""
        except Exception as exc:
            logger.debug("[eu] SEDIA fetch failed for %s: %s", identifier, exc)
            return ""

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

            # Fetch full description from detail endpoint; fall back to bulk-file fields
            detail_desc = self._fetch_topic_detail(identifier)
            description = detail_desc or objective or call_title or title

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

            # Budget: try multiple field paths across bulk JSON and legacy schemas
            amount_max: Optional[float] = None
            for budget_key in ("budgetOverallBudget", "budget", "totalCost", "budgetMax"):
                cost = topic.get(budget_key)
                if cost:
                    try:
                        amount_max = float(str(cost).replace(",", ""))
                        break
                    except ValueError:
                        pass
            # Also try nested budgetTopicActionList
            if amount_max is None:
                budget_list = topic.get("budgetTopicActionList") or []
                for entry in budget_list:
                    val = entry.get("budgetMax") or entry.get("budget") or entry.get("budgetTopicAction")
                    if val:
                        try:
                            amount_max = float(str(val).replace(",", ""))
                            break
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
