import asyncio
import json
import redis
from redis.asyncio import Redis
from src.core.config import settings
from src.domain.models.errors import RedisUnavailableError


class ConnectionManager:
    def __init__(self):
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            self._redis = Redis.from_url(settings.REDIS_URL)
        return self._redis

    async def publish_command(self, session_id: str, command: dict):
        try:
            await self.redis.publish(f"cmd:{session_id}", json.dumps(command))
        except (
            redis.exceptions.ConnectionError,
            redis.exceptions.TimeoutError,
            redis.exceptions.RedisError,
        ) as e:
            raise RedisUnavailableError(
                "Command publishing temporarily unavailable", {"reason": str(e)}
            )

    async def subscribe_results(self, session_id: str):
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(f"res:{session_id}")
            return pubsub
        except (
            redis.exceptions.ConnectionError,
            redis.exceptions.TimeoutError,
            redis.exceptions.RedisError,
        ) as e:
            raise RedisUnavailableError(
                "Result subscription temporarily unavailable", {"reason": str(e)}
            )


manager = ConnectionManager()
