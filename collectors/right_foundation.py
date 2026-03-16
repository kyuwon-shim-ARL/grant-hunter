"""RIGHT Foundation funding opportunity collector."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from collectors.base import BaseCollector
from config import REQUEST_TIMEOUT
from models import Grant

logger = logging.getLogger(__name__)

RIGHT_URLS = [
    "https://rightfoundation.kr/en/funding-opportunities/",
    "https://rightfoundation.kr/en/",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GrantHunterBot/1.0; +https://github.com/grant_hunter)"
    )
}


class RightFoundationCollector(BaseCollector):
    name = "right_foundation"

    def collect(self) -> List[Grant]:
        grants: List[Grant] = []
        seen_ids: set = set()

        for url in RIGHT_URLS:
            try:
                fetched = self._fetch_page(url, seen_ids)
                grants.extend(fetched)
                logger.info("[right_foundation] %s -> %d grants", url, len(fetched))
                time.sleep(1)
            except Exception as exc:
                logger.error("[right_foundation] Error fetching %s: %s", url, exc)

        logger.info("[right_foundation] Total collected: %d grants", len(grants))
        return grants

    def _fetch_page(self, url: str, seen_ids: set) -> List[Grant]:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        grants = []

        # Look for RFP / funding opportunity entries
        for item in soup.find_all(["article", "li", "div"], class_=lambda c: c and any(
            kw in c.lower() for kw in ["rfp", "fund", "opportunit", "call", "grant", "post", "item"]
        )):
            grant = self._parse_item(item, url, seen_ids)
            if grant:
                grants.append(grant)

        if not grants:
            grants = self._parse_headings(soup, url, seen_ids)

        return grants

    def _parse_item(self, item, base_url: str, seen_ids: set) -> Optional[Grant]:
        try:
            heading = item.find(["h1", "h2", "h3", "h4", "a"])
            title = heading.get_text(strip=True) if heading else ""
            if not title or len(title) < 5:
                return None

            grant_id = f"right_foundation::{hashlib.md5((detail_url + title).encode()).hexdigest()[:12]}"
            if grant_id in seen_ids:
                return None
            seen_ids.add(grant_id)

            desc_tag = item.find("p")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            link_tag = item.find("a", href=True)
            detail_url = urljoin(base_url, link_tag["href"]) if link_tag else base_url

            deadline = self._extract_deadline(item.get_text())

            return Grant(
                id=grant_id,
                title=title,
                agency="RIGHT Foundation",
                source=self.name,
                url=detail_url,
                description=description[:2000],
                deadline=deadline,
                keywords=["AMR", "antimicrobial resistance", "Korea", "RIGHT Foundation"],
                raw_data={"scraped_from": base_url},
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[right_foundation] parse_item error: %s", exc)
            return None

    def _parse_headings(self, soup: BeautifulSoup, base_url: str, seen_ids: set) -> List[Grant]:
        grants = []
        for heading in soup.find_all(["h2", "h3", "h4"]):
            title = heading.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            lower = title.lower()
            if not any(kw in lower for kw in ["fund", "rfp", "call", "grant", "award", "opportunit"]):
                continue

            grant_id = f"right_foundation::{hashlib.md5((detail_url + title).encode()).hexdigest()[:12]}"
            if grant_id in seen_ids:
                continue
            seen_ids.add(grant_id)

            desc = ""
            nxt = heading.find_next_sibling()
            if nxt and nxt.name == "p":
                desc = nxt.get_text(strip=True)

            link_tag = heading.find("a", href=True) or heading.find_next("a", href=True)
            detail_url = urljoin(base_url, link_tag["href"]) if link_tag else base_url

            grants.append(Grant(
                id=grant_id,
                title=title,
                agency="RIGHT Foundation",
                source=self.name,
                url=detail_url,
                description=desc[:2000],
                keywords=["AMR", "antimicrobial resistance", "Korea", "RIGHT Foundation"],
                raw_data={"scraped_from": base_url},
                fetched_at=datetime.utcnow(),
            ))
        return grants

    @staticmethod
    def _extract_deadline(text: str):
        import re
        from datetime import date
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
