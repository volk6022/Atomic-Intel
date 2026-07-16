"""Yandex Maps actions — XHR-intercept strategy.

Implements two actions, both derived from the experiments in
`yandex_maps_experiment/` (see `docs/yandex-maps-scraping-experiment-journal.md`):

* :class:`YandexMapsExtractAction` — discovery. Launches a headless browser
  through a residential proxy, navigates to a regional search URL, intercepts
  responses to ``/maps/api/search``, and parses ``data.items[]`` to build
  :class:`YandexOrganization` objects (65+ fields per org including
  phones/coordinates/services/photos/metro/ИНН).

* :class:`YandexMapsReviewsAction` — reviews. Same browser session pattern,
  but observes ``/maps/api/business/fetchReviews`` URLs, then replays them
  via ``page.request.get(...)`` to authenticate against the same-origin
  endpoint with live session cookies.

Both actions are registered in :data:`action_registry`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from src.core.logging import get_logger
from src.domain.models.dsl import CommandType
from src.domain.models.yandex_card import YandexOrgCard
from src.domain.models.yandex_organization import YandexOrganization
from src.domain.models.yandex_review import YandexReview
from src.domain.registry.action_registry import action_registry
from src.infrastructure.browser.pool_manager import pool_manager
from src.infrastructure.browser.proxy_provider import proxy_provider
from src.infrastructure.browser.user_agent_pool import UserAgentPool

logger = get_logger(__name__)


class YandexCaptchaError(RuntimeError):
    """Raised when Yandex SmartCaptcha is detected on the loaded page."""


# Endpoints that the search results SPA hits with org payloads.
_SEARCH_API_MARKERS = (
    "/maps/api/search",
    "search-maps.yandex.ru/v1",
    "fullobjects",
)
# Endpoint that the org reviews tab hits for review pages.
_REVIEWS_API_MARKER = "fetchReviews"

# Paths inside the `/maps/api/search` JSON that may hold the array of orgs.
_SEARCH_ITEMS_PATHS: tuple[tuple[str, ...], ...] = (
    ("data", "items"),
    ("items",),
    ("data", "geo", "items"),
)
# Paths inside the `fetchReviews` JSON that may hold the array of reviews.
_REVIEW_ITEMS_PATHS: tuple[tuple[str, ...], ...] = (
    ("data", "reviews"),
    ("reviews",),
    ("data", "items"),
    ("items",),
)


def _get_in(data: Any, path: tuple[str, ...]) -> Optional[Any]:
    cur = data
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def _extract_array(data: Any, paths: tuple[tuple[str, ...], ...]) -> Optional[list]:
    for path in paths:
        cur = _get_in(data, path)
        if isinstance(cur, list):
            return cur
    return None


def _is_business_item(it: Any) -> bool:
    """`data.items` contains transit stops / metro stations too; we only want orgs."""
    if not isinstance(it, dict):
        return False
    return any(k in it for k in ("permalink", "seoname", "oid")) and bool(
        it.get("id") or it.get("oid") or it.get("businessId")
    )


# --- httpx SSR helpers (no browser) -----------------------------------------
#
# Yandex server-renders the first page of search results and the reviews list
# into a large inline <script> JSON blob. Pure httpx + SSR parsing is ~7x cheaper
# than a browser and far more stable than fetchReviews observe-and-replay (see
# parse-yandex-economy-experiment/). These helpers power the reviews and card
# actions; the browser path is kept only as a captcha fallback.

_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S)
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html",
    "Accept-Language": "ru-RU,ru;q=0.9",
    # NB: no brotli — the runtime lacks a brotli decoder, so a `br` response would
    # decode to garbage, fail JSON parse and trigger an expensive browser fallback.
    "Accept-Encoding": "gzip, deflate",
}


# In-process dead-proxy memory: ports that just connect-failed are skipped for a
# TTL so traffic concentrates on the currently-live subset of the pool. Entries
# expire (the pool is rotating-residential and ports recover).
_DEAD_PROXIES: dict[str, float] = {}
_DEAD_TTL_S = 60.0  # ports rotate live/dead; re-try a benched port fairly soon


def _build_proxy_url(p: dict) -> str:
    server = p["server"]  # e.g. "http://host:port"
    if p.get("username") and "://" in server:
        scheme, rest = server.split("://", 1)
        return f"{scheme}://{p['username']}:{p['password']}@{rest}"
    return server


def _mark_proxy_dead(url: Optional[str]) -> None:
    if url:
        _DEAD_PROXIES[url] = time.monotonic() + _DEAD_TTL_S


def _httpx_proxy() -> Optional[str]:
    """Next proxy URL from the rotating pool, skipping recently-dead ones."""
    n = max(1, len(getattr(proxy_provider, "_proxies", []) or [1]))
    now = time.monotonic()
    fallback: Optional[str] = None
    for _ in range(n):
        p = proxy_provider.get_proxy()
        if not p:
            return None
        url = _build_proxy_url(p)
        fallback = url
        if _DEAD_PROXIES.get(url, 0.0) <= now:
            return url
    return fallback  # whole pool flagged dead — try one anyway


def _iter_big_blobs(html: str):
    """Yield every parseable inline <script> JSON object above ~20 KB.

    A Yandex page embeds several large scripts and the results blob is not always
    the first one, so callers scan all of them for the path they need.
    """
    for m in _SCRIPT_RE.finditer(html):
        t = m.group(1).strip()
        if len(t) < 20_000:
            continue
        try:
            yield json.loads(t)
        except Exception:
            try:
                yield json.loads(t[t.find("{"):])
            except Exception:
                continue


def _big_blob(html: str) -> Optional[dict]:
    """First large inline <script> JSON (any caller that just needs the state)."""
    for blob in _iter_big_blobs(html):
        return blob
    return None


def _ssr_items_from_html(html: str) -> list[dict]:
    """`stack[0].results.items` from whichever big blob actually carries it."""
    for blob in _iter_big_blobs(html):
        try:
            items = blob["stack"][0]["results"]["items"]
        except Exception:
            continue
        if isinstance(items, list) and items:
            return items
    return []


def _ssr_first_item(html: str) -> Optional[dict]:
    """First `stack[0].results.items[0]` — the focal org on a card/reviews page."""
    items = _ssr_items_from_html(html)
    return items[0] if items else None


def _ssr_search_items(html: str) -> list[dict]:
    """SSR-rendered first page of search results (scans all large blobs)."""
    return _ssr_items_from_html(html)


_HTTP_TIMEOUT = httpx.Timeout(connect=4.0, read=20.0, write=20.0, pool=20.0)


async def _one_get(url: str, proxy: Optional[str]) -> str:
    """Single proxied GET. Returns HTML, or raises (captcha / connect / read)."""
    async with httpx.AsyncClient(
        proxy=proxy, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT, follow_redirects=True
    ) as client:
        resp = await client.get(url)
    html = resp.text
    low = html.lower()
    if "smartcaptcha" in low or "showcaptcha" in low:
        raise YandexCaptchaError(f"captcha on {url[:120]}")
    if len(html) < 50_000:  # SSR pages are ~600 KB; a short body == proxy error page
        raise RuntimeError(f"short body ({len(html)}B) — likely proxy error page")
    return html


async def _http_get_html(url: str, *, tries: int = 20) -> str:
    """GET a Yandex SSR page, rotating proxies SEQUENTIALLY one at a time.

    The puls-proxy pool is concurrency-capped — firing many proxies at once trips
    the cap and turns live ports into timeouts. Sequential with a short connect
    timeout is both reliable and cheap: dead/unprovisioned ports are abandoned in
    ~5 s, live ports answer in ~4-5 s.
    """
    last_exc: Optional[Exception] = None
    for _ in range(tries):
        proxy = _httpx_proxy()
        try:
            return await _one_get(url, proxy)
        except YandexCaptchaError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Port not accepting connections → bench it; keep slow-but-live ports.
            _mark_proxy_dead(proxy)
            last_exc = exc
        except Exception as exc:  # noqa: BLE001 — read timeout / short body; just rotate
            last_exc = exc
    raise RuntimeError(f"httpx GET failed after {tries} proxies: {last_exc}")


def _parse_review_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


class YandexMapsExtractAction:
    """Discovery: text-query search inside a region → list[YandexOrganization]."""

    def __init__(self) -> None:
        self.pool_manager = pool_manager
        self.user_agent_pool = UserAgentPool()
        self.scroll_limit = 25
        self.scroll_pause_ms = 900
        self.captured_response_timeout = 10.0

    async def execute(
        self,
        query: str,
        region_id: int = 2,
        city_slug: str = "saint-petersburg",
        target_count: int = 40,
        include_raw: bool = True,
        ll_lat: Optional[float] = None,
        ll_lon: Optional[float] = None,
    ) -> list[YandexOrganization]:
        """httpx SSR-first discovery; browser fallback on captcha/short-body.

        Yandex SSR-renders the first ~25 results into the page's inline JSON. For
        a tile-based grid (small radius per query) that first page is the whole
        answer, so a single httpx GET replaces a full browser session (~7x cheaper
        and dodges ERR_PROXY_AUTH_UNSUPPORTED). The browser path (with DOM scroll)
        is kept for captcha and for queries that need pagination past the SSR page.
        """
        search_url = (
            f"https://yandex.ru/maps/{region_id}/{city_slug}/search/"
            f"{quote(query, safe='')}/"
        )
        if ll_lat is not None and ll_lon is not None:
            search_url += f"?ll={ll_lon},{ll_lat}&z=17"
        try:
            html = await _http_get_html(search_url)
            items = _ssr_search_items(html)
            if items:
                orgs = self._parse_captured(
                    [{"url": "ssr://httpx", "status": 200,
                      "body": json.dumps({"items": items})}],
                    include_raw=include_raw,
                )
                logger.info(
                    "yandex_maps.extract(httpx-ssr): query=%r ssr_items=%d orgs=%d",
                    query, len(items), len(orgs),
                )
                return orgs
            logger.info("extract httpx-ssr: no items for %r — browser fallback", query)
        except YandexCaptchaError:
            logger.warning("extract httpx-ssr captcha for %r — browser fallback", query)
        except Exception as exc:  # noqa: BLE001 — fall back to the browser path
            logger.warning("extract httpx-ssr failed for %r (%s) — browser fallback",
                           query, exc)
        return await self._execute_browser(
            query, region_id, city_slug, target_count, include_raw, ll_lat, ll_lon,
        )

    async def _execute_browser(
        self,
        query: str,
        region_id: int = 2,
        city_slug: str = "saint-petersburg",
        target_count: int = 40,
        include_raw: bool = True,
        ll_lat: Optional[float] = None,
        ll_lon: Optional[float] = None,
    ) -> list[YandexOrganization]:
        proxy = proxy_provider.get_proxy() or None
        user_agent = self.user_agent_pool.get_user_agent()
        logger.info(
            "yandex_maps.extract: query=%r region_id=%s city=%s target=%s proxy=%s",
            query, region_id, city_slug, target_count, bool(proxy),
        )

        context = await self.pool_manager.create_context(
            user_agent=user_agent,
            stealth=True,
            proxy=proxy,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1440, "height": 900},
        )

        captured: list[dict[str, Any]] = []
        pending_tasks: list[asyncio.Task] = []

        async def _capture(resp) -> None:
            url = resp.url
            try:
                body = await resp.text()
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.debug("failed to read response body for %s: %s", url[:120], exc)
                return
            captured.append({"url": url, "status": resp.status, "body": body})
            logger.debug("captured XHR %s %s (%dB)", resp.status, url[:120], len(body))

        def on_response(resp) -> None:
            # `page.on("response", …)` is synchronous; schedule async work and
            # remember the task so we can drain it before the context closes.
            if any(m in resp.url for m in _SEARCH_API_MARKERS):
                pending_tasks.append(asyncio.create_task(_capture(resp)))

        try:
            page = await context.new_page()
            page.on("response", on_response)

            url = f"https://yandex.ru/maps/{region_id}/{city_slug}/search/{quote(query, safe='')}/"
            if ll_lat is not None and ll_lon is not None:
                url += f"?ll={ll_lon},{ll_lat}&z=17"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                logger.warning("page.goto failed: %s", exc)
                raise

            content_lower = (await page.content()).lower()
            if "smartcaptcha" in content_lower or "showcaptcha" in content_lower:
                raise YandexCaptchaError(f"captcha on initial load of {url}")

            try:
                await page.wait_for_selector(
                    ".search-list-view, .search-snippet-view", timeout=20_000
                )
            except Exception as exc:
                logger.warning("results panel never appeared: %s", exc)

            # Extract SSR-rendered first page of results (Yandex switched from
            # pure XHR to server-side rendering the initial batch in a <script>
            # tag; pagination still fires XHR /maps/api/search on scroll).
            ssr_items = await self._extract_ssr_items(page)

            await self._scroll_until(page, target_count)

            # Drain pending body reads before closing the context (else
            # `resp.text()` will fail with "Target page, context or browser
            # has been closed").
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
        finally:
            try:
                await context.close()
            except Exception:
                pass

        # Merge SSR items (initial page) with XHR items (pagination scrolls).
        # SSR items are injected as a synthetic "captured" response so the same
        # _parse_captured code path handles dedup.
        if ssr_items:
            captured.insert(0, {"url": "ssr://initial", "status": 200,
                                 "body": json.dumps({"items": ssr_items})})

        orgs = self._parse_captured(captured, include_raw=include_raw)
        logger.info(
            "yandex_maps.extract: ssr=%d captured=%d unique_orgs=%d",
            len(ssr_items), len(captured), len(orgs),
        )
        return orgs

    async def _extract_ssr_items(self, page) -> list[dict[str, Any]]:
        """Extract the initial search results from the SSR JSON embedded in <script>.

        Yandex Maps now renders the first page of results server-side: the data
        lives in the largest <script> block as
        ``{stack: [{results: {items: [...]}}]}``.
        Pagination still uses the old /maps/api/search XHR (handled elsewhere).
        """
        try:
            scripts = await page.query_selector_all("script")
            for s in scripts:
                text = await s.inner_text()
                if len(text) < 100_000:
                    continue
                try:
                    data = json.loads(text)
                except Exception:
                    continue
                stack = data.get("stack")
                if not isinstance(stack, list) or not stack:
                    continue
                results = stack[0].get("results") if isinstance(stack[0], dict) else None
                if not isinstance(results, dict):
                    continue
                items = results.get("items")
                if isinstance(items, list):
                    logger.debug("ssr_extract: found %d items in script tag", len(items))
                    return items
        except Exception as exc:
            logger.debug("ssr_extract failed: %s", exc)
        return []

    async def _scroll_until(self, page, target_count: int) -> None:
        """DOM-scroll until either target reached or the list stops growing."""
        count_js = (
            "() => document.querySelectorAll("
            "'li.search-snippet-view, div.search-snippet-view'"
            ").length"
        )
        scroll_js = """() => {
            const list = document.querySelector(
                '.scroll__container, .search-list-view__list, .search-list-view'
            ) || document.querySelector('div[class*=search-list]');
            if (list) list.scrollBy(0, 2000);
            window.scrollBy(0, 1500);
        }"""

        seen, stale = 0, 0
        for _ in range(self.scroll_limit):
            try:
                count = await page.evaluate(count_js)
            except Exception:
                count = seen
            if count >= target_count:
                break
            if count == seen:
                stale += 1
                if stale >= 3:
                    break
            else:
                stale = 0
            seen = count
            try:
                await page.evaluate(scroll_js)
            except Exception:
                pass
            await page.wait_for_timeout(self.scroll_pause_ms)

    def _parse_captured(
        self, captured: list[dict[str, Any]], *, include_raw: bool
    ) -> list[YandexOrganization]:
        orgs: list[YandexOrganization] = []
        seen_oids: set[str] = set()

        for cap in captured:
            body = cap.get("body") or ""
            if len(body) < 80:
                continue
            try:
                data = json.loads(body)
            except Exception:
                continue

            items = _extract_array(data, _SEARCH_ITEMS_PATHS)
            if not items:
                continue

            for raw_item in items:
                if not _is_business_item(raw_item):
                    continue
                oid = str(
                    raw_item.get("id") or raw_item.get("oid") or raw_item.get("businessId") or ""
                )
                if not oid or oid in seen_oids:
                    continue
                try:
                    org = YandexOrganization.from_yandex_item(raw_item, keep_raw=include_raw)
                except Exception as exc:
                    logger.debug("skipping malformed org item oid=%s: %s", oid, exc)
                    continue
                seen_oids.add(oid)
                orgs.append(org)

        return orgs


class YandexMapsCardAction:
    """Card: fetch the rich org page via httpx SSR → YandexOrgCard.

    The card page carries `socialLinks` (with @-handles), `description`, full
    phones and `ratingData` that the search results omit — the primary
    deterministic source of social-DM channels for outreach.
    """

    async def execute(
        self,
        business_oid: str,
        seoname: str,
        include_raw: bool = False,
    ) -> YandexOrgCard:
        url = f"https://yandex.ru/maps/org/{seoname}/{business_oid}/"
        logger.info("yandex_maps.card: oid=%s seoname=%s", business_oid, seoname)
        html = await _http_get_html(url)
        item = _ssr_first_item(html)
        if not item:
            raise RuntimeError(f"card SSR item not found for oid={business_oid}")
        card = YandexOrgCard.from_card_item(
            item, oid=business_oid, seoname=seoname, keep_raw=include_raw
        )
        logger.info(
            "yandex_maps.card: oid=%s social=%d phones=%d descr=%s",
            business_oid, len(card.social_links), len(card.phones),
            bool(card.description),
        )
        return card


class YandexMapsReviewsAction:
    """Reviews: httpx SSR `?page=N&ranking=…` pagination (browser = captcha fallback)."""

    def __init__(self) -> None:
        self.pool_manager = pool_manager
        self.user_agent_pool = UserAgentPool()
        self.scroll_iterations = 5
        self.scroll_pause_ms = 1200

    async def execute(
        self,
        business_oid: str,
        seoname: str,
        max_count: int = 50,
        ranking: str = "by_time",
        since_months: Optional[int] = None,
        include_raw: bool = True,
    ) -> list[YandexReview]:
        """httpx SSR pagination: GET /reviews/?page=N&ranking=…; stop on date/cap."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=since_months * 30.4)
            if since_months else None
        )
        base = f"https://yandex.ru/maps/org/{seoname}/{business_oid}/reviews/"
        logger.info(
            "yandex_maps.reviews(ssr): oid=%s seoname=%s max=%s ranking=%s since_months=%s",
            business_oid, seoname, max_count, ranking, since_months,
        )
        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        stop = False
        for page in range(1, 13):  # SSR depth limit ~12 pages (~600 reviews)
            try:
                html = await _http_get_html(base + f"?page={page}&ranking={ranking}")
            except YandexCaptchaError:
                logger.warning("reviews httpx hit captcha; falling back to browser")
                return await self._execute_browser(
                    business_oid, seoname, count=max_count, ranking=ranking,
                    pages=max(1, (max_count + 49) // 50), include_raw=include_raw,
                )
            item = _ssr_first_item(html)
            revs = (item or {}).get("reviewResults", {}).get("reviews") if item else None
            if not revs:
                break
            page_window = 0
            for rv in revs:
                if not isinstance(rv, dict):
                    continue
                rid = str(rv.get("reviewId") or rv.get("id") or rv.get("publicId") or "")
                if not rid or rid in seen_ids:
                    continue
                if cutoff is not None:
                    d = _parse_review_dt(rv.get("updatedTime"))
                    if d is not None:
                        if d < cutoff:
                            continue
                        page_window += 1
                seen_ids.add(rid)
                collected.append(rv)
                if len(collected) >= max_count:
                    stop = True
                    break
            if stop:
                break
            # stop once a whole page is entirely outside the date window
            if cutoff is not None and page_window == 0:
                break
            await asyncio.sleep(0.4)

        reviews = self._dedup_reviews(collected, include_raw=include_raw)
        logger.info(
            "yandex_maps.reviews(ssr): oid=%s collected=%d", business_oid, len(reviews),
        )
        return reviews

    async def _execute_browser(
        self,
        business_oid: str,
        seoname: str,
        count: int = 50,
        ranking: str = "by_time",
        pages: int = 1,
        include_raw: bool = True,
    ) -> list[YandexReview]:
        """Legacy browser observe-and-replay path; used only as captcha fallback."""
        proxy = proxy_provider.get_proxy() or None
        user_agent = self.user_agent_pool.get_user_agent()
        logger.info(
            "yandex_maps.reviews: oid=%s seoname=%s count=%s ranking=%s pages=%s",
            business_oid, seoname, count, ranking, pages,
        )

        context = await self.pool_manager.create_context(
            user_agent=user_agent,
            stealth=True,
            proxy=proxy,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1440, "height": 900},
        )

        observed_urls: list[str] = []

        def on_response(resp) -> None:
            if _REVIEWS_API_MARKER in resp.url and resp.status == 200:
                observed_urls.append(resp.url)

        org_url = f"https://yandex.ru/maps/org/{seoname}/{business_oid}/reviews/"
        all_reviews: list[dict[str, Any]] = []

        try:
            page = await context.new_page()
            page.on("response", on_response)

            try:
                await page.goto(org_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                logger.warning("page.goto reviews failed: %s", exc)
                raise

            content_lower = (await page.content()).lower()
            if "smartcaptcha" in content_lower or "showcaptcha" in content_lower:
                raise YandexCaptchaError(f"captcha on reviews page {org_url}")

            try:
                await page.wait_for_selector(
                    ".business-reviews-card-view, .business-review-view, .scroll__container",
                    timeout=20_000,
                )
            except Exception as exc:
                logger.debug("reviews ui not detected: %s", exc)

            await self._scroll_reviews_pane(page)
            # Let the last batch of `fetchReviews` XHRs land in our observer.
            await asyncio.sleep(1.5)

            # Replay each observed URL via the live session — this is what the
            # research found to be the only reliable way to read the full body
            # (param ordering & cookies must match exactly).
            seen_urls: set[str] = set()
            for u in observed_urls[: max(1, pages)]:
                if u in seen_urls:
                    continue
                seen_urls.add(u)
                try:
                    resp = await page.request.get(
                        u,
                        headers={
                            "Referer": org_url,
                            "Accept": "application/json, text/plain, */*",
                            "X-Requested-With": "XMLHttpRequest",
                        },
                        timeout=30_000,
                    )
                except Exception as exc:
                    logger.warning("fetchReviews replay failed for %s: %s", u[:120], exc)
                    continue

                if resp.status != 200:
                    logger.warning("fetchReviews replay %s -> %s", u[:120], resp.status)
                    continue

                try:
                    data = await resp.json()
                except Exception as exc:
                    logger.warning("fetchReviews replay JSON parse failed: %s", exc)
                    continue

                items = _extract_array(data, _REVIEW_ITEMS_PATHS)
                if items:
                    all_reviews.extend(items)
        finally:
            try:
                await context.close()
            except Exception:
                pass

        reviews = self._dedup_reviews(all_reviews, include_raw=include_raw)
        logger.info(
            "yandex_maps.reviews: observed=%d unique_reviews=%d",
            len(observed_urls), len(reviews),
        )
        return reviews

    async def _scroll_reviews_pane(self, page) -> None:
        scroll_js = """() => {
            const c = document.querySelector(
                '.scroll__container, .business-reviews-card-view, div[class*=reviews]'
            );
            if (c) c.scrollBy(0, 4000);
            window.scrollBy(0, 3000);
        }"""
        for _ in range(self.scroll_iterations):
            try:
                await page.evaluate(scroll_js)
            except Exception:
                pass
            await page.wait_for_timeout(self.scroll_pause_ms)

    def _dedup_reviews(
        self, items: list[dict[str, Any]], *, include_raw: bool
    ) -> list[YandexReview]:
        seen: set[str] = set()
        out: list[YandexReview] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            rid = str(raw.get("reviewId") or raw.get("id") or raw.get("publicId") or "")
            if not rid or rid in seen:
                continue
            try:
                review = YandexReview.from_yandex_item(raw, keep_raw=include_raw)
            except Exception as exc:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("skipping malformed review %s: %s", rid, exc)
                continue
            seen.add(rid)
            out.append(review)
        return out


action_registry.register(CommandType.YANDEX_MAPS_EXTRACT)(YandexMapsExtractAction)
action_registry.register(CommandType.YANDEX_MAPS_REVIEWS)(YandexMapsReviewsAction)
