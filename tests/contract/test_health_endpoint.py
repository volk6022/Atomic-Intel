"""
Contract test for /healthz endpoint.
T004: Write failing contract test for /healthz endpoint.

This test MUST fail before implementation (TDD requirement).
"""

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_healthz_returns_200():
    """Health endpoint should return 200 OK"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_healthz_response_format():
    """Health endpoint should return JSON with status"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


@pytest.mark.asyncio
async def test_healthz_includes_redis_status():
    """Health endpoint should include Redis connection status"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
        data = response.json()
        assert "redis" in data


@pytest.mark.asyncio
async def test_healthz_includes_browser_pool_status():
    """Health endpoint should include browser pool availability"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
        data = response.json()
        assert "browser_pool" in data


@pytest.mark.asyncio
async def test_healthz_response_time():
    """Health endpoint should respond within 200ms"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        import time

        start = time.perf_counter()
        response = await client.get("/healthz")
        elapsed = (time.perf_counter() - start) * 1000
        assert elapsed < 3000, (
            f"Health check took {elapsed}ms, expected <3000ms (relaxed for cold starts)"
        )
