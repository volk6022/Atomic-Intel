"""E2E tests for the Yandex Maps full extraction flow.

The live-network test (`test_yandex_maps_endpoint_returns_organizations`) is
marked `@pytest.mark.e2e` and skipped unless explicitly requested with
`pytest -m e2e`. It requires:
  * a running uvicorn at http://localhost:8000
  * a residential proxy configured in `proxies.txt` (Yandex blocks DC IPs)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_yandex_maps_endpoint_registered_in_app():
    """Yandex Maps endpoint should be registered in main app."""
    from src.api.main import app

    routes = [r.path for r in app.routes]
    assert any("/yandex-maps/extract" in r for r in routes), (
        "Yandex Maps extract endpoint not registered"
    )
    assert any("/yandex-maps/reviews" in r for r in routes), (
        "Yandex Maps reviews endpoint not registered"
    )


def test_yandex_maps_router_exists():
    try:
        from src.api.routers.yandex_maps import router

        assert router is not None
    except ImportError:
        pytest.fail("Yandex Maps router does not exist")


@pytest.mark.e2e
def test_yandex_maps_endpoint_returns_organizations():
    """Live E2E: real browser + real Yandex. Requires uvicorn on :8000 and proxy."""
    import asyncio

    import httpx

    async def check():
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "http://localhost:8000/api/v1/yandex-maps/extract",
                headers={"X-API-Key": "default_internal_key"},
                json={
                    "query": "стоматология",
                    "region_id": 2,
                    "city_slug": "saint-petersburg",
                    "target_count": 20,
                },
            )
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            data = response.json()
            assert "organizations" in data
            assert "total" in data
            assert isinstance(data["organizations"], list)
            assert data["total"] == len(data["organizations"])

    asyncio.run(check())


@pytest.mark.e2e
def test_yandex_maps_reviews_endpoint_returns_reviews():
    """Live E2E: reviews for a known org."""
    import asyncio

    import httpx

    async def check():
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "http://localhost:8000/api/v1/yandex-maps/reviews",
                headers={"X-API-Key": "default_internal_key"},
                json={
                    "business_oid": "82071161567",
                    "seoname": "dental_konfidens",
                    "count": 50,
                },
            )
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}: {response.text}"
            )
            data = response.json()
            assert "reviews" in data
            assert isinstance(data["reviews"], list)

    asyncio.run(check())


def test_stealth_config_applied_to_yandex_requests():
    from src.infrastructure.browser.stealth_pool import StealthPool

    pool = StealthPool()
    assert hasattr(pool, "human_emulation_enabled")


def test_user_agent_pool_contains_agents():
    from src.infrastructure.browser.user_agent_pool import UserAgentPool

    pool = UserAgentPool()
    assert pool.get_user_agent()


def test_proxy_provider_works_for_yandex_maps():
    from src.infrastructure.browser.proxy_provider import ProxyProvider

    provider = ProxyProvider()
    proxy = provider.get_proxy()
    assert proxy is None or isinstance(proxy, dict)


@pytest.mark.asyncio
async def test_yandex_organization_schema_complete():
    """YandexOrganization model has the required fields and validators."""
    from src.domain.models.yandex_organization import (
        YandexCoordinates,
        YandexOrganization,
        YandexPhone,
    )

    org = YandexOrganization(
        oid="1",
        seoname="x",
        title="Test",
    )
    assert org.oid == "1"
    assert org.title == "Test"
    assert org.phones == []
    assert org.coordinates is None

    full = YandexOrganization(
        oid="2",
        seoname="y",
        title="Full",
        coordinates=YandexCoordinates(lat=59.934, lon=30.306),
        phones=[YandexPhone(number="+7 999 000 0000", value="+79990000000")],
    )
    assert full.coordinates.lat == 59.934
    assert full.coordinates.lon == 30.306
    assert full.phones[0].value == "+79990000000"


@pytest.mark.asyncio
async def test_request_model_validation():
    """YandexMapsExtractRequest must reject invalid inputs."""
    from pydantic import ValidationError

    from src.domain.models.requests import YandexMapsExtractRequest

    valid = YandexMapsExtractRequest(query="кафе", region_id=2, target_count=20)
    assert valid.query == "кафе"
    assert valid.region_id == 2

    with pytest.raises(ValidationError):
        YandexMapsExtractRequest(query="", region_id=2)
    with pytest.raises(ValidationError):
        YandexMapsExtractRequest(query="x", region_id=0)
    with pytest.raises(ValidationError):
        YandexMapsExtractRequest(query="x", target_count=999)


@pytest.mark.asyncio
async def test_reviews_request_model_validation():
    from pydantic import ValidationError

    from src.domain.models.requests import YandexMapsReviewsRequest

    valid = YandexMapsReviewsRequest(business_oid="82071161567", seoname="x")
    assert valid.count == 50
    assert valid.ranking == "by_time"

    with pytest.raises(ValidationError):
        YandexMapsReviewsRequest(business_oid="not-digits", seoname="x")
    with pytest.raises(ValidationError):
        YandexMapsReviewsRequest(business_oid="1", seoname="x", ranking="weird")
    with pytest.raises(ValidationError):
        YandexMapsReviewsRequest(business_oid="1", seoname="x", count=999)


@pytest.mark.asyncio
async def test_extract_action_aggregates_across_multiple_xhr_responses():
    """Action collects orgs across several `/maps/api/search` payloads."""
    import json

    from src.actions.yandex_maps import YandexMapsExtractAction

    body_a = json.dumps(
        {
            "data": {
                "items": [
                    {
                        "id": "A1",
                        "permalink": "A1",
                        "seoname": "a1",
                        "title": "Org A1",
                    },
                    {
                        "id": "A2",
                        "permalink": "A2",
                        "seoname": "a2",
                        "title": "Org A2",
                    },
                ]
            }
        }
    )
    body_b = json.dumps(
        {
            "data": {
                "items": [
                    {
                        "id": "B1",
                        "permalink": "B1",
                        "seoname": "b1",
                        "title": "Org B1",
                    }
                ]
            }
        }
    )

    def _resp(url, body):
        r = MagicMock()
        r.url = url
        r.status = 200
        r.text = AsyncMock(return_value=body)
        return r

    handlers: list = []
    page = MagicMock()
    page.on = lambda event, cb: handlers.append((event, cb))

    async def goto(*a, **kw):
        for r in (
            _resp("https://yandex.ru/maps/api/search?p=0", body_a),
            _resp("https://yandex.ru/maps/api/search?p=1", body_b),
        ):
            for event, cb in handlers:
                if event == "response":
                    cb(r)

    page.goto = goto
    page.content = AsyncMock(return_value="<html></html>")
    page.wait_for_selector = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=99)

    ctx = MagicMock()
    ctx.new_page = AsyncMock(return_value=page)
    ctx.close = AsyncMock()

    action = YandexMapsExtractAction()
    action.scroll_limit = 1
    with patch.object(
        action.pool_manager, "create_context", new=AsyncMock(return_value=ctx)
    ), patch("src.actions.yandex_maps.proxy_provider") as proxy_mock:
        proxy_mock.get_proxy.return_value = None
        orgs = await action.execute(query="x", target_count=10)

    assert {o.oid for o in orgs} == {"A1", "A2", "B1"}
