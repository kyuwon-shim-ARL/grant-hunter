"""Tests for collector _parse() methods using mock data (no real HTTP calls)."""

import pytest
from datetime import datetime
from grant_hunter.collectors.nih import NIHCollector
from grant_hunter.collectors.eu_portal import EUPortalCollector
from grant_hunter.collectors.grants_gov import GrantsGovCollector
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

