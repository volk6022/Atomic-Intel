import pytest
from redis.asyncio import Redis
from src.core.config import settings


@pytest.mark.asyncio
async def test_redis_connection():
    redis = Redis.from_url(settings.REDIS_URL)
    assert await redis.ping() is True
    await redis.close()
