"""SearXNG-backed SERP client.

Заменяет предыдущий Playwright-based GoogleSearchClient. Стучимся на локальный
SearXNG (по умолчанию http://localhost:8080), который сам разруливает upstream
поисковики и socks5-pool (см. infra/searxng/searxng/settings.yml).

Стратегия выверена прогоном 9 (REPORT_searxng.md):
    VPN на хосте + pool 20 socks5 + retries=2 → 95.3% success rate.

SearXNG ротирует upstream proxy round-robin'ом внутри пула — повторная попытка
с большой вероятностью идёт через новый IP. Между попытками маленькая пауза
(retry_delay) чтобы дать SearXNG моментик сменить курс.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from src.core.config import settings
from src.core.logging import get_logger
from src.domain.models.requests import SearchRequest, SearchResponse, SearchResult


logger = get_logger(__name__)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class SearXngSearchClient:
    """Async SERP-клиент на базе SearXNG JSON API.

    Контракт идентичен прежнему GoogleSearchClient — `async search(SearchRequest)
    -> SearchResponse` — так что call-site'ы (POST /serper, tools.web_search)
    не меняются.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float,
        max_retries: int,
        retry_delay: float,
        min_organic: int,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._min_organic = min_organic
        self._client = httpx.AsyncClient(timeout=timeout, headers=DEFAULT_HEADERS)

    async def search(
        self,
        request: SearchRequest,
        language: str | None = None,
    ) -> SearchResponse:
        last_err: Exception | None = None
        attempts = self._max_retries + 1  # 1 первая + N retry
        for attempt in range(1, attempts + 1):
            try:
                organic = await self._fetch_once(request.q, request.num, language)
                if len(organic) >= self._min_organic:
                    logger.info(
                        "SearXNG search ok q=%r attempt=%d organic=%d",
                        request.q, attempt, len(organic),
                    )
                    return SearchResponse(
                        searchParameters={
                            "q": request.q,
                            "type": "search",
                            "engine": "searxng",
                            "num": request.num,
                        },
                        organic=organic,
                    )
                last_err = RuntimeError(
                    f"empty organic (got {len(organic)}, need ≥{self._min_organic})"
                )
                logger.warning(
                    "SearXNG attempt %d/%d: %s (q=%r)",
                    attempt, attempts, last_err, request.q,
                )
            except (httpx.HTTPError, RuntimeError) as e:
                last_err = e
                logger.warning(
                    "SearXNG attempt %d/%d failed: %s (q=%r)",
                    attempt, attempts, e, request.q,
                )
            if attempt < attempts:
                await asyncio.sleep(self._retry_delay)

        raise Exception(
            f"SearXNG search failed after {attempts} attempts: {last_err}"
        )

    async def _fetch_once(
        self,
        query: str,
        num: int,
        language: str | None = None,
    ) -> list[SearchResult]:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            # SearXNG accepts "all" or a BCP-47-ish code ("en", "ru", "ru-RU").
            # We pass the bare base language ("ru" not "ru-RU") since SearXNG's
            # engine map keys are short codes; "all" is the safe default.
            "language": (language or "en").split("-")[0].lower() if language else "en",
        }
        resp = await self._client.get(f"{self._base_url}/search", params=params)
        if resp.status_code >= 400:
            raise RuntimeError(f"searxng http {resp.status_code}")

        data = resp.json()
        raw = data.get("results") or []

        # Парсинг 1:1 из serp_experiment/approaches/searxng_local.py (выверен
        # 10 прогонами): dedup по link, limit по num, поля title/link/snippet/position.
        organic: list[SearchResult] = []
        seen: set[str] = set()
        for item in raw:
            link = item.get("url") or ""
            if not link.startswith("http") or link in seen:
                continue
            seen.add(link)
            organic.append(
                SearchResult(
                    title=(item.get("title") or "").strip(),
                    link=link,
                    snippet=(item.get("content") or "").strip(),
                    position=len(organic) + 1,
                )
            )
            if len(organic) >= num:
                break
        return organic

    async def aclose(self) -> None:
        await self._client.aclose()


search_client = SearXngSearchClient(
    base_url=settings.SEARXNG_BASE_URL,
    timeout=settings.SEARXNG_TIMEOUT,
    max_retries=settings.SEARXNG_MAX_RETRIES,
    retry_delay=settings.SEARXNG_RETRY_DELAY,
    min_organic=settings.SEARXNG_MIN_ORGANIC,
)
