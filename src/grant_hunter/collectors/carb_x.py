"""CARB-X funding opportunity collector."""

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

CARB_X_URLS = [
    "https://carb-x.org/apply/",
    "https://carb-x.org/portfolio/",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GrantHunterBot/1.0; +https://github.com/grant_hunter)"
    )
}


class CarbXCollector(BaseCollector):
    name = "carb_x"

    def collect(self) -> List[Grant]:
        grants: List[Grant] = []
        seen_ids: set = set()

        for url in CARB_X_URLS:
            try:
                fetched = self._fetch_page(url, seen_ids)
                grants.extend(fetched)
                logger.info("[carb_x] %s -> %d grants", url, len(fetched))
                time.sleep(1)
            except Exception as exc:
                logger.error("[carb_x] Error fetching %s: %s", url, exc)

        logger.info("[carb_x] Total collected: %d grants", len(grants))
        return grants

    def _fetch_page(self, url: str, seen_ids: set) -> List[Grant]:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        grants = []

        # Try to find funding round / call sections
        # CARB-X apply page typically lists funding rounds with titles and deadlines
        for section in soup.find_all(["article", "section", "div"], class_=lambda c: c and any(
            kw in c.lower() for kw in ["funding", "round", "call", "apply", "opportunity", "grant"]
        )):
            grant = self._parse_section(section, url, seen_ids)
            if grant:
                grants.append(grant)

        # Fallback: look for heading + paragraph pairs
        if not grants:
            grants = self._parse_headings(soup, url, seen_ids)

        return grants

    def _parse_section(self, section, base_url: str, seen_ids: set) -> Optional[Grant]:
        try:
            heading = section.find(["h1", "h2", "h3", "h4"])
            title = heading.get_text(strip=True) if heading else ""
            if not title or len(title) < 5:
                return None

            link_tag = section.find("a", href=True)
            detail_url = urljoin(base_url, link_tag["href"]) if link_tag else base_url

            grant_id = f"carb_x::{hashlib.md5((detail_url + title).encode()).hexdigest()[:12]}"
            if grant_id in seen_ids:
                return None
            seen_ids.add(grant_id)

            desc_tag = section.find("p")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            deadline = self._extract_deadline(section.get_text())

            return Grant(
                id=grant_id,
                title=title,
                agency="CARB-X",
                source=self.name,
                url=detail_url,
                description=description[:2000],
                deadline=deadline,
                keywords=["AMR", "antibiotic", "antimicrobial resistance", "CARB-X"],
                raw_data={"scraped_from": base_url},
                fetched_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.debug("[carb_x] parse_section error: %s", exc)
            return None

    def _parse_headings(self, soup: BeautifulSoup, base_url: str, seen_ids: set) -> List[Grant]:
        grants = []
        for heading in soup.find_all(["h2", "h3"]):
            title = heading.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            # Only include headings that look like funding opportunities
            lower = title.lower()
            if not any(kw in lower for kw in ["fund", "round", "call", "grant", "award", "rfp", "apply"]):
                continue

            link_tag = heading.find("a", href=True) or heading.find_next("a", href=True)
            detail_url = urljoin(base_url, link_tag["href"]) if link_tag else base_url

            grant_id = f"carb_x::{hashlib.md5((detail_url + title).encode()).hexdigest()[:12]}"
            if grant_id in seen_ids:
                continue
            seen_ids.add(grant_id)

            # Get next sibling paragraph as description
            desc = ""
            nxt = heading.find_next_sibling()
            if nxt and nxt.name == "p":
                desc = nxt.get_text(strip=True)

            grants.append(Grant(
                id=grant_id,
                title=title,
                agency="CARB-X",
                source=self.name,
                url=detail_url,
                description=desc[:2000],
                keywords=["AMR", "antibiotic", "antimicrobial resistance", "CARB-X"],
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
