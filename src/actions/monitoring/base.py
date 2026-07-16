"""Base class for demand-side source scrapers.

Every source (hh, fl, kwork, ...) subclasses :class:`BaseSourceScraper` and
implements ``collect`` / ``detail``. The base provides the single **hybrid
fetch** used across all sources: try httpx first (fast, cheap), and only fall
back to the Playwright pool when anti-bot detection says the httpx body is
unusable. This mirrors the ``YandexMapsExtractAction`` strategy but is shared so
no source re-implements the fallback.

The pure parsers (regex/JSON extraction) live in each source module, copied
verbatim from ``experiment_monitoring/prototype/monitor_proto.py``; the base only
owns transport.
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.core.config import settings
from src.core.logging import get_logger
from src.domain.models.monitoring import MonitorItem
from src.infrastructure.browser.pool_manager import pool_manager
from src.infrastructure.browser.proxy_provider import proxy_provider
from src.infrastructure.http import AntibotVerdict, RotatingHTTPClient, detect_antibot

logger = get_logger(__name__)

# Shared browser-like defaults (from monitor_proto.py BASE_HEADERS / CHROME_UA).
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    # NB: no brotli — the runtime may lack a brotli decoder, so a `br` response
    # would decode to garbage and break parsing (same reasoning as yandex_maps).
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


class AntibotBlockedError(RuntimeError):
    """Raised when both httpx and the browser fallback fail to get a clean body."""


class BaseSourceScraper(ABC):
    #: short source key, e.g. "hh"; set on each subclass.
    source: str = ""
    #: default headers for this source's httpx requests.
    headers: dict[str, str] = BASE_HEADERS

    def __init__(self) -> None:
        self.http = RotatingHTTPClient(headers=self.headers)

    # ------------------------------------------------------------------ API
    @abstractmethod
    async def collect(self, limit: int = 25) -> list[MonitorItem]:
        """Return a normalised list of the newest items for this source."""

    @abstractmethod
    async def detail(self, item: dict) -> dict:
        """Fetch and parse the detail page for one item (dict from collect)."""

    # -------------------------------------------------------------- transport
    async def fetch_text(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        allow_browser: bool = True,
        **kwargs: Any,
    ) -> str:
        """httpx-first GET/POST returning HTML text; browser fallback on anti-bot."""
        try:
            resp = await self.http.request(method, url, headers=headers or {}, **kwargs)
            verdict = detect_antibot(resp)
            if verdict == AntibotVerdict.CLEAN:
                return resp.text
            logger.info(
                "%s: httpx verdict=%s on %s — falling back to browser",
                self.source, verdict.value, url,
            )
        except Exception as exc:  # noqa: BLE001 — any transport failure → try browser
            logger.info("%s: httpx failed on %s (%s) — falling back to browser", self.source, url, exc)

        if not allow_browser:
            raise AntibotBlockedError(f"{self.source}: httpx blocked and browser disabled for {url}")
        return await self._browser_get(url)

    async def fetch_json(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> Any:
        """httpx-only JSON fetch (XHR endpoints; browser can't return raw JSON)."""
        resp = await self.http.request(method, url, headers=headers or {}, **kwargs)
        return resp.json()

    async def _browser_get(self, url: str, *, wait_s: float = 0.0) -> str:
        """Render ``url`` in the stealth browser and return page HTML.

        ``wait_s`` adds a settle delay after DOM-ready for JS-hydrated pages
        (e.g. hh.ru embeds its vacancy JSON after an initial network round-trip).
        """
        proxy = proxy_provider.get_proxy() if settings.MONITOR_USE_PROXY else None
        context = await pool_manager.create_context(stealth=True, proxy=proxy)
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT)
            if wait_s:
                await asyncio.sleep(wait_s)
                try:
                    await page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
            else:
                await asyncio.sleep(random.uniform(0.5, 1.5))
            return await page.content()
        finally:
            await context.close()
