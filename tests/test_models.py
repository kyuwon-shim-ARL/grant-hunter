"""Tests for Grant model."""

import pytest
from datetime import date, datetime
from grant_hunter.models import Grant
from tests.conftest import make_grant


def test_fingerprint_returns_consistent_hash():
    grant = make_grant(id="TEST-001", source="nih")
    fp1 = grant.fingerprint()
    fp2 = grant.fingerprint()
    assert fp1 == fp2
    assert fp1 == "nih::TEST-001"


def test_two_identical_grants_same_fingerprint():
    g1 = make_grant(id="SAME-001", source="eu")
    g2 = make_grant(id="SAME-001", source="eu")
    assert g1.fingerprint() == g2.fingerprint()


def test_two_different_grants_different_fingerprints():
    g1 = make_grant(id="DIFF-001", source="nih")
    g2 = make_grant(id="DIFF-002", source="nih")
    assert g1.fingerprint() != g2.fingerprint()


def test_grant_serialization_deserialization():
    original = make_grant(
        id="SER-001",
        title="Serialization Test",
        agency="NIH",
        source="nih",
        url="https://example.com/grant",
        description="Test description",
        deadline=date(2026, 12, 31),
        amount_min=100_000.0,
        amount_max=500_000.0,
        duration_months=24,
        keywords=["AMR", "AI"],
    )
    d = original.to_dict()
    restored = Grant.from_dict(d)

    assert restored.id == original.id
    assert restored.title == original.title
    assert restored.source == original.source
    assert restored.deadline == original.deadline
    assert restored.amount_min == original.amount_min
    assert restored.amount_max == original.amount_max
    assert restored.duration_months == original.duration_months
    assert restored.keywords == original.keywords
