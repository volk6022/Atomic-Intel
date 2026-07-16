"""
E2E test for rate limiting middleware flow.
Tests that the RateLimitMiddleware enforces per-domain rules through the full
FastAPI app stack, including the Retry-After header and yandex-specific limits.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from src.infrastructure.rate_limiter.token_bucket import RateLimitResult

AUTH_HEADERS = {"X-API-Key": "default_internal_key"}
YANDEX_BODY = {
    "category": "restaurants",
    "center": {"lat": 59.934, "lng": 30.306},
    "radius": 1000,
}
ENRICH_BODY = {"url": "https://example.com"}


def _allowed_result(count: int = 1) -> RateLimitResult:
    return RateLimitResult(allowed=True, current_count=count, max_requests=30, retry_after=None)


def _blocked_result() -> RateLimitResult:
    return RateLimitResult(allowed=False, current_count=31, max_requests=30, retry_after=3600)


@pytest.mark.asyncio
async def test_yandex_domain_rate_limit_applied():
    """Request is rejected with 429 when the yandex rate limiter returns blocked."""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.api.middleware.rate_limit.rate_limiter.consume",
            new_callable=AsyncMock,
            return_value=_blocked_result(),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json=YANDEX_BODY,
            )
    assert response.status_code == 429
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Rate limit exceeded"


@pytest.mark.asyncio
async def test_rate_limit_retry_after_header_present():
    """A 429 response must include a Retry-After header."""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.api.middleware.rate_limit.rate_limiter.consume",
            new_callable=AsyncMock,
            return_value=_blocked_result(),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json=YANDEX_BODY,
            )
    assert response.status_code == 429
    assert "retry-after" in response.headers


@pytest.mark.asyncio
async def test_non_yandex_domain_passes_when_allowed():
    """Enrichment requests pass through when rate limiter allows them."""
    from src.api.main import app
    from src.domain.models.enriched_content import EnrichedContent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with (
            patch(
                "src.api.middleware.rate_limit.rate_limiter.consume",
                new_callable=AsyncMock,
                return_value=_allowed_result(),
            ),
            patch(
                "src.actions.site_enricher.SiteEnrichAction.execute",
                new_callable=AsyncMock,
                return_value=EnrichedContent(
                    url="https://example.com",
                    text="hello world",
                    word_count=2,
                    truncated=False,
                ),
            ),
        ):
            response = await client.post(
                "/api/v1/enrich",
                headers=AUTH_HEADERS,
                json=ENRICH_BODY,
            )
    assert response.status_code == 200
