"""fl.ru — httpx RSS feeds (listing) + project page (detail).

Parsers ported verbatim from ``experiment_monitoring/prototype/monitor_proto.py``
(FL.RU section, verified 2026-06-19). RSS is fetched as bytes to avoid ElementTree's
"encoding declaration in unicode string" error; the detail page uses the hybrid
httpx→browser fetch.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BASE_HEADERS, BaseSourceScraper, CHROME_UA
from src.domain.models.monitoring import MonitorItem

# category feeds: 5=programming, 31=AI/ML; base feed guarantees freshness/volume.
FL_FEEDS = [
    "https://www.fl.ru/rss/all.xml",
    "https://www.fl.ru/rss/all.xml?category=5",
    "https://www.fl.ru/rss/all.xml?category=31",
]
_FL_RSS_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/rss+xml, application/xml, */*",
}


def _fl_numeric_id(link: str) -> str:
    """Numeric project ID from an fl.ru project URL (dedup key), else the URL."""
    m = re.search(r"/projects/(\d+)/", link)
    return m.group(1) if m else link


@register_source
class FLScraper(BaseSourceScraper):
    source = "fl"
    headers = _FL_RSS_HEADERS

    async def collect(self, limit: int = 50) -> list[MonitorItem]:
        items: dict[str, dict] = {}
        for url in FL_FEEDS:
            try:
                resp = await self.http.get(url)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            raw_bytes = resp.content
            if not raw_bytes.lstrip().startswith((b"<?xml", b"<rss")):
                continue
            try:
                root = ET.fromstring(raw_bytes)
            except Exception:
                continue
            ch = root.find("channel")
            if ch is None:
                continue
            for it in ch.findall("item"):
                link = (it.findtext("link") or "").strip()
                if not link:
                    continue
                numeric_id = _fl_numeric_id(link)
                if numeric_id in items:
                    continue
                items[numeric_id] = {
                    "id": numeric_id,
                    "title": (it.findtext("title") or "").strip(),
                    "url": link,
                    "pub_date": (it.findtext("pubDate") or "").strip(),
                    "description": (it.findtext("description") or "").strip()[:300],
                }

        if not items:
            raise RuntimeError("No RSS items returned from fl.ru feeds")

        return [
            MonitorItem(
                source="fl",
                id=v["id"],
                title=v["title"],
                url=v["url"],
                amount=None,
                date=v.get("pub_date", ""),
                extra={"desc": v.get("description", "")},
            )
            for v in list(items.values())[:limit]
        ]

    async def detail(self, item: dict) -> dict:
        html = await self.fetch_text(item["url"], headers=BASE_HEADERS)

        title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
        amount = None

        # Primary: Product LD+JSON offers.price
        ld_scripts = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        for s in ld_scripts:
            try:
                d = json.loads(s)
                if d.get("@type") == "Product":
                    offers = d.get("offers") or {}
                    price_val = offers.get("price")
                    currency = offers.get("priceCurrency", "RUB")
                    if price_val and str(price_val) not in ("0", ""):
                        amount = f"{price_val} {currency}"
                    break
            except Exception:
                pass

        if not amount:
            bud_m = re.search(
                r"Бюджет:\s*<span[^>]*>\s*([\d\s]+)<span[^>]*>",
                html, re.DOTALL,
            )
            if bud_m:
                amount = bud_m.group(1).strip().replace("\n", "").replace("  ", " ") + " руб"

        if not amount:
            rss_title = item.get("title", "")
            rss_m = re.search(r"Бюджет:\s*([\d\s]+(?:руб|₽|р\.)[^,)]*)", rss_title)
            if rss_m:
                amount = rss_m.group(1).strip()

        desc_m = re.search(
            r'<div[^>]*class="[^"]*b-post-text[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL,
        )
        desc_text = ""
        if desc_m:
            desc_text = re.sub(r"<[^>]+>", " ", desc_m.group(1)).strip()[:500]

        return {
            "id": item["id"],
            "title": title_m.group(1).strip() if title_m else item["title"],
            "amount": amount or item.get("amount"),
            "description": desc_text or (item.get("extra") or item.get("_extra") or {}).get("desc", ""),
            "url": item["url"],
        }
