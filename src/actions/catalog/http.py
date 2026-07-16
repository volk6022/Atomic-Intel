"""Block-aware, throttled async request helper for catalog paging.

Async port of the ``_request`` helpers in ``kwork_services_scrape.py`` and
``fl_freelancers_scrape.py``. Rotates a fresh proxy per attempt from the existing
:data:`proxy_provider` pool (kwork/QRATOR IP-bans after ~8 rapid catalog calls, so
one IP per request avoids the volume ban), retries on a caller-supplied ``is_block``
predicate, and backs off between attempts. ``use_proxy=False`` (fl.ru) issues a
plain direct request.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Optional

import httpx

from src.core.logging import get_logger
from src.infrastructure.browser.proxy_provider import proxy_provider
from src.infrastructure.http.rotating_client import build_proxy_url

logger = get_logger(__name__)

IsBlock = Callable[[httpx.Response], bool]


class CatalogBlockedError(RuntimeError):
    """The catalog request kept hitting anti-bot blocks / errors across all tries."""


def _pick_proxy() -> Optional[str]:
    p = proxy_provider.get_proxy()
    return build_proxy_url(p) if p else None


async def catalog_request(
    method: str,
    url: str,
    *,
    is_block: IsBlock,
    use_proxy: bool = True,
    tries: int = 4,
    timeout: float = 35.0,
    backoff: float = 5.0,
    **kwargs: Any,
) -> httpx.Response:
    """Issue ``method url`` with proxy rotation + block-retry. Raises on exhaustion."""
    last: Optional[Exception] = None
    for attempt in range(tries):
        proxy = _pick_proxy() if use_proxy else None
        try:
            async with httpx.AsyncClient(
                proxy=proxy, follow_redirects=True, timeout=timeout
            ) as client:
                r = await client.request(method, url, **kwargs)
            if is_block(r):
                last = CatalogBlockedError(f"{method} {url} -> {r.url} [{r.status_code}]")
                await asyncio.sleep(backoff * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except CatalogBlockedError as exc:
            last = exc
        except Exception as exc:  # noqa: BLE001 — transport/HTTP error → retry
            last = exc
            await asyncio.sleep(2.0)
    raise last if last else CatalogBlockedError(f"{method} {url} failed")


async def throttle(base: float, jitter: float) -> None:
    """Polite inter-request pause (async port of the scripts' _throttle)."""
    await asyncio.sleep(base + random.uniform(0, jitter))
