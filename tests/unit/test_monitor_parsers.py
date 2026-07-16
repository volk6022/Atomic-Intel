"""Unit tests for the promoted monitor parsers — run against the saved
``experiment_monitoring/*/samples`` fixtures, no network.

Each test either exercises a pure parser directly or drives ``collect()`` with the
transport mocked to return a saved sample, asserting a non-empty ``MonitorItem``
list. Tests skip cleanly when a sample file is absent so the suite is portable.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

SAMPLES = Path(__file__).resolve().parents[2] / "experiment_monitoring"


def _read(rel: str) -> str:
    p = SAMPLES / rel
    if not p.exists():
        pytest.skip(f"sample missing: {rel}")
    return p.read_text(encoding="utf-8", errors="replace")


class _Resp:
    """Minimal httpx.Response stand-in for mocking RotatingHTTPClient."""

    def __init__(self, *, content: bytes = b"", status: int = 200, text: str = "", payload=None):
        self.content = content
        self.status_code = status
        self._text = text
        self._payload = payload

    @property
    def text(self) -> str:
        return self._text

    def json(self):
        return self._payload


# --------------------------------------------------------------------------- #
# pure parsers on saved HTML
# --------------------------------------------------------------------------- #
def test_superjob_parser():
    from src.actions.monitoring.sources.superjob import _sj_extract_from_html

    rows = _sj_extract_from_html(_read("experiment-superjob/samples/search_httpx_direct.html"))
    assert len(rows) >= 10
    assert rows[0]["id"] and rows[0]["title"]


def test_habr_parser():
    from src.actions.monitoring.sources.habr import _habr_extract_ssr

    rows = _habr_extract_ssr(_read("experiment-habr/samples/listing_httpx_direct.html"))
    assert len(rows) >= 5
    assert str(rows[0].get("id"))


def test_avito_parser():
    from src.actions.monitoring.sources.avito import _avito_extract_mfe

    best: list[dict] = []
    for f in glob.glob(str(SAMPLES / "experiment-avito/samples/*.html")):
        items = _avito_extract_mfe(Path(f).read_text(encoding="utf-8", errors="replace"))
        if len(items) > len(best):
            best = items
    if not best:
        pytest.skip("no avito MFE sample yielded items")
    assert best[0]["id"] and "url" in best[0]


def test_hh_parser():
    from src.actions.monitoring.sources.hh import _hh_extract_from_json

    best: list[dict] = []
    for f in glob.glob(str(SAMPLES / "experiment-hh/samples/**/*.html"), recursive=True):
        items = _hh_extract_from_json(Path(f).read_text(encoding="utf-8", errors="replace"))
        if len(items) > len(best):
            best = items
    if not best:
        pytest.skip("no hh sample yielded vacancy JSON")
    assert best[0]["id"] and best[0]["title"] and best[0]["link"].startswith("https://hh.ru/")


def test_zarplata_parser_synthetic():
    # rabota.ru samples differ; assert the HH/Redux parser on a minimal synthetic blob.
    from src.actions.monitoring.sources.zarplata import _zp_extract_vacancies

    html = '{"vacancyId":123,"name":"Python developer","visibleName":"Acme","from":100000,"currencyCode":"RUR"}'
    rows = _zp_extract_vacancies(html)
    assert rows and rows[0]["id"] == "123" and rows[0]["title"] == "Python developer"


def test_kwork_list_parser():
    from src.actions.monitoring.sources.kwork import _kwork_list

    payload = {"data": {"pagination": {"data": [{"id": 7, "name": "Bot", "priceLimit": 500}]}}}
    assert _kwork_list(payload) == [{"id": 7, "name": "Bot", "priceLimit": 500}]


def test_fl_numeric_id():
    from src.actions.monitoring.sources.fl import _fl_numeric_id

    assert _fl_numeric_id("https://www.fl.ru/projects/5510226/nazvanie.html") == "5510226"
    assert _fl_numeric_id("https://www.fl.ru/no-match") == "https://www.fl.ru/no-match"


# --------------------------------------------------------------------------- #
# collect() with mocked transport → MonitorItem list
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_superjob_collect_items():
    from src.actions.monitoring.sources.superjob import SuperjobScraper

    s = SuperjobScraper()
    with patch.object(s, "fetch_text", AsyncMock(return_value=_read("experiment-superjob/samples/search_httpx_direct.html"))):
        items = await s.collect(limit=10)
    assert items and all(i.source == "superjob" for i in items)
    assert items[0].id and items[0].title


@pytest.mark.asyncio
async def test_habr_collect_items():
    from src.actions.monitoring.sources.habr import HabrScraper

    s = HabrScraper()
    with patch.object(s, "fetch_text", AsyncMock(return_value=_read("experiment-habr/samples/listing_httpx_direct.html"))):
        items = await s.collect(limit=10)
    assert items and items[0].source == "habr" and items[0].url.startswith("https://career.habr.com")


@pytest.mark.asyncio
async def test_avito_collect_items():
    from src.actions.monitoring.sources.avito import AvitoScraper

    # pick a sample that yields MFE items
    from src.actions.monitoring.sources.avito import _avito_extract_mfe
    html = ""
    for f in glob.glob(str(SAMPLES / "experiment-avito/samples/*.html")):
        candidate = Path(f).read_text(encoding="utf-8", errors="replace")
        if _avito_extract_mfe(candidate):
            html = candidate
            break
    if not html:
        pytest.skip("no avito MFE sample")
    s = AvitoScraper()
    with patch.object(s, "fetch_text", AsyncMock(return_value=html)):
        items = await s.collect(limit=10)
    assert items and items[0].source == "avito"


@pytest.mark.asyncio
async def test_hh_collect_items():
    from src.actions.monitoring.sources.hh import HHScraper, _hh_extract_from_json

    html = ""
    for f in glob.glob(str(SAMPLES / "experiment-hh/samples/**/*.html"), recursive=True):
        candidate = Path(f).read_text(encoding="utf-8", errors="replace")
        if _hh_extract_from_json(candidate):
            html = candidate
            break
    if not html:
        pytest.skip("no hh sample with vacancy JSON")
    s = HHScraper()
    with patch.object(s, "_browser_get", AsyncMock(return_value=html)):
        items = await s.collect(limit=10)
    assert items and items[0].source == "hh"


@pytest.mark.asyncio
async def test_fl_collect_items():
    from src.actions.monitoring.sources.fl import FLScraper

    rss_path = SAMPLES / "experiment-fl/samples/fl_rss_base.xml"
    if not rss_path.exists():
        pytest.skip("fl rss sample missing")
    rss = rss_path.read_bytes()
    s = FLScraper()
    with patch.object(s.http, "get", AsyncMock(return_value=_Resp(content=rss, status=200))):
        items = await s.collect(limit=20)
    assert items and all(i.source == "fl" for i in items)
    assert items[0].id and items[0].url


@pytest.mark.asyncio
async def test_youdo_collect_items():
    from src.actions.monitoring.sources.youdo import YoudoScraper

    payload = json.loads(_read("experiment-youdo/samples/httpx/api_it_opened_p1.json"))
    s = YoudoScraper()
    with patch.object(s, "fetch_json", AsyncMock(return_value=payload)):
        items = await s.collect(limit=10)
    assert items and items[0].source == "youdo" and items[0].url.startswith("https://youdo.com")


@pytest.mark.asyncio
async def test_kwork_collect_items():
    from src.actions.monitoring.sources.kwork import KworkScraper

    payload = {"data": {"pagination": {"data": [
        {"id": 101, "name": "Telegram bot", "priceLimit": 1500, "description": "парсинг"},
        {"id": 102, "name": "ML pipeline", "possiblePriceLimit": 5000},
    ]}}}
    s = KworkScraper()
    with patch.object(s, "fetch_json", AsyncMock(return_value=payload)):
        items = await s.collect(limit=10)
    assert items and items[0].source == "kwork"
    assert {i.id for i in items} == {"101", "102"}
