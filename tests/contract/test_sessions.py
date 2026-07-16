"""
Contract tests for sessions API endpoints.

Tests real endpoint behavior via ASGITransport, with Redis errors mocked for error case testing.
"""

import pytest
from unittest.mock import AsyncMock, patch
import redis.exceptions

from httpx import AsyncClient, ASGITransport

from src.api.main import app

TEST_API_KEY = "default_internal_key"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


@pytest.mark.asyncio
async def test_create_session_returns_200_with_valid_request():
    """Session creation should return 200 OK with session_id and status"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.infrastructure.queue.session_actor.run_session_actor.kiq",
            new_callable=AsyncMock,
            return_value=AsyncMock(),
        ):
            response = await client.post(
                "/sessions",
                headers=AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 200
            data = response.json()
            assert "session_id" in data
            assert "status" in data
            assert data["status"] == "active"
            assert len(data["session_id"]) == 36


@pytest.mark.asyncio
async def test_create_session_with_custom_viewport():
    """Session creation should accept custom viewport configuration"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.infrastructure.queue.session_actor.run_session_actor.kiq",
            new_callable=AsyncMock,
            return_value=AsyncMock(),
        ):
            response = await client.post(
                "/sessions",
                headers=AUTH_HEADERS,
                json={
                    "headless": False,
                    "viewport": {"width": 1920, "height": 1080},
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_session_with_proxy():
    """Session creation should accept proxy configuration"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.infrastructure.queue.session_actor.run_session_actor.kiq",
            new_callable=AsyncMock,
            return_value=AsyncMock(),
        ):
            response = await client.post(
                "/sessions",
                headers=AUTH_HEADERS,
                json={
                    "proxy": "http://user:pass@proxy.com:8080",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_session_returns_503_when_redis_unavailable():
    """Create session should return 503 when Redis is unavailable"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.infrastructure.queue.session_actor.run_session_actor.kiq",
            side_effect=redis.exceptions.ConnectionError("Connection refused"),
        ):
            response = await client.post(
                "/sessions",
                headers=AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 503


@pytest.mark.parametrize(
    "redis_error",
    [
        redis.exceptions.ConnectionError("Connection refused"),
        redis.exceptions.TimeoutError("Connection timed out"),
    ],
)
@pytest.mark.asyncio
async def test_create_session_returns_503_on_various_redis_errors(redis_error):
    """Create session should return 503 for various Redis errors"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.infrastructure.queue.session_actor.run_session_actor.kiq",
            side_effect=redis_error,
        ):
            response = await client.post(
                "/sessions",
                headers=AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 503


@pytest.mark.asyncio
async def test_redis_error_has_correct_format():
    """Redis error response should have standard error format"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.infrastructure.queue.session_actor.run_session_actor.kiq",
            side_effect=redis.exceptions.ConnectionError("Connection refused"),
        ):
            response = await client.post(
                "/sessions",
                headers=AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 503
            data = response.json()
            assert "detail" in data
            detail = data["detail"]
            assert "error" in detail
            assert "code" in detail
            assert detail["code"] == "REDIS_UNAVAILABLE"


@pytest.mark.asyncio
async def test_command_endpoint_returns_503_when_redis_unavailable():
    """Command endpoint should return 503 when Redis is unavailable"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.api.websockets.manager.manager.publish_command",
            side_effect=redis.exceptions.ConnectionError("Connection refused"),
        ):
            response = await client.post(
                "/sessions/test-session-id/command",
                headers=AUTH_HEADERS,
                json={"type": "goto", "params": {"url": "https://example.com"}},
            )
            assert response.status_code == 503


@pytest.mark.asyncio
async def test_command_endpoint_subscribe_failure_returns_503():
    """Command endpoint should return 503 when Redis subscribe fails"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.api.websockets.manager.manager.subscribe_results",
            side_effect=redis.exceptions.ConnectionError("Connection refused"),
        ):
            response = await client.post(
                "/sessions/test-session-id/command",
                headers=AUTH_HEADERS,
                json={"type": "goto", "params": {"url": "https://example.com"}},
            )
            assert response.status_code == 503


@pytest.mark.asyncio
async def test_delete_session_returns_503_when_redis_unavailable():
    """Delete session should return 503 when Redis is unavailable"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.api.websockets.manager.manager.publish_command",
            side_effect=redis.exceptions.ConnectionError("Connection refused"),
        ):
            response = await client.delete(
                "/sessions/test-session-id",
                headers=AUTH_HEADERS,
            )
            assert response.status_code == 503


@pytest.mark.asyncio
async def test_delete_session_returns_503_on_various_redis_errors():
    """Delete session should return 503 for various Redis errors"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.api.websockets.manager.manager.publish_command",
            side_effect=redis.exceptions.TimeoutError("Connection timed out"),
        ):
            response = await client.delete(
                "/sessions/test-session-id",
                headers=AUTH_HEADERS,
            )
            assert response.status_code == 503


@pytest.mark.asyncio
async def test_command_invalid_session_id():
    """Command endpoint should work with any session_id format"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.api.websockets.manager.manager.subscribe_results",
            side_effect=redis.exceptions.ConnectionError("Connection refused"),
        ):
            response = await client.post(
                "/sessions/invalid-uuid-123/command",
                headers=AUTH_HEADERS,
                json={"type": "goto", "params": {"url": "https://example.com"}},
            )
            assert response.status_code == 503


@pytest.mark.asyncio
async def test_create_session_requires_auth():
    """Session creation should require authentication"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/sessions",
            json={},
        )
        assert response.status_code == 403
