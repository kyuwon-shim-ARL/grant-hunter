"""Gates Grand Challenges collector."""

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

GATES_GC_URLS = [
    "https://gcgh.grandchallenges.org/grant-opportunities",
    "https://www.grandchallenges.org/grant-opportunities",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GrantHunterBot/1.0; +https://github.com/grant_hunter)"
    )
}

# Keywords to identify relevant challenges
RELEVANCE_KEYWORDS = [
    "antimicrobial", "antibiotic", "amr", "drug resistance",
    "infectious disease", "global health", "pathogen",
    "artificial intelligence", "machine learning", "diagnostic",
]


class GatesGCCollector(BaseCollector):
    name = "gates_gc"

    def collect(self) -> List[Grant]:
        grants: List[Grant] = []
        seen_ids: set = set()

        for url in GATES_GC_URLS:
            try:
                fetched = self._fetch_page(url, seen_ids)
                grants.extend(fetched)
                logger.info("[gates_gc] %s -> %d grants", url, len(fetched))
                time.sleep(1)
            except Exception as exc:
                logger.error("[gates_gc] Error fetching %s: %s", url, exc)

        logger.info("[gates_gc] Total collected: %d grants", len(grants))
        return grants

    def _fetch_page(self, url: str, seen_ids: set) -> List[Grant]:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        grants = []

        # Grand Challenges site lists challenges in card/article elements
        selectors = [
            ("article", None),
            ("div", lambda c: c and any(kw in c.lower() for kw in ["challenge", "grant", "opportunity", "card", "item"])),
            ("li", lambda c: c and "challenge" in (c.lower() if c else "")),
        ]

        for tag, class_filter in selectors:
            items = soup.find_all(tag, class_=class_filter) if class_filter else soup.find_all(tag)
            for item in items:
                grant = self._parse_challenge(item, url, seen_ids)
                if grant:
                    grants.append(grant)
                    time.sleep(0)  # placeholder for rate limiting

            if grants:
                break

        # Fallback to heading-based parsing
        if not grants:
            grants = self._parse_headings(soup, url, seen_ids)

        return grants

    def _parse_challenge(self, item, base_url: str, seen_ids: set) -> Optional[Grant]:
        try:
            heading = item.find(["h1", "h2", "h3", "h4"])
            title = heading.get_text(strip=True) if heading else ""
            if not title or len(title) < 5:
                return None

            link_tag = item.find("a", href=True)
            detail_url = urljoin(base_url, link_tag["href"]) if link_tag else base_url

            grant_id = f"gates_gc::{hashlib.md5((detail_url + title).encode()).hexdigest()[:12]}"
            if grant_id in seen_ids:
                return None
            seen_ids.add(grant_id)

            desc_tag = item.find("p")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            deadline = self._extract_deadline(item.get_text())

            return Grant(
                id=grant_id,
                title=title,
                agency="Gates Foundation Grand Challenges",
                source=self.name,
                url=detail_url,
                description=description[:2000],
                deadline=deadline,
                keywords=["Grand Challenges", "Gates Foundation", "global health"],
                raw_data={"scraped_from": base_url},
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[gates_gc] parse_challenge error: %s", exc)
            return None

    def _parse_headings(self, soup: BeautifulSoup, base_url: str, seen_ids: set) -> List[Grant]:
        grants = []
        for heading in soup.find_all(["h2", "h3"]):
            title = heading.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            link_tag = heading.find("a", href=True) or heading.find_next("a", href=True)
            detail_url = urljoin(base_url, link_tag["href"]) if link_tag else base_url

            grant_id = f"gates_gc::{hashlib.md5((detail_url + title).encode()).hexdigest()[:12]}"
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
                agency="Gates Foundation Grand Challenges",
                source=self.name,
                url=detail_url,
                description=desc[:2000],
                keywords=["Grand Challenges", "Gates Foundation", "global health"],
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
