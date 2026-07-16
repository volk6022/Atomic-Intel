import pytest
from unittest.mock import AsyncMock, patch
import redis.exceptions
from fastapi import HTTPException

from src.api.routers.sessions import (
    create_session,
    send_command,
    CreateSessionRequest,
    CommandRequest,
)


@pytest.mark.asyncio
async def test_session_creation_fails_gracefully():
    """Test that session creation returns 503 when Redis is unavailable"""
    with patch("src.api.routers.sessions.run_session_actor.kiq") as mock_kiq:
        mock_kiq.side_effect = redis.exceptions.ConnectionError("Connection refused")

        request = CreateSessionRequest()
        with pytest.raises(HTTPException) as exc_info:
            await create_session(request)

        assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_command_publish_fails_gracefully():
    """Test that command endpoint returns 503 when Redis publish fails"""
    with patch("src.api.routers.sessions.manager.publish_command") as mock_publish:
        mock_publish.side_effect = redis.exceptions.ConnectionError(
            "Connection refused"
        )

        with pytest.raises(HTTPException) as exc_info:
            await send_command("test-session", CommandRequest(type="goto"))

        assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_error_response_includes_details():
    """Test that error response includes proper error details"""
    with patch("src.api.routers.sessions.manager.subscribe_results") as mock_subscribe:
        mock_subscribe.side_effect = redis.exceptions.ConnectionError(
            "Connection refused"
        )

        with pytest.raises(HTTPException) as exc_info:
            await send_command("test-session", CommandRequest(type="goto"))

        assert exc_info.value.status_code == 503
        detail = exc_info.value.detail
        assert "details" in detail
        assert "reason" in detail["details"]
        assert "Connection refused" in detail["details"]["reason"]
