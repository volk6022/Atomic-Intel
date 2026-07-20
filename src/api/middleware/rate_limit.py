"""Per-tenant hourly quota enforcement with per-bucket billing.

Fixes bug C-01: the previous implementation keyed the token bucket on
``request.headers["host"]`` — the API's OWN inbound Host header, not any
caller identity or scrape target. Every caller hitting the same hostname
shared one bucket, so the quota was effectively global instead of per-tenant,
and the ``*.yandex.*`` rule could never match (the inbound Host header is the
API's own domain, never ``yandex.ru``).

The bucket is now keyed on the resolved tenant (from the caller's
``X-API-Key``, via ``src.api.auth.resolve_principal``), with the per-hour
limit read from that tenant's ``quota_per_hour`` DB column. Requests with a
missing/invalid key are NOT rejected here — they fall through to the
route-level ``get_api_key`` dependency, which returns 403. Rate limiting only
ever applies to a request that already resolves to a real, active tenant.

The old ``*.yandex.*`` rule is dropped rather than carried forward: "does this
route touch Yandex" is an *outbound target* politeness concern, not an
*inbound caller* quota concern, and belongs in the scraping/action layer
(``src.actions.yandex_maps._httpx_proxy`` / ``_mark_proxy_dead``) — not in
this gate. If per-target outbound throttling is needed later, it should be a
separate limiter down in that layer, not bolted onto caller-facing quota.

BILLING SEPARATION (read vs work): To prevent clients from being charged quota
for retrieving their own results, we split the quota into two independent
buckets per tenant:

  1. WORK bucket (key: ``tenant:{id}``, limit: ``principal.quota_per_hour``)
     — charged for write operations (e.g. POST /api/v1/research/run).
  2. READ bucket (key: ``tenant:{id}:read``, limit: ``READ_QUOTA_PER_HOUR``)
     — charged for read-only status/stream operations.

This allows a client to retrieve a result multiple times (polling via /status)
without exhausting the quota meant for launching new research tasks. The READ
bucket uses a separate, generous limit (default 1000/hour) to rate-limit
abuse while accommodating normal polling patterns.
"""

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.api.auth import resolve_principal
from src.infrastructure.rate_limiter.token_bucket import rate_limiter
from src.core.logging import get_logger
from src.core.config import settings

logger = get_logger(__name__)

# /docs, /redoc, /openapi.json are disabled app-wide (see src/api/main.py) but
# are kept in this exemption list too in case they're ever re-enabled.
EXEMPT_PATHS = {"/healthz", "/docs", "/redoc", "/openapi.json"}

# Read-only paths that are charged against the READ bucket instead of the WORK bucket.
# This prevents clients from being quota-limited on polling their own task status.
READ_PATH_PREFIXES = ("/api/v1/research/status", "/api/v1/research/stream")

WINDOW_SECONDS = 3600


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._enabled = True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enabled or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        api_key = request.headers.get("x-api-key")
        principal = await resolve_principal(api_key)
        if principal is None:
            # No/unknown/inactive key: let get_api_key 403 it downstream —
            # this middleware only rate-limits requests from real tenants.
            return await call_next(request)

        # Determine which bucket (READ or WORK) this request consumes from.
        # Read paths (status/stream polling) hit the READ bucket so clients can
        # retrieve their results without burning through the WORK quota.
        is_read_path = any(
            request.url.path.startswith(prefix) for prefix in READ_PATH_PREFIXES
        )

        if is_read_path:
            # READ bucket: generous limit, keyed separately so reads don't starve work.
            max_requests = settings.READ_QUOTA_PER_HOUR
            bucket_key = f"tenant:{principal.tenant_id}:read"
            scope = "read"
        else:
            # WORK bucket: per-tenant quota for launches/creates.
            max_requests = principal.quota_per_hour
            bucket_key = f"tenant:{principal.tenant_id}"
            scope = "work"

        try:
            result = await rate_limiter.consume(
                domain=bucket_key,
                max_requests=max_requests,
                window_seconds=WINDOW_SECONDS,
            )
        except Exception as e:
            logger.warning(f"Rate limiter unavailable, allowing request: {e}")
            return await call_next(request)

        if not result.allowed:
            retry_after = result.retry_after or WINDOW_SECONDS
            logger.warning(
                f"Rate limit exceeded for tenant {principal.name} "
                f"({principal.tenant_id}) on {scope} bucket: "
                f"{result.current_count}/{max_requests}"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": retry_after,
                    "tenant": principal.name,
                    "scope": scope,
                },
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, max_requests - result.current_count)
        )
        return response
