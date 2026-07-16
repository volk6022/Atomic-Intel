import fnmatch
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as redis
from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RateLimitResult:
    allowed: bool
    current_count: int
    max_requests: int
    retry_after: Optional[int] = None


class TokenBucketRateLimiter:
    def __init__(self):
        self._redis: Optional[redis.Redis] = None

    async def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(settings.REDIS_URL)
        return self._redis

    def _matches_pattern(self, domain: str, pattern: str) -> bool:
        return fnmatch.fnmatch(domain, pattern)

    async def check_rate_limit(
        self, domain: str, max_requests: int, window_seconds: int = 3600
    ) -> RateLimitResult:
        key = f"ratelimit:{domain}"
        redis_client = await self._get_redis()

        current = await redis_client.get(key)
        current_count = int(current) if current else 0

        if current_count >= max_requests:
            ttl = await redis_client.ttl(key)
            retry_after = ttl if ttl > 0 else window_seconds
            return RateLimitResult(
                allowed=False,
                current_count=current_count,
                max_requests=max_requests,
                retry_after=retry_after,
            )

        return RateLimitResult(
            allowed=True,
            current_count=current_count,
            max_requests=max_requests,
        )

    async def consume(
        self, domain: str, max_requests: int, window_seconds: int = 3600
    ) -> RateLimitResult:
        key = f"ratelimit:{domain}"
        redis_client = await self._get_redis()

        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

        new_count = results[0]

        if new_count > max_requests:
            ttl = await redis_client.ttl(key)
            retry_after = ttl if ttl > 0 else window_seconds
            return RateLimitResult(
                allowed=False,
                current_count=new_count,
                max_requests=max_requests,
                retry_after=retry_after,
            )

        return RateLimitResult(
            allowed=True,
            current_count=new_count,
            max_requests=max_requests,
        )

    async def reset(self, domain: str) -> None:
        key = f"ratelimit:{domain}"
        redis_client = await self._get_redis()
        await redis_client.delete(key)

    async def get_remaining(self, domain: str, max_requests: int) -> int:
        key = f"ratelimit:{domain}"
        redis_client = await self._get_redis()

        current = await redis_client.get(key)
        current_count = int(current) if current else 0
        return max(0, max_requests - current_count)


rate_limiter = TokenBucketRateLimiter()
