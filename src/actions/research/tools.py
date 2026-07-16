"""Web tools for the flat-loop research agent.

Two plain async functions the agent calls directly (no LangChain dispatcher):
``web_search`` (SearXNG via ``SearXngSearchClient``) and ``scrape_url``
(Playwright + proxy + stealth via ``SiteEnrichAction``).
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Error signatures that mean "the proxy connection was the problem", not the
# target site. Used to attribute scrape-attempt time to proxy-pool waste.
_PROXY_ERR_MARKERS = (
    "err_timed_out", "err_tunnel_connection_failed", "err_proxy",
    "err_connection_reset", "err_connection_closed", "err_empty_response",
    "err_socks", "timeout 15000ms", "connecttimeout", "proxyerror",
    "tunnel", "readtimeout",
)


def _is_proxy_error(err: str) -> bool:
    low = err.lower()
    return any(m in low for m in _PROXY_ERR_MARKERS)


async def web_search(query: str, k: int = 5, language: str | None = None) -> list[dict]:
    """Web search via local SearXNG (backed by ``SearXngSearchClient``).

    ``language`` is a BCP-47 / SearXNG language hint ("ru", "en"). When set,
    SearXNG biases the engine map and the returned SERP becomes overwhelmingly
    that language — main lever for getting local results without proxies.

    On failure returns ``[]`` (not an error dict) so callers don't have to
    special-case error sentinels mixed in with real results.
    """
    from src.core.logging import get_logger
    from src.domain.models.requests import SearchRequest
    from src.infrastructure.external_api.search_client import search_client

    log = get_logger(__name__)
    try:
        request = SearchRequest(q=query, num=k)
        response = await search_client.search(request, language=language)
        return [
            {"url": r.link, "title": r.title, "snippet": r.snippet}
            for r in response.organic
        ]
    except Exception as e:
        log.error("web_search failed for %r: %s", query, e)
        return []


async def scrape_url(url: str, *, attempts: int = 2) -> dict:
    """Scrape a URL and return cleaned text.

    Routing (cheapest viable method wins; see ``optimize-scrape/FINDINGS.md``):
      1. Instagram → login-walled, never render: return a light @-handle stub.
      2. Allowlisted SSR domains → proxied httpx GET (~15-40x fewer bytes than a
         browser, equal content). Falls back to the browser if httpx fails/blocks.
      3. Everything else → Playwright browser via ``SiteEnrichAction`` (with
         in-browser resource-blocking), retried across fresh rotating proxies.
    """
    from src.actions.research.http_fetch import (
        host_in_allowlist,
        httpx_ssr_fetch,
        instagram_handle,
        is_instagram,
    )
    from src.domain.utils.content_cleaner import count_words, html_to_text

    t_start = time.monotonic()

    # 1. Instagram: login-wall — return the handle from the URL, don't render.
    if is_instagram(url):
        handle = instagram_handle(url)
        text = f"Instagram profile @{handle}" if handle else "Instagram (login-walled; no public content)"
        return {"url": url, "text": text, "word_count": len(text.split()),
                "success": True, "method": "instagram_stub",
                "perf": {"method": "instagram_stub", "total_s": 0.0,
                         "failed_s": 0.0, "proxy_waste_s": 0.0, "attempts": 0}}

    failed_s = 0.0        # time burnt in attempts that did NOT produce the result
    proxy_waste_s = 0.0   # subset of failed_s attributable to proxy errors
    proxies_tried: list[str] = []

    # 2. httpx-SSR fast-path for allowlisted server-rendered domains.
    if host_in_allowlist(url):
        ssr_stats: dict = {}
        t0 = time.monotonic()
        try:
            html = await httpx_ssr_fetch(url, stats_out=ssr_stats)
            text = html_to_text(html)[:30000]  # let goal-extract pick from the full page
            return {"url": url, "text": text, "word_count": count_words(text),
                    "success": True, "method": "httpx_ssr",
                    "perf": {"method": "httpx_ssr",
                             "total_s": round(time.monotonic() - t_start, 2),
                             "failed_s": ssr_stats.get("failed_s", 0.0),
                             "proxy_waste_s": ssr_stats.get("failed_s", 0.0),
                             "attempts": ssr_stats.get("tries", 1)}}
        except Exception as e:  # noqa: BLE001 — fall back to the browser path
            dur = time.monotonic() - t0
            failed_s += dur
            if _is_proxy_error(str(e)):
                proxy_waste_s += dur
            logger.warning("httpx_ssr fast-path failed for %s after %.1fs (%s) — browser fallback",
                           url, dur, e)

    # 3. Browser path (heavy SPAs, org sites, social profiles).
    from src.actions.site_enricher import SiteEnrichAction

    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        action = SiteEnrichAction()
        t0 = time.monotonic()
        try:
            result = await action.execute(url)
            proxies_tried.append(getattr(action, "last_proxy", None) or "?")
            return {
                "url": url,
                "text": result.text,
                "word_count": len(result.text.split()),
                "success": True,
                "method": "browser",
                "perf": {"method": "browser",
                         "total_s": round(time.monotonic() - t_start, 2),
                         "failed_s": round(failed_s, 2),
                         "proxy_waste_s": round(proxy_waste_s, 2),
                         "attempts": attempt,
                         "proxies": proxies_tried},
            }
        except Exception as e:  # noqa: BLE001 — retry transient proxy/nav failures
            dur = time.monotonic() - t0
            failed_s += dur
            if _is_proxy_error(str(e)):
                proxy_waste_s += dur
            proxies_tried.append(getattr(action, "last_proxy", None) or "?")
            last_err = e
            logger.warning("scrape_url attempt %d/%d failed %s after %.1fs (proxy=%s): %s",
                           attempt, attempts, url, dur, proxies_tried[-1], e)
    return {"url": url, "error": str(last_err), "success": False,
            "perf": {"method": "browser_failed",
                     "total_s": round(time.monotonic() - t_start, 2),
                     "failed_s": round(failed_s, 2),
                     "proxy_waste_s": round(proxy_waste_s, 2),
                     "attempts": attempts,
                     "proxies": proxies_tried}}
