"""Async httpx client with sequential proxy rotation.

Generalises the rotation pattern inlined in ``src/actions/yandex_maps.py``
(``_build_proxy_url`` / ``_httpx_proxy`` / dead-proxy TTL memory) and the sync
``ProxyRotatingClient`` from ``experiment_monitoring/experiment-fl/proxy_client.py``.

Design notes:
* Proxies come from the existing :data:`proxy_provider` (same ``proxies.txt``),
  so there is one source of truth for the pool.
* The puls-proxy pool is concurrency-capped, so rotation is **sequential** with a
  short connect timeout: dead ports are benched (TTL) and abandoned in ~5 s.
* ``use_proxy=False`` (the default, ``MONITOR_USE_PROXY``) does a plain direct
  request — most sources (fl/kwork/superjob/habr/zarplata) pass anti-bot without
  a proxy, and a proxy only slows them down.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from src.core.config import settings
from src.core.logging import get_logger
from src.infrastructure.browser.proxy_provider import proxy_provider

logger = get_logger(__name__)

# Infrastructure-level failures worth rotating the proxy for.
_INFRA_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ProxyError,
)
# Upstream statuses that indicate a bad/blocked proxy hop (not a real page).
_RETRY_STATUS = frozenset({407, 500, 502, 503, 504})

# In-process dead-proxy memory (mirrors yandex_maps): benched ports are skipped
# for a TTL so traffic concentrates on the currently-live subset of the pool.
_DEAD_PROXIES: dict[str, float] = {}
_DEAD_TTL_S = 60.0


def build_proxy_url(p: dict) -> str:
    """Turn a proxy_provider dict ({server, username?, password?}) into an httpx URL."""
    server = p["server"]  # e.g. "http://host:port"
    if p.get("username") and "://" in server:
        scheme, rest = server.split("://", 1)
        return f"{scheme}://{p['username']}:{p['password']}@{rest}"
    return server


def _next_proxy_url() -> Optional[str]:
    """Next live proxy URL from the rotating pool, skipping recently-dead ones."""
    n = max(1, len(getattr(proxy_provider, "_proxies", []) or [1]))
    now = time.monotonic()
    fallback: Optional[str] = None
    for _ in range(n):
        p = proxy_provider.get_proxy()
        if not p:
            return None
        url = build_proxy_url(p)
        fallback = url
        if _DEAD_PROXIES.get(url, 0.0) <= now:
            return url
    return fallback  # whole pool benched — try one anyway


def _mark_dead(url: Optional[str]) -> None:
    if url:
        _DEAD_PROXIES[url] = time.monotonic() + _DEAD_TTL_S


class AllProxiesFailedError(RuntimeError):
    """Raised when every rotation attempt failed to produce a usable response."""


class RotatingHTTPClient:
    """Async httpx wrapper. Direct by default; rotates proxies when enabled."""

    def __init__(
        self,
        *,
        use_proxy: Optional[bool] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.use_proxy = settings.MONITOR_USE_PROXY if use_proxy is None else use_proxy
        read = timeout if timeout is not None else settings.MONITOR_HTTP_TIMEOUT
        # short connect (bench dead ports fast), generous read (SSR pages are big)
        self._timeout = httpx.Timeout(connect=4.0, read=read, write=read, pool=read)
        self._max_retries = (
            max_retries if max_retries is not None else settings.MONITOR_MAX_PROXY_RETRIES
        )
        self._headers = headers or {}

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        merged = {**self._headers, **kwargs.pop("headers", {})}

        if not self.use_proxy:
            async with httpx.AsyncClient(
                timeout=self._timeout, headers=merged, follow_redirects=True
            ) as client:
                return await client.request(method, url, **kwargs)

        last_exc: Optional[Exception] = None
        tries = min(self._max_retries, max(1, len(getattr(proxy_provider, "_proxies", []) or [1])))
        for attempt in range(tries):
            proxy = _next_proxy_url()
            try:
                async with httpx.AsyncClient(
                    proxy=proxy,
                    timeout=self._timeout,
                    headers=merged,
                    follow_redirects=True,
                ) as client:
                    resp = await client.request(method, url, **kwargs)
                if resp.status_code in _RETRY_STATUS:
                    last_exc = RuntimeError(f"HTTP {resp.status_code}")
                    logger.debug("rotating_http: %s on attempt %d — rotating", resp.status_code, attempt + 1)
                    continue
                return resp
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                _mark_dead(proxy)
                last_exc = exc
            except _INFRA_ERRORS as exc:
                last_exc = exc

        raise AllProxiesFailedError(f"{tries} attempts failed for {url}: {last_exc}")

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)
