"""Shared fixtures for grant_hunter tests."""

import pytest
from datetime import date, datetime
from grant_hunter.models import Grant


def make_grant(
    id="test-001",
    title="Test Grant",
    agency="Test Agency",
    source="nih",
    url="https://example.com",
    description="",
    deadline=None,
    amount_min=None,
    amount_max=None,
    duration_months=None,
    keywords=None,
    raw_data=None,
    relevance_score=0.0,
):
    return Grant(
        id=id,
        title=title,
        agency=agency,
        source=source,
        url=url,
        description=description,
        deadline=deadline,
        amount_min=amount_min,
        amount_max=amount_max,
        duration_months=duration_months,
        keywords=keywords or [],
        raw_data=raw_data or {},
        fetched_at=datetime(2026, 3, 17, 0, 0, 0),
        relevance_score=relevance_score,
    )


@pytest.fixture
def basic_grant():
    return make_grant(
        id="BASIC-001",
        title="Basic Research Grant",
        agency="NIH",
        source="nih",
        description="A basic research grant for testing purposes.",
    )


@pytest.fixture
def amr_ai_grant():
    return make_grant(
        id="AMR-AI-001",
        title="Machine learning approaches to antimicrobial resistance",
        agency="NIH",
        source="nih",
        description=(
            "This grant funds artificial intelligence and deep learning research "
            "on antimicrobial resistance and antibiotic resistance drug discovery."
        ),
        amount_max=2_000_000.0,
    )


@pytest.fixture
def lmic_grant():
    return make_grant(
        id="LMIC-001",
        title="Grant for LMIC countries",
        agency="WHO",
        source="eu",
        description="Open to developing countries and low-income nations only.",
    )
