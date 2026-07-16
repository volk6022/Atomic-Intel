import fnmatch
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.infrastructure.rate_limiter.token_bucket import rate_limiter
from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_RULES = [
    {"pattern": "*.yandex.*", "requests_per_hour": settings.RATE_LIMIT_YANDEX_PER_HOUR},
    {"pattern": "*", "requests_per_hour": settings.RATE_LIMIT_DEFAULT_PER_HOUR},
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rules: list = None):
        super().__init__(app)
        self.rules = rules or DEFAULT_RULES
        self._enabled = True

    def _get_domain_from_request(self, request: Request) -> str:
        host = request.headers.get("host", "")
        if ":" in host:
            host = host.split(":")[0]
        return host

    def _get_rate_limit_rule(self, domain: str) -> dict:
        for rule in self.rules:
            if fnmatch.fnmatch(domain, rule["pattern"]):
                return rule
        return {
            "pattern": "*",
            "requests_per_hour": settings.RATE_LIMIT_DEFAULT_PER_HOUR,
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enabled:
            return await call_next(request)

        if request.url.path in ["/healthz", "/docs", "/openapi.json"]:
            return await call_next(request)

        domain = self._get_domain_from_request(request)
        rule = self._get_rate_limit_rule(domain)

        max_requests = rule["requests_per_hour"]
        window_seconds = 3600

        try:
            result = await rate_limiter.consume(
                domain=f"rate:{domain}",
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
        except Exception as e:
            logger.warning(f"Rate limiter unavailable, allowing request: {e}")
            return await call_next(request)

        if not result.allowed:
            retry_after = result.retry_after or 3600
            logger.warning(
                f"Rate limit exceeded for {domain}: "
                f"{result.current_count}/{max_requests}"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": retry_after,
                    "domain": domain,
                },
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, max_requests - result.current_count)
        )
        return response
