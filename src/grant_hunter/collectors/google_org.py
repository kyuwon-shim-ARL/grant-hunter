"""Google.org Impact Challenges collector."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from grant_hunter.collectors.base import BaseCollector
from grant_hunter.config import REQUEST_TIMEOUT
from grant_hunter.models import Grant

logger = logging.getLogger(__name__)

GOOGLE_ORG_URLS = [
    "https://www.google.org/impact-challenges/",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GrantHunterBot/1.0; +https://github.com/grant_hunter)"
    )
}


class GoogleOrgCollector(BaseCollector):
    name = "google_org"

    def collect(self) -> List[Grant]:
        grants: List[Grant] = []
        seen_ids: set = set()

        for url in GOOGLE_ORG_URLS:
            try:
                fetched = self._fetch_page(url, seen_ids)
                grants.extend(fetched)
                logger.info("[google_org] %s -> %d grants", url, len(fetched))
                time.sleep(1)
            except Exception as exc:
                logger.error("[google_org] Error fetching %s: %s", url, exc)

        logger.info("[google_org] Total collected: %d grants", len(grants))
        return grants

    def _fetch_page(self, url: str, seen_ids: set) -> List[Grant]:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        grants = []

        # Google.org challenge pages list challenges in cards / article elements
        for item in soup.find_all(["article", "div", "section"], class_=lambda c: c and any(
            kw in c.lower() for kw in ["challenge", "impact", "grant", "fund", "card", "item", "opportunity"]
        )):
            grant = self._parse_item(item, url, seen_ids)
            if grant:
                grants.append(grant)

        if not grants:
            grants = self._parse_headings(soup, url, seen_ids)

        return grants

    def _parse_item(self, item, base_url: str, seen_ids: set) -> Optional[Grant]:
        try:
            heading = item.find(["h1", "h2", "h3", "h4"])
            title = heading.get_text(strip=True) if heading else ""
            if not title or len(title) < 5:
                return None

            link_tag = item.find("a", href=True)
            detail_url = urljoin(base_url, link_tag["href"]) if link_tag else base_url

            grant_id = f"google_org::{hashlib.md5((detail_url + title).encode()).hexdigest()[:12]}"
            if grant_id in seen_ids:
                return None
            seen_ids.add(grant_id)

            desc_tag = item.find("p")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            deadline = self._extract_deadline(item.get_text())

            return Grant(
                id=grant_id,
                title=title,
                agency="Google.org",
                source=self.name,
                url=detail_url,
                description=description[:2000],
                deadline=deadline,
                keywords=["Google.org", "impact challenge", "technology", "global health"],
                raw_data={"scraped_from": base_url},
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[google_org] parse_item error: %s", exc)
            return None

    def _parse_headings(self, soup: BeautifulSoup, base_url: str, seen_ids: set) -> List[Grant]:
        grants = []
        for heading in soup.find_all(["h2", "h3"]):
            title = heading.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            lower = title.lower()
            if not any(kw in lower for kw in ["challenge", "impact", "fund", "grant", "award", "opportunit"]):
                continue

            link_tag = heading.find("a", href=True) or heading.find_next("a", href=True)
            detail_url = urljoin(base_url, link_tag["href"]) if link_tag else base_url

            grant_id = f"google_org::{hashlib.md5((detail_url + title).encode()).hexdigest()[:12]}"
            if grant_id in seen_ids:
                continue
            seen_ids.add(grant_id)

            desc = ""
            nxt = heading.find_next_sibling()
            if nxt and nxt.name == "p":
                desc = nxt.get_text(strip=True)

            grants.append(Grant(
                id=grant_id,
                title=title,
                agency="Google.org",
                source=self.name,
                url=detail_url,
                description=desc[:2000],
                keywords=["Google.org", "impact challenge", "technology", "global health"],
                raw_data={"scraped_from": base_url},
                fetched_at=datetime.utcnow(),
            ))
        return grants

    @staticmethod
    def _extract_deadline(text: str):
        import re
        patterns = [
            r"(?:deadline|due|closes?|submit by)[:\s]+(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{1,2}/\d{1,2}/\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                raw = m.group(1)
                for fmt in ("%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(raw.strip(), fmt).date()
                    except ValueError:
                        continue
        return None
