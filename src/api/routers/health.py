"""
Health check endpoint router.
T006-T008: Create /healthz endpoint with Redis and browser pool checks.
"""

from fastapi import APIRouter
from redis.asyncio import Redis
from pydantic import BaseModel

from src.core.config import settings

router = APIRouter(prefix="", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    redis: str
    browser_pool: str


@router.get("/healthz", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint for container orchestration."""
    redis_status = "unknown"
    browser_status = "unknown"
    overall_status = "healthy"

    # Check Redis connection
    try:
        redis_client = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        try:
            await redis_client.ping()
            redis_status = "connected"
        except Exception as e:
            redis_status = f"failed: {str(e)[:40]}"
            overall_status = "degraded"
        finally:
            await redis_client.aclose()
    except Exception as e:
        redis_status = f"unavailable: {str(e)[:50]}"
        overall_status = "degraded"

    # Check browser pool availability
    try:
        from src.infrastructure.browser.pool_manager import pool_manager

        available = pool_manager.available_contexts()
        if available > 0:
            browser_status = f"available ({available} contexts)"
        else:
            browser_status = "degraded"
            if overall_status == "healthy":
                overall_status = "degraded"
    except Exception as e:
        browser_status = f"error: {str(e)}"
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status, redis=redis_status, browser_pool=browser_status
    )
