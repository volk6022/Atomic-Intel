import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import redis.asyncio as redis


@pytest.fixture(autouse=True)
def mock_redis():
    mock_redis_client = MagicMock()  # Use MagicMock for the client
    mock_redis_client.ping = AsyncMock(return_value=True)
    mock_redis_client.publish = AsyncMock(return_value=1)
    mock_redis_client.close = AsyncMock(return_value=None)

    mock_pubsub = MagicMock()
    mock_pubsub.subscribe = AsyncMock(return_value=None)
    mock_pubsub.unsubscribe = AsyncMock(return_value=None)

    # Define an async generator for listen()
    async def mock_listen():
        yield {
            "type": "message",
            "channel": b"res:test-session",
            "data": b'{"status": "success"}',
        }
        await asyncio.sleep(0.1)

    mock_pubsub.listen = mock_listen
    mock_redis_client.pubsub.return_value = mock_pubsub

    # Force the sync redis client (used by research_store) to look unavailable so
    # tests fall back to the per-process in-memory dict. Without this, the store
    # would talk to a real Redis on localhost:6379 and tests would see leftover
    # tasks from previous runs (e.g. concurrency-limit false positives).
    def _sync_redis_unavailable(*_a, **_kw):
        raise ConnectionError("redis mocked away in tests")

    with (
        patch("redis.asyncio.Redis.from_url", return_value=mock_redis_client),
        patch("redis.asyncio.client.Redis.from_url", return_value=mock_redis_client),
        patch("redis.Redis.from_url", side_effect=_sync_redis_unavailable),
    ):
        yield mock_redis_client


@pytest.fixture(autouse=True)
def reset_research_store():
    """Clear the in-memory research-store fallback before every test."""
    from src.infrastructure.tasks import research_store as _store

    _store._local_fallback.clear()
    yield
    _store._local_fallback.clear()
