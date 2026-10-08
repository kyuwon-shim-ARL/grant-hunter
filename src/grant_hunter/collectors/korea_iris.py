"""Korean domestic R&D announcement collector via IRIS (범부처통합연구지원시스템).

Verified keyless source (confirmed live by direct HTTP probing, see commit
history / PR notes for the full write-up):

1. GET https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do
   with a browser User-Agent to obtain session cookies.
2. POST https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituList.do,
   headers ``X-Requested-With: XMLHttpRequest``, Referer = the view URL,
   form data ``pageIndex=<n>&ancmPrg=<ancmIng|ancmPre>``. Returns JSON with
   ``paginationInfo`` (totalRecordCount/totalPageCount/currentPageNo) and
   ``listBsnsAncmBtinSitu`` (10 items per page).
3. Detail page: GET
   https://www.iris.go.kr/contents/retrieveBsnsAncmView.do?ancmId=<id>&ancmPrg=<prg>
   (confirmed to return HTTP 200 with the announcement content via query
   params, even though the site's own JS submits this as a POST form).

No hard keyword gate is applied here — collect ALL open (ancmIng) and
upcoming (ancmPre) announcements; relevance scoring/filtering is the
downstream job of filters.py.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import List, Optional

import requests

from grant_hunter.collectors.base import BaseCollector
from grant_hunter.config import REQUEST_TIMEOUT
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

IRIS_LIST_VIEW_URL = "https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do"
IRIS_LIST_URL = "https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituList.do"
IRIS_DETAIL_URL = "https://www.iris.go.kr/contents/retrieveBsnsAncmView.do"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# ancmPrg values: ancmIng=접수중(open), ancmPre=예정(upcoming), ancmEnd=마감(closed)
ANCM_PRG_VALUES = ("ancmIng", "ancmPre")

PAGE_SLEEP = 0.3  # seconds between page requests (be polite)
MAX_PAGES = 50  # safety cap

# Noise filtering: IRIS 접수예정(ancmPre) listings carry a lot of stale/junk
# rows (test announcements, years-old reports with no live department/deadline,
# sentinel "9999.12.31" deadlines, and lifecycle paperwork that isn't a new
# call for proposals). Filter these out at parse time.
_TEST_TITLE_RE = re.compile(r"(?i)\btest\b|테스트")
_NON_CALL_TITLE_PATTERNS = ("연차실적계획서", "단계보고서", "연차보고서", "선정결과")
_LEADING_YEAR_RE = re.compile(r"^\(?(\d{4})년")


class KoreaIRISCollector(BaseCollector):
    name = "korea"

    def collect(self) -> List[Grant]:
        grants: List[Grant] = []
        seen_ids: set = set()

        for ancm_prg in ANCM_PRG_VALUES:
            try:
                items = self._fetch_ancm_prg(ancm_prg)
            except Exception as exc:
                logger.error("[korea] Error fetching ancmPrg=%s: %s", ancm_prg, exc)
                continue

            for item in items:
                ancm_id = item.get("ancmId")
                if not ancm_id or ancm_id in seen_ids:
                    continue
                seen_ids.add(ancm_id)

                grant = self._parse_item(item)
                if grant:
                    grants.append(grant)

        logger.info("[korea] Total collected: %d unique announcements", len(grants))
        return grants

    def _fetch_ancm_prg(self, ancm_prg: str) -> List[dict]:
        """Fetch all pages of announcements for a given ancmPrg status."""
        try:
            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})
            session.get(IRIS_LIST_VIEW_URL, timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            logger.error("[korea] Failed to establish session: %s", exc)
            return []

        items: List[dict] = []
        page = 1
        total_pages = 1

        while page <= total_pages and page <= MAX_PAGES:
            try:
                resp = session.post(
                    IRIS_LIST_URL,
                    data={"pageIndex": page, "ancmPrg": ancm_prg},
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": IRIS_LIST_VIEW_URL,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error(
                    "[korea] Failed to fetch ancmPrg=%s page=%d: %s", ancm_prg, page, exc
                )
                break

            page_items = data.get("listBsnsAncmBtinSitu", []) or []
            items.extend(page_items)

            pagination = data.get("paginationInfo", {}) or {}
            total_pages = pagination.get("totalPageCount", page) or page

            if not page_items:
                break

            # Early stop: ancmPre (접수예정) can carry tens of thousands of
            # historical/test records behind the live upcoming ones (observed
            # totalPageCount in the hundreds). Once we hit a page that is
            # entirely noise (see _is_noise), we've run past the live window
            # into pure backlog — stop paginating rather than crawl it all.
            if all(self._is_noise(it) for it in page_items):
                logger.info(
                    "[korea] ancmPrg=%s page=%d is all noise — stopping pagination",
                    ancm_prg, page,
                )
                break

            page += 1
            if page <= total_pages:
                time.sleep(PAGE_SLEEP)

        return items

    def _parse_item(self, item: dict) -> Optional[Grant]:
        try:
            ancm_id = item.get("ancmId")
            if not ancm_id:
                return None

            if self._is_noise(item):
                return None

            title = item.get("ancmTl", "") or ""
            agency_dept = item.get("blngGovdSeNm", "") or ""
            agency_org = item.get("sorgnNm", "") or ""
            agency = "/".join(filter(None, [agency_dept, agency_org])) or "IRIS"

            ancm_prg = "ancmPre" if item.get("rcveSttSeNmLst") == "접수예정" else "ancmIng"

            deadline = self._parse_date(item.get("rcveEndDe"))

            url = f"{IRIS_DETAIL_URL}?ancmId={ancm_id}&ancmPrg={ancm_prg}"

            desc_parts = [
                f"공고번호: {item.get('ancmNo', '')}",
                f"공모유형: {item.get('pbofrTpSeNmLst', '')}",
                f"접수기간: {item.get('rcveStrDe', '')} ~ {item.get('rcveEndDe', '')}",
            ]
            description = " | ".join(p for p in desc_parts if p)

            return Grant(
                id=f"korea-{ancm_id}",
                title=title,
                agency=agency,
                source=self.name,
                deadline=deadline,
                amount_min=None,
                amount_max=None,
                duration_months=None,
                url=url,
                description=description,
                keywords=[],
                raw_data=item,
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[korea] parse error: %s | item: %s", exc, str(item)[:200])
            return None

    @staticmethod
    def _is_noise(item: dict) -> bool:
        """Return True for stale/test/non-call rows that should be dropped.

        IRIS 접수예정(ancmPre) in particular mixes in: literal test titles,
        years-old lifecycle paperwork (연차실적계획서/단계보고서/선정결과) with
        no live department, and a "9999.12.31" sentinel deadline used for
        stale/withdrawn announcements.
        """
        title = (item.get("ancmTl") or "").strip()
        if not title:
            return True
        if _TEST_TITLE_RE.search(title):
            return True
        if any(p in title for p in _NON_CALL_TITLE_PATTERNS):
            return True

        deadline_raw = (item.get("rcveEndDe") or "").strip()
        if deadline_raw.startswith("9999"):
            return True

        agency = item.get("blngGovdSeNm")
        if not agency:
            return True

        # Extra safety net: an explicit old-year title prefix with no
        # deadline on record is almost certainly stale leftover data.
        year_match = _LEADING_YEAR_RE.match(title)
        if year_match and not deadline_raw:
            if int(year_match.group(1)) < date.today().year:
                return True

        return False

    @staticmethod
    def _parse_date(value) -> Optional[date]:
        if not value:
            return None
        for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value).strip(), fmt).date()
            except ValueError:
                continue
        return None
