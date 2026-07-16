"""Contract tests for the monitoring API — in-process via ASGITransport, action mocked."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.domain.models.monitoring import MonitorItem

_HEADERS = {"X-API-Key": "default_internal_key"}


def _client() -> AsyncClient:
    from src.api.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _FakeScraper:
    async def collect(self, limit=25):
        return [MonitorItem(source="fl", id="1", title="Python bot", url="https://fl.ru/projects/1")]

    async def detail(self, item):
        return {"id": item["id"], "title": "Python bot", "url": item.get("url", "")}


async def test_collect_returns_200_and_shape():
    with patch("src.api.routers.monitoring.get_scraper", return_value=_FakeScraper()):
        async with _client() as client:
            resp = await client.post("/api/v1/monitor/fl/collect", headers=_HEADERS, json={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert {"source", "total", "items"} <= data.keys()
    assert data["source"] == "fl" and data["total"] == 1
    assert data["items"][0]["source"] == "fl"


async def test_detail_returns_200():
    with patch("src.api.routers.monitoring.get_scraper", return_value=_FakeScraper()):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/monitor/fl/detail", headers=_HEADERS,
                json={"item": {"id": "1", "url": "https://fl.ru/projects/1"}},
            )
    assert resp.status_code == 200
    assert resp.json()["item"]["id"] == "1"


async def test_unknown_source_returns_404():
    async with _client() as client:
        resp = await client.post("/api/v1/monitor/nope/collect", headers=_HEADERS, json={"limit": 5})
    assert resp.status_code == 404


async def test_missing_api_key_returns_403():
    async with _client() as client:
        resp = await client.post("/api/v1/monitor/fl/collect", json={"limit": 5})
    assert resp.status_code == 403


async def test_sources_lists_all_eight():
    async with _client() as client:
        resp = await client.get("/api/v1/monitor/sources", headers=_HEADERS)
    assert resp.status_code == 200
    sources = set(resp.json()["sources"])
    assert {"hh", "avito", "superjob", "habr", "zarplata", "fl", "kwork", "youdo"} <= sources
