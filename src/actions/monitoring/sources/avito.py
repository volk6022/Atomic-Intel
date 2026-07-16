"""avito.ru — httpx, MFE state JSON blob (vacancies vertical).

Parsers ported verbatim from ``monitor_proto.py`` (AVITO.RU section, bug-fix #2a/#2b
preserved: the /tag/python-razrabotchik URL populates the MFE catalog with dev
vacancies; base URL needs a keyword post-filter). The hybrid fetch handles avito's
occasional 403 by falling back to the browser (the MFE blob is in SSR HTML either way).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BaseSourceScraper, CHROME_UA
from src.domain.models.monitoring import MonitorItem

_AVITO_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}
_AVITO_URL = "https://www.avito.ru/all/vakansii/tag/python-razrabotchik?s=104"
_AVITO_URL_FALLBACK = "https://www.avito.ru/all/vakansii/tag/razrabotchik?s=104"
_AVITO_URL_BASE = "https://www.avito.ru/all/vakansii?s=104"
_AVITO_IT_KEYWORDS = {
    "python", "django", "fastapi", "flask",
    "разработчик", "developer", "программист",
    "backend", "frontend", "fullstack", "devops",
    "machine learning", "искусственный интеллект",
    "аналитик данных", "data scientist", "data engineer",
    "golang", "java ", "kotlin", "typescript",
    "javascript", "angular", "linux", "docker", "kubernetes",
    "1с программист", "bitrix", "selenium",
    "тестировщик", "postgresql", "mongodb", "kafka",
    "верстальщик", "веб-разработчик", "веб разработчик",
    "software engineer", "мобильный разработчик",
    "android разработчик", "ios разработчик",
}


def _avito_extract_mfe(html: str) -> list[dict]:
    m = re.search(
        r'<script[^>]+type=["\']mime/invalid["\'][^>]+data-mfe-state=["\']true["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []

    state = data.get("state", {})

    def find_catalog(obj, depth=0):
        if depth > 6:
            return None
        if isinstance(obj, dict):
            if "catalog" in obj and isinstance(obj.get("catalog"), dict):
                cat = obj["catalog"]
                if "items" in cat and isinstance(cat["items"], list):
                    return cat
            for v in obj.values():
                r = find_catalog(v, depth + 1)
                if r:
                    return r
        return None

    catalog = find_catalog(state)
    if not catalog:
        return []

    items = []
    for raw in catalog.get("items", []):
        if not isinstance(raw, dict) or "id" not in raw:
            continue
        price = raw.get("priceDetailed") or {}
        sort_ts = raw.get("sortTimeStamp")
        url_path = (raw.get("urlPath") or "").split("?")[0]
        sort_dt = ""
        if sort_ts:
            try:
                sort_dt = str(datetime.fromtimestamp(sort_ts / 1000, tz=timezone.utc).isoformat())
            except Exception:
                sort_dt = str(sort_ts)
        items.append({
            "id": str(raw["id"]),
            "title": raw.get("title", ""),
            "price_string": price.get("fullString", "") or price.get("string", ""),
            "url": f"https://www.avito.ru{url_path}",
            "sort_datetime": sort_dt,
            "location": (raw.get("location") or {}).get("name", ""),
            "description_snippet": (raw.get("description") or "")[:200],
        })
    return items


def _avito_is_it_relevant(item: dict) -> bool:
    text = (item.get("title", "") + " " + item.get("description_snippet", "")).lower()
    return any(kw in text for kw in _AVITO_IT_KEYWORDS)


def _avito_find_item_data(loader: dict) -> dict | None:
    for v in loader.values():
        if not isinstance(v, dict):
            continue
        buyer = v.get("buyerItem") or {}
        if isinstance(buyer, dict):
            candidate = buyer.get("item")
            if isinstance(candidate, dict) and "id" in candidate and "title" in candidate:
                return candidate
        candidate = (v.get("initialData") or {}).get("data", {}).get("item")
        if isinstance(candidate, dict) and "id" in candidate:
            return candidate
        candidate = (v.get("data") or {}).get("item")
        if isinstance(candidate, dict) and "id" in candidate:
            return candidate
    return None


@register_source
class AvitoScraper(BaseSourceScraper):
    source = "avito"
    headers = _AVITO_HEADERS

    async def collect(self, limit: int = 30) -> list[MonitorItem]:
        raw_items: list[dict] = []
        for url in (_AVITO_URL, _AVITO_URL_FALLBACK):
            html = await self.fetch_text(url)
            raw_items = _avito_extract_mfe(html)
            if raw_items:
                break

        if not raw_items:
            seen_ids: set[str] = set()
            for page in (1, 2, 3, 4, 5):
                page_url = _AVITO_URL_BASE + (f"&p={page}" if page > 1 else "")
                html = await self.fetch_text(page_url)
                page_items = _avito_extract_mfe(html)
                if not page_items:
                    break
                for x in page_items:
                    if x["id"] not in seen_ids and _avito_is_it_relevant(x):
                        seen_ids.add(x["id"])
                        raw_items.append(x)
                if len(raw_items) >= limit:
                    break

        if not raw_items:
            raise RuntimeError("No IT-relevant vacancies found in avito")

        return [
            MonitorItem(
                source="avito",
                id=v["id"],
                title=v["title"],
                url=v["url"],
                amount=v.get("price_string") or None,
                date=v.get("sort_datetime", ""),
                extra={"location": v.get("location", ""), "desc": v.get("description_snippet", "")},
            )
            for v in raw_items[:limit]
        ]

    async def detail(self, item: dict) -> dict:
        extra = item.get("extra") or item.get("_extra") or {}
        try:
            html = await self.fetch_text(item["url"])
        except Exception:
            html = ""

        if not html:
            desc_snippet = extra.get("desc", "")
            return {
                "id": item["id"],
                "title": item["title"],
                "amount": item.get("amount"),
                "description": desc_snippet,
                "desc_len": len(desc_snippet),
                "url": item["url"],
                "_note": "detail page unavailable; using listing data",
            }

        # Strategy 1: staticRouterHydrationData
        m = re.search(
            r'(?:window\.__)?staticRouterHydrationData\s*=\s*JSON\.parse\("(.+?)"\);',
            html, re.DOTALL,
        )
        if m:
            try:
                decoded_str = json.loads(f'"{m.group(1)}"')
                data = json.loads(decoded_str)
                loader = data.get("loaderData", {})
                item_data = _avito_find_item_data(loader)
                if item_data:
                    price = item_data.get("priceDetailed") or {}
                    raw_desc = str(item_data.get("description") or "")
                    desc_text = re.sub(r"<[^>]+>", " ", raw_desc).strip()
                    return {
                        "id": str(item_data.get("id", item["id"])),
                        "title": item_data.get("title", item["title"]),
                        "amount": price.get("fullString") or price.get("string") or None,
                        "description": desc_text[:500],
                        "desc_len": len(desc_text),
                        "location": (item_data.get("location") or {}).get("name", ""),
                        "company": (item_data.get("seller") or {}).get("name", ""),
                        "date": (item_data.get("time") or {}).get("date", ""),
                        "url": item["url"],
                    }
            except Exception:
                pass

        # Strategy 2: MFE block on item page
        raw = _avito_extract_mfe(html)
        if raw:
            v = raw[0]
            desc = v.get("description_snippet", "")
            return {
                "id": v["id"],
                "title": v["title"],
                "amount": v.get("price_string") or None,
                "description": desc,
                "desc_len": len(desc),
                "url": item["url"],
            }

        # Strategy 3: minimal regex fallback
        title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
        return {
            "id": item["id"],
            "title": title_m.group(1).strip() if title_m else item["title"],
            "url": item["url"],
            "amount": item.get("amount"),
            "desc_len": 0,
        }
