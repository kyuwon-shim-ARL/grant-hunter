"""Tests for the Korean IRIS (범부처통합연구지원시스템) 사업공고 collector.

IRIS is a keyless, verified-live source (see collectors/korea_iris.py module
docstring): a session GET followed by an XHR POST returning JSON. These
tests exercise `_parse_item`, pagination across `ancmIng`/`ancmPre`, dedupe
by `ancmId`, and graceful failure handling against a saved fixture / mocked
responses — they do not hit the real network.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grant_hunter.collectors.korea_iris import KoreaIRISCollector
from grant_hunter.models import Grant

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "iris_list_page1.json"


@pytest.fixture
def fixture_page() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def collector():
    return KoreaIRISCollector()


# ── _parse_item ──────────────────────────────────────────────────────────

def test_parse_item_returns_grant_with_standard_fields(collector, fixture_page):
    item = fixture_page["listBsnsAncmBtinSitu"][0]
    grant = collector._parse_item(item)

    assert grant is not None
    assert isinstance(grant, Grant)
    assert grant.id == f"korea-{item['ancmId']}"
    assert grant.source == "korea"
    assert grant.title == item["ancmTl"]
    assert grant.agency == f"{item['blngGovdSeNm']}/{item['sorgnNm']}"
    assert grant.deadline is not None
    assert grant.deadline.isoformat() == "2026-10-20"
    assert grant.url == (
        "https://www.iris.go.kr/contents/retrieveBsnsAncmView.do"
        f"?ancmId={item['ancmId']}&ancmPrg=ancmIng"
    )
    assert item["ancmNo"] in grant.description
    assert item["pbofrTpSeNmLst"] in grant.description
    assert item["rcveStrDe"] in grant.description
    assert item["rcveEndDe"] in grant.description


def test_parse_item_missing_ancm_id_returns_none(collector):
    item = {"ancmTl": "제목만 있음"}
    assert collector._parse_item(item) is None


# ── noise filtering (ancmPre junk: test rows, stale reports, 9999 sentinel) ──

@pytest.mark.parametrize(
    "item",
    [
        {"ancmId": "1", "ancmTl": "TEST", "blngGovdSeNm": None, "rcveEndDe": None},
        {"ancmId": "2", "ancmTl": "test", "blngGovdSeNm": None, "rcveEndDe": None},
        {
            "ancmId": "3",
            "ancmTl": "(TEST) KISTEP  통합공고 테스트 입니다.  ",
            "blngGovdSeNm": "과학기술정보통신부",
            "rcveEndDe": "2027.12.31",
        },
        {
            "ancmId": "4",
            "ancmTl": "2026년도 투·융자 연계 기술개발사업 지원계획 수정 공고",
            "blngGovdSeNm": None,
            "rcveEndDe": None,
        },
        {
            "ancmId": "5",
            "ancmTl": "2024년도 STEAM연구 사업 하반기 신규과제 재공고",
            "blngGovdSeNm": "과학기술정보통신부",
            "rcveEndDe": "9999.12.31",
        },
        {
            "ancmId": "6",
            "ancmTl": "2024년_국민생활안전긴급대응연구사업_2022년 선정_1단계3연차_연차실적계획서 접수",
            "blngGovdSeNm": None,
            "rcveEndDe": None,
        },
        {
            "ancmId": "7",
            "ancmTl": "2024년도_단계보고서 접수",
            "blngGovdSeNm": "과학기술정보통신부",
            "rcveEndDe": None,
        },
    ],
)
def test_parse_item_drops_noise_rows(collector, item):
    assert collector._parse_item(item) is None


def test_parse_item_keeps_legit_row_with_old_year_prefix_but_live_deadline(collector):
    # Old-year title prefix alone should NOT drop a row that has a real
    # department and a real (non-sentinel) deadline on record.
    item = {
        "ancmId": "8",
        "ancmTl": "2024년도 바이오·의료기술개발사업 신규과제 공모",
        "blngGovdSeNm": "보건복지부",
        "sorgnNm": "한국보건산업진흥원",
        "rcveStrDe": "2026.10.01",
        "rcveEndDe": "2026.10.20",
        "ancmNo": "x",
        "pbofrTpSeNmLst": "자유공모",
    }
    assert collector._parse_item(item) is not None


# ── pagination ───────────────────────────────────────────────────────────

def test_fetch_prg_paginates_until_all_pages_collected(collector, fixture_page):
    page2 = dict(fixture_page)
    page2["paginationInfo"] = dict(fixture_page["paginationInfo"], currentPageNo=2)
    page2["listBsnsAncmBtinSitu"] = [
        {**item, "ancmId": f"{item['ancmId']}-p2"}
        for item in fixture_page["listBsnsAncmBtinSitu"]
    ]
    page3 = dict(fixture_page)
    page3["paginationInfo"] = dict(fixture_page["paginationInfo"], currentPageNo=3)
    page3["listBsnsAncmBtinSitu"] = fixture_page["listBsnsAncmBtinSitu"][:2]

    responses = [fixture_page, page2, page3]

    def fake_post(*args, **kwargs):
        resp = MagicMock()
        resp.json.return_value = responses.pop(0)
        resp.raise_for_status.return_value = None
        return resp

    with patch("grant_hunter.collectors.korea_iris.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.post.side_effect = fake_post
        mock_session.get.return_value = MagicMock(status_code=200)
        mock_session_cls.return_value = mock_session

        items = collector._fetch_ancm_prg("ancmIng")

    assert len(items) == 22  # 10 + 10 + 2 across 3 pages


# ── collect(): both ancmIng + ancmPre, dedupe ───────────────────────────────

def test_collect_merges_ancming_and_ancmpre_and_dedupes(collector, fixture_page):
    dup_item = fixture_page["listBsnsAncmBtinSitu"][0]
    ancm_pre_page = {
        "paginationInfo": {"currentPageNo": 1, "totalPageCount": 1},
        "listBsnsAncmBtinSitu": [dup_item],  # same ancmId as in ancmIng fixture
    }

    def fake_fetch(ancm_prg):
        if ancm_prg == "ancmIng":
            return fixture_page["listBsnsAncmBtinSitu"]
        return ancm_pre_page["listBsnsAncmBtinSitu"]

    with patch.object(collector, "_fetch_ancm_prg", side_effect=fake_fetch):
        grants = collector.collect()

    ids = [g.id for g in grants]
    assert len(ids) == len(set(ids))  # no duplicates
    assert len(grants) == 10  # only the 10 unique items from ancmIng fixture


# ── graceful failure ─────────────────────────────────────────────────────

def test_fetch_ancm_prg_returns_empty_on_non_json_response(collector):
    with patch("grant_hunter.collectors.korea_iris.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        bad_resp = MagicMock()
        bad_resp.json.side_effect = ValueError("not json")
        bad_resp.raise_for_status.return_value = None
        mock_session.post.return_value = bad_resp
        mock_session.get.return_value = MagicMock(status_code=200)
        mock_session_cls.return_value = mock_session

        items = collector._fetch_ancm_prg("ancmIng")

    assert items == []


def test_fetch_ancm_prg_returns_empty_on_http_500(collector):
    import requests as real_requests

    with patch("grant_hunter.collectors.korea_iris.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = real_requests.HTTPError("500")
        mock_session.post.return_value = bad_resp
        mock_session.get.return_value = MagicMock(status_code=200)
        mock_session_cls.return_value = mock_session

        items = collector._fetch_ancm_prg("ancmIng")

    assert items == []


def test_fetch_prg_stops_early_once_a_page_is_entirely_noise(collector, fixture_page):
    """ancmPre can carry hundreds of pages of historical/test backlog behind
    the live window. Once a full page is all-noise, pagination should stop
    rather than crawl the entire backlog."""
    noise_page_1 = {
        "paginationInfo": {"currentPageNo": 1, "totalPageCount": 500},
        "listBsnsAncmBtinSitu": [
            {"ancmId": "n1", "ancmTl": "TEST", "blngGovdSeNm": None, "rcveEndDe": None},
        ],
    }
    noise_page_2 = {
        "paginationInfo": {"currentPageNo": 2, "totalPageCount": 500},
        "listBsnsAncmBtinSitu": [
            {"ancmId": "n2", "ancmTl": "2024년도 옛 보고서", "blngGovdSeNm": None, "rcveEndDe": None},
        ],
    }
    never_reached = MagicMock()

    responses = [noise_page_1, noise_page_2, never_reached]

    def fake_post(*args, **kwargs):
        resp = MagicMock()
        resp.json.return_value = responses.pop(0)
        resp.raise_for_status.return_value = None
        return resp

    with patch("grant_hunter.collectors.korea_iris.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.post.side_effect = fake_post
        mock_session.get.return_value = MagicMock(status_code=200)
        mock_session_cls.return_value = mock_session

        items = collector._fetch_ancm_prg("ancmPre")

    assert len(items) == 1  # stopped after page 1 (already all-noise)
    assert mock_session.post.call_count == 1


def test_collect_returns_empty_list_when_both_prg_fail(collector):
    with patch.object(collector, "_fetch_ancm_prg", return_value=[]):
        grants = collector.collect()
    assert grants == []
