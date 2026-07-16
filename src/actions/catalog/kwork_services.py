"""kwork gig-catalog scraper (supply side).

Async port of ``experiment_monitoring/experiment-kwork/kwork_services_scrape.py``.
LIST: POST /catalog_kworks_filters/<parent>/<leaf> (page=N, excludeIds) → 24/page.
CARD: GET /<url_path> → inline ``window.stateData`` blob. Pure parsers copied
verbatim; networking goes through the block-aware :func:`catalog_request`.
"""

from __future__ import annotations

import json
import re

from src.actions.catalog.http import catalog_request, throttle
from src.core.logging import get_logger
from src.domain.models.catalog import Gig

logger = get_logger(__name__)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
LIST_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://kwork.ru",
}
CARD_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

LIST_FIELDS = (
    "id", "url", "gtitle", "price", "days", "queueCount",
    "userId", "userName", "convertedUserRating", "userRating",
    "userRatingCount", "sellerLevel", "rating", "topBadge",
    "baseVolume", "baseVolumeShortName",
)

THROTTLE_BASE = 2.0
THROTTLE_JITTER = 1.0


def _is_block(r) -> bool:
    return "not_access" in str(r.url) or r.status_code in (403, 429)


# --- pure parsers (verbatim) ------------------------------------------------
def gigs_from_response(payload: dict) -> tuple[list[dict], dict]:
    kw = payload.get("data", {}).get("stateData", {}).get("viewData", {}).get("kworks", {})
    posts = kw.get("posts", {})
    gigs = posts.get("data", []) if isinstance(posts, dict) else []
    meta = {
        "currentpage": kw.get("currentpage"),
        "total": kw.get("total"),
        "total_found": kw.get("total_found"),
        "items_per_page": kw.get("items_per_page"),
    }
    return gigs, meta


def slim_gig(g: dict, parent: str, leaf: str) -> dict:
    out = {k: g.get(k) for k in LIST_FIELDS}
    out["parent"] = parent
    out["leaf"] = leaf
    return out


def _extract_js_object(text: str, anchor: str) -> dict | None:
    """Balanced {...} JS object literal following `anchor`, string/escape aware."""
    i = text.find(anchor)
    if i == -1:
        return None
    i = text.find("{", i)
    if i == -1:
        return None
    depth, in_str, esc, quote = 0, False, False, ""
    start = i
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str, quote = True, ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    blob = text[start: j + 1]
                    try:
                        return json.loads(blob)
                    except json.JSONDecodeError:
                        return None
    return None


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()


class KworkServicesAction:
    """Scrape the kwork gig catalog for a category, optionally enriching cards."""

    async def fetch_catalog_page(self, parent: str, leaf: str, page: int, exclude_ids: str = "") -> dict:
        path = f"{parent}/{leaf}" if leaf else parent
        url = f"https://kwork.ru/catalog_kworks_filters/{path}"
        headers = dict(LIST_HEADERS)
        headers["Referer"] = f"https://kwork.ru/categories/{path}"
        data = {"page": str(page), "onePage": "1"}
        if exclude_ids:
            data["excludeIds"] = exclude_ids
        r = await catalog_request("POST", url, is_block=_is_block, headers=headers, data=data)
        return r.json()

    async def _fetch_page_safe(self, parent: str, leaf: str, page: int, exclude: str) -> dict | None:
        try:
            return await self.fetch_catalog_page(parent, leaf, page, exclude_ids=exclude)
        except Exception as exc:  # noqa: BLE001
            logger.warning("kwork catalog %s/%s page %d failed: %s", parent, leaf, page, exc)
            return None

    async def scrape_category(self, parent: str, leaf: str, max_pages: int = 8) -> list[dict]:
        first = await self._fetch_page_safe(parent, leaf, 1, "")
        if not first:
            return []
        gigs, meta = gigs_from_response(first)
        total = meta.get("total") or 0
        per = meta.get("items_per_page") or 24
        pages = min(max_pages, -(-total // per) if total else 1)
        all_gigs = [slim_gig(g, parent, leaf) for g in gigs]
        seen = {g["id"] for g in all_gigs}
        empty_streak = 0
        for page in range(2, pages + 1):
            await throttle(THROTTLE_BASE, THROTTLE_JITTER)
            exclude = ",".join(str(i) for i in seen)
            payload = await self._fetch_page_safe(parent, leaf, page, exclude)
            if payload is None:
                break
            page_gigs, _ = gigs_from_response(payload)
            new = [slim_gig(g, parent, leaf) for g in page_gigs if g.get("id") not in seen]
            seen.update(g["id"] for g in new)
            all_gigs.extend(new)
            if not new:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
        return all_gigs

    async def fetch_card(self, url_path: str) -> dict | None:
        url = "https://kwork.ru" + url_path if url_path.startswith("/") else url_path
        try:
            r = await catalog_request("GET", url, is_block=_is_block, headers=CARD_HEADERS)
        except Exception as exc:  # noqa: BLE001
            logger.warning("kwork card %s failed: %s", url_path, exc)
            return None
        sd = _extract_js_object(r.text, "window.stateData")
        if not sd:
            return None
        k = sd.get("kwork", {}) or {}
        extras = sd.get("extras") or (sd.get("viewData", {}) or {}).get("extras") or []
        return {
            "id": k.get("id"),
            "url": url_path,
            "gtitle": k.get("gtitle"),
            "price": k.get("price"),
            "displayedPrice": k.get("displayedPrice"),
            "days": k.get("days"),
            "queueCount": k.get("queueCount"),
            "bookmarkCount": k.get("bookmarkCount"),
            "categoryTitle": k.get("categoryTitle"),
            "gdesc_text": html_to_text(k.get("gdesc") or k.get("gdesc_source")),
            "ginst_text": html_to_text(k.get("ginst")),
            "packages": [
                {"title": p.get("title") or p.get("name"), "price": p.get("price")}
                for p in (k.get("packages") or []) if isinstance(p, dict)
            ],
            "extras": [
                {
                    "title": e.get("title") or e.get("name"),
                    "price": e.get("price"),
                    "duration": e.get("duration"),
                    "description": html_to_text(e.get("description")),
                }
                for e in extras if isinstance(e, dict)
            ],
        }

    async def execute(self, parent: str, leaf: str = "", max_pages: int = 8, cards: int = 0) -> dict:
        gigs = await self.scrape_category(parent, leaf, max_pages=max_pages)
        card_data: list[dict] = []
        if cards:
            ranked = sorted(gigs, key=lambda g: int(g.get("userRatingCount") or 0), reverse=True)
            for g in ranked[:cards]:
                await throttle(THROTTLE_BASE, THROTTLE_JITTER)
                card = await self.fetch_card(g["url"]) if g.get("url") else None
                if card:
                    card["leaf"] = leaf or parent
                    card_data.append(card)
        return {"gigs": [Gig(**g) for g in gigs], "cards": card_data}
