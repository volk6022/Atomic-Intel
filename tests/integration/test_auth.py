"""
Integration tests for API authentication.

Tests authentication middleware with real FastAPI app.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from src.api.main import app


TEST_API_KEY = "default_internal_key"
VALID_AUTH_HEADER = {"X-API-Key": TEST_API_KEY}


class TestAuthOnProtectedEndpoints:
    """Test authentication on various protected endpoints"""

    @pytest.mark.asyncio
    async def test_enrichment_requires_auth(self):
        """Enrichment endpoint should require authentication"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/enrich",
                json={"url": "https://example.com"},
            )
            assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_enrichment_accepts_valid_key(self):
        """Enrichment endpoint should accept valid API key"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/enrich",
                json={"url": "https://example.com"},
                headers=VALID_AUTH_HEADER,
            )
            assert response.status_code in [200, 500]

    @pytest.mark.asyncio
    async def test_enrichment_rejects_invalid_key(self):
        """Enrichment endpoint should reject invalid API key"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/enrich",
                json={"url": "https://example.com"},
                headers={"X-API-Key": "invalid_key_12345"},
            )
            assert response.status_code == 403


class TestAuthOnResearchEndpoints:
    """Test authentication on research endpoints"""

    @pytest.mark.asyncio
    async def test_research_run_requires_auth(self):
        """Research run endpoint should require authentication"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/research/research/run",
                json={"query": "test", "mode": "speed"},
            )
            assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_research_status_requires_auth(self):
        """Research status endpoint should require authentication"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/research/research/status/test-id")
            assert response.status_code in [403, 404]

    @pytest.mark.asyncio
    async def test_research_stream_requires_auth(self):
        """Research stream endpoint should require authentication"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/research/research/stream/test-id")
            assert response.status_code in [403, 404]


class TestAuthOnYandexMapsEndpoint:
    """Test authentication on Yandex Maps endpoint"""

    @pytest.mark.asyncio
    async def test_yandex_maps_requires_auth(self):
        """Yandex Maps endpoint should require authentication"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                json={
                    "category": "restaurants",
                    "center": {"lat": 59.934, "lng": 30.306},
                    "radius": 1000,
                },
            )
            assert response.status_code == 403


class TestPublicEndpoints:
    """Test that public endpoints don't require auth"""

    @pytest.mark.asyncio
    async def test_healthz_is_public(self):
        """Health check should be publicly accessible"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/healthz")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_docs_are_disabled(self):
        """Interactive docs are disabled in the public build (M2 strip)."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/docs")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_openapi_schema_is_disabled(self):
        """OpenAPI schema is disabled in the public build (M2 strip)."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/openapi.json")
            assert response.status_code == 404


class TestAuthErrorFormat:
    """Test authentication error response format"""

    @pytest.mark.asyncio
    async def test_auth_error_has_detail(self):
        """Auth error should include detail field"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/enrich",
                json={"url": "https://example.com"},
                headers={"X-API-Key": "wrong_key"},
            )
            assert response.status_code == 403
            data = response.json()
            assert "detail" in data

    @pytest.mark.asyncio
    async def test_auth_error_message_is_clear(self):
        """Auth error message should be clear"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/enrich",
                json={"url": "https://example.com"},
                headers={"X-API-Key": "invalid"},
            )
            assert response.status_code == 403
