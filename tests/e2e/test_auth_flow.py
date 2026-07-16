"""
E2E test for authentication flow across all protected routes.
Verifies that X-API-Key enforcement works end-to-end for every protected router.
"""

import pytest
from httpx import AsyncClient, ASGITransport

VALID_KEY = "default_internal_key"

PROTECTED_ROUTES = [
    ("POST", "/api/v1/yandex-maps/extract", {
        "query": "стоматология",
        "region_id": 2,
        "city_slug": "saint-petersburg",
        "target_count": 20,
    }),
    ("POST", "/api/v1/yandex-maps/reviews", {
        "business_oid": "82071161567",
        "seoname": "dental_konfidens",
        "count": 50,
    }),
    ("POST", "/api/v1/enrich", {"url": "https://example.com"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", PROTECTED_ROUTES)
async def test_all_protected_routes_require_api_key(method, path, body):
    """Every protected route must return 403 when no API key is provided."""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        send = client.post if method == "POST" else client.get
        response = await send(path, json=body)
    assert response.status_code == 403, (
        f"{method} {path} returned {response.status_code}, expected 403"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", PROTECTED_ROUTES)
async def test_valid_api_key_grants_access(method, path, body):
    """Every protected route must NOT return 403 when a valid API key is provided."""
    from src.api.main import app
    from unittest.mock import patch, AsyncMock
    from src.domain.models.enriched_content import EnrichedContent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        send = client.post if method == "POST" else client.get
        with (
            patch(
                "src.actions.yandex_maps.YandexMapsExtractAction.execute",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.actions.yandex_maps.YandexMapsReviewsAction.execute",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.actions.site_enricher.SiteEnrichAction.execute",
                new_callable=AsyncMock,
                return_value=EnrichedContent(
                    url=str(body.get("url", "https://example.com")),
                    text="hello world",
                    word_count=2,
                    truncated=False,
                ),
            ),
        ):
            response = await send(path, headers={"X-API-Key": VALID_KEY}, json=body)
    assert response.status_code != 403, (
        f"{method} {path} with valid key returned 403"
    )
