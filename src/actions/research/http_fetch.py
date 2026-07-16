"""httpx-SSR fast-path for cheap server-rendered pages (no browser).

For directory/registry/social-preview domains the useful content is already in
the server-rendered HTML, so a single proxied httpx GET replaces a full Playwright
load — 15-40x fewer bytes at equal-or-better content (verified in
``optimize-scrape/FINDINGS.md`` and ``scale_test/SCALE_RESULTS.md``).

Brotli is intentionally NOT advertised: the runtime lacks a brotli decoder, so a
``Content-Encoding: br`` response would decode to binary garbage that still looks
"long" (high word count) — the single most dangerous footgun found in testing.

Proxy rotation reuses the battle-tested helpers from ``yandex_maps`` (sequential,
dead-port aware — the residential pool is concurrency-capped).
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from src.actions.yandex_maps import _httpx_proxy, _mark_proxy_dead
from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # NO brotli — runtime can't decode `br`
}
_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=20.0)

_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com"}
_INSTA_NON_HANDLE = {"p", "reel", "reels", "tv", "explore", "stories", "accounts"}


def _norm_host(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def _allowlist() -> set[str]:
    return {
        d.strip().lower()
        for d in settings.RESEARCH_HTTPX_SSR_ALLOWLIST.split(",")
        if d.strip()
    }


def host_in_allowlist(url: str) -> bool:
    """True if the URL's host is in the SSR allowlist (exact or sub-domain).

    e.g. ``spb.hh.ru`` matches allowlist entry ``hh.ru``.
    """
    host = _norm_host(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in _allowlist())


def is_instagram(url: str) -> bool:
    return _norm_host(url) in {"instagram.com"} or urlparse(url).netloc.lower() in _INSTAGRAM_HOSTS


def instagram_handle(url: str) -> str:
    """Extract the @handle from an instagram URL, or '' for post/reel/explore links."""
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    first = path.split("/")[0].lower()
    if first in _INSTA_NON_HANDLE:
        return ""
    return path.split("/")[0]


def rewrite_url(url: str) -> str:
    """SSR-friendly URL rewrites applied before an httpx fetch.

    - ``t.me/X`` -> ``t.me/s/X`` (the public web preview is pure SSR; the bare
      ``t.me/X`` page is a JS app-redirect with almost no content).
    """
    p = urlparse(url)
    host = p.netloc.lower()
    if host in ("t.me", "www.t.me") and p.path and not p.path.startswith("/s/"):
        if len(p.path.strip("/")) > 0:
            return f"https://t.me/s{p.path}"
    return url


async def httpx_ssr_fetch(
    url: str, *, tries: int = 6, min_len: int = 1500, stats_out: dict | None = None
) -> str:
    """Proxied gzip GET of an SSR page; returns HTML or raises.

    Rotates proxies sequentially (dead-port aware). Treats a 200 shorter than
    ``min_len`` as a proxy error page and rotates on. When ``stats_out`` is
    given, fills ``{"tries": N, "failed_s": X}`` — attempts used and seconds
    burnt in non-final attempts (≈ proxy-rotation waste).
    """
    import time as _time

    target = rewrite_url(url)
    last: str | None = None
    used = 0
    failed_s = 0.0
    for _ in range(tries):
        used += 1
        proxy = _httpx_proxy()
        t0 = _time.monotonic()
        try:
            async with httpx.AsyncClient(
                proxy=proxy, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
            ) as client:
                resp = await client.get(target)
            html = resp.text
            if resp.status_code == 200 and len(html) >= min_len:
                if stats_out is not None:
                    stats_out.update(tries=used, failed_s=round(failed_s, 2))
                return html
            failed_s += _time.monotonic() - t0
            last = f"status={resp.status_code} len={len(html)}"
        except Exception as exc:  # noqa: BLE001 — rotate on any transport error
            failed_s += _time.monotonic() - t0
            last = f"{type(exc).__name__}: {str(exc)[:80]}"
            low = last.lower()
            if any(s in low for s in ("connect", "timeout", "proxy", "tunnel", "reset")):
                _mark_proxy_dead(proxy)
    if stats_out is not None:
        stats_out.update(tries=used, failed_s=round(failed_s, 2))
    raise RuntimeError(f"httpx_ssr_fetch failed for {target}: {last}")
