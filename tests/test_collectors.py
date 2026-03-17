"""Tests for collector _parse() methods using mock data (no real HTTP calls)."""

import pytest
from datetime import datetime
from grant_hunter.collectors.nih import NIHCollector
from grant_hunter.collectors.eu_portal import EUPortalCollector
from grant_hunter.collectors.grants_gov import GrantsGovCollector
from grant_hunter.collectors.carb_x import CarbXCollector
from grant_hunter.collectors.right_foundation import RightFoundationCollector
from grant_hunter.collectors.gates_gc import GatesGCCollector
from grant_hunter.collectors.pasteur_network import PasteurNetworkCollector
from grant_hunter.collectors.google_org import GoogleOrgCollector
from grant_hunter.models import Grant


# ── NIH ───────────────────────────────────────────────────────────────────────

def test_nih_parse_returns_grant():
    collector = NIHCollector()
    item = {
        "number": "PAR-26-116",
        "title": "Machine Learning for AMR Detection",
        "agencyCode": "NIH-NIAID",
        "closeDate": "12/31/2026",
        "id": 12345,
    }
    detail = {
        "synopsis": {
            "synopsisDesc": "Using AI to detect antimicrobial resistance patterns.",
            "awardFloor": 100000,
            "awardCeiling": 500000,
        }
    }
    grant = collector._parse(item, detail=detail)
    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.id == "PAR-26-116"
    assert grant.source == "nih"
    assert grant.agency == "NIH-NIAID"
    assert grant.amount_max == 500000.0
    assert grant.amount_min == 100000.0
    assert grant.url == "https://www.grants.gov/search-results-detail/PAR-26-116"


def test_nih_parse_returns_none_without_number():
    collector = NIHCollector()
    grant = collector._parse({"title": "No ID Grant"}, detail=None)
    assert grant is None


# ── EU Portal ─────────────────────────────────────────────────────────────────

def test_eu_parse_returns_grant():
    collector = EUPortalCollector()
    item = {
        "identifier": "HORIZON-HLTH-2026-AMR-01",
        "title": "AMR Artificial Intelligence Project",
        "callTitle": "Horizon Europe Health Call",
        "deadlineDatesLong": [1893456000000],  # some future epoch ms
    }
    grant = collector._parse(item)
    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.id == "eu-HORIZON-HLTH-2026-AMR-01"
    assert grant.source == "eu"
    assert "AMR Artificial Intelligence Project" in grant.title


def test_eu_parse_returns_none_without_identifier():
    collector = EUPortalCollector()
    grant = collector._parse({"title": "No identifier item"})
    assert grant is None


# ── Grants.gov ────────────────────────────────────────────────────────────────

def test_grants_gov_parse_returns_grant():
    collector = GrantsGovCollector()
    item = {
        "id": "HHS-2024-AMR-001",
        "oppNumber": "HHS-2024-AMR-001",
        "title": "Antimicrobial Resistance Research Initiative",
        "agencyName": "Department of Health and Human Services",
        "synopsis": "Funding for AMR drug discovery using AI.",
        "closeDate": "12/31/2026",
        "awardFloor": 100000,
        "awardCeiling": 1000000,
    }
    grant = collector._parse(item)
    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.id == "HHS-2024-AMR-001"
    assert grant.source == "grants_gov"
    assert grant.amount_min == 100000.0
    assert grant.amount_max == 1000000.0


def test_grants_gov_parse_returns_none_without_id():
    collector = GrantsGovCollector()
    grant = collector._parse({"title": "No ID grant"})
    assert grant is None


# ── CARB-X (HTML scraping via BeautifulSoup section) ─────────────────────────

def test_carb_x_parse_section_returns_grant():
    from bs4 import BeautifulSoup
    collector = CarbXCollector()
    html = """
    <section class="funding-round">
        <h2><a href="/apply/round5">CARB-X Funding Round 5</a></h2>
        <p>Funding for early-stage AMR drug discovery projects.</p>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")
    section = soup.find("section")
    seen_ids: set = set()
    grant = collector._parse_section(section, "https://carb-x.org/apply/", seen_ids)
    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.source == "carb_x"
    assert grant.agency == "CARB-X"
    assert "CARB-X Funding Round 5" in grant.title


# ── RIGHT Foundation ──────────────────────────────────────────────────────────

def test_right_foundation_parse_item_returns_grant():
    from bs4 import BeautifulSoup
    collector = RightFoundationCollector()
    html = """
    <article class="rfp-item">
        <h3><a href="/rfp/2024">RIGHT Foundation RFP 2024</a></h3>
        <p>Research funding for global health challenges.</p>
    </article>
    """
    soup = BeautifulSoup(html, "html.parser")
    item = soup.find("article")
    seen_ids: set = set()
    grant = collector._parse_item(item, "https://rightfoundation.kr/en/", seen_ids)
    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.source == "right_foundation"
    assert grant.agency == "RIGHT Foundation"


# ── Gates Grand Challenges ────────────────────────────────────────────────────

def test_gates_gc_parse_challenge_returns_grant():
    from bs4 import BeautifulSoup
    collector = GatesGCCollector()
    html = """
    <article class="challenge-card">
        <h3><a href="/challenges/amr-diagnostics">AMR Diagnostics Challenge</a></h3>
        <p>Grand challenge for antimicrobial resistance diagnostics.</p>
    </article>
    """
    soup = BeautifulSoup(html, "html.parser")
    item = soup.find("article")
    seen_ids: set = set()
    grant = collector._parse_challenge(item, "https://gcgh.grandchallenges.org/", seen_ids)
    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.source == "gates_gc"
    assert grant.agency == "Gates Foundation Grand Challenges"


# ── Pasteur Network ───────────────────────────────────────────────────────────

def test_pasteur_network_parse_item_returns_grant():
    from bs4 import BeautifulSoup
    collector = PasteurNetworkCollector()
    html = """
    <div class="call-item">
        <h3><a href="/calls/spark-2024">SPARK Program 2024</a></h3>
        <p>Funding for infectious disease research.</p>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    item = soup.find("div")
    seen_ids: set = set()
    grant = collector._parse_item(item, "https://pasteur-network.org/calls/", seen_ids)
    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.source == "pasteur_network"
    assert grant.agency == "Pasteur Network"


# ── Google.org ────────────────────────────────────────────────────────────────

def test_google_org_parse_item_returns_grant():
    from bs4 import BeautifulSoup
    collector = GoogleOrgCollector()
    html = """
    <article class="challenge-card">
        <h3><a href="/impact-challenges/health">Google.org Health Impact Challenge</a></h3>
        <p>Funding for innovative global health solutions.</p>
    </article>
    """
    soup = BeautifulSoup(html, "html.parser")
    item = soup.find("article")
    seen_ids: set = set()
    grant = collector._parse_item(item, "https://www.google.org/impact-challenges/", seen_ids)
    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.source == "google_org"
    assert grant.agency == "Google.org"
