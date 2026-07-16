"""kwork.ru — httpx POST XHR (listing) + project page (detail).

Ported verbatim from ``monitor_proto.py`` (KWORK.RU section). The listing is a
form-urlencoded POST returning JSON (``data.pagination.data[]``); the detail page
is HTML parsed via regex over the embedded ``window.stateData`` fields.
"""

from __future__ import annotations

import json
import re

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BASE_HEADERS, BaseSourceScraper, CHROME_UA
from src.domain.models.monitoring import MonitorItem

_KWORK_URL = "https://kwork.ru/projects"
_KWORK_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://kwork.ru/projects",
    "Origin": "https://kwork.ru",
}
_KWORK_CATEGORIES = ["41", "11"]  # scripts/bots/python-ml ; programming


def _kwork_list(data: dict) -> list[dict]:
    d = data.get("data", {})
    if isinstance(d.get("pagination"), dict) and isinstance(d["pagination"].get("data"), list):
        return d["pagination"]["data"]
    if isinstance(d.get("wants"), list):
        return d["wants"]
    return []


@register_source
class KworkScraper(BaseSourceScraper):
    source = "kwork"
    headers = _KWORK_HEADERS

    async def collect(self, limit: int = 50) -> list[MonitorItem]:
        items: dict[str, dict] = {}
        for cat in _KWORK_CATEGORIES:
            try:
                payload = await self.fetch_json(_KWORK_URL, method="POST", data={"c": cat})
            except Exception:
                continue
            for p in _kwork_list(payload):
                pid = str(p.get("id") or p.get("want_id") or "")
                if not pid:
                    continue
                price = p.get("priceLimit") or p.get("possiblePriceLimit")
                items[pid] = {
                    "id": pid,
                    "title": (p.get("name") or "").strip(),
                    "url": f"https://kwork.ru/projects/{pid}",
                    "price": str(price) if price else None,
                    "description": (p.get("description") or "").strip()[:300],
                }

        if not items:
            raise RuntimeError("No items returned from kwork.ru")

        return [
            MonitorItem(
                source="kwork",
                id=v["id"],
                title=v["title"],
                url=v["url"],
                amount=v.get("price"),
                date="",
                extra={"desc": v.get("description", "")},
            )
            for v in list(items.values())[:limit]
        ]

    async def detail(self, item: dict) -> dict:
        html = await self.fetch_text(item["url"], headers=BASE_HEADERS)

        title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
        price_m = re.search(r'"wantPriceLimit"\s*:\s*"?(\d+)"?', html)
        desc_m = re.search(r'"wantDescription"\s*:\s*"((?:[^"\\]|\\.){10,})"', html)
        desc_text = ""
        if desc_m:
            try:
                desc_text = json.loads(f'"{desc_m.group(1)}"')[:500]
            except Exception:
                desc_text = desc_m.group(1)[:500]

        return {
            "id": item["id"],
            "title": title_m.group(1).strip() if title_m else item["title"],
            "amount": price_m.group(1) if price_m else item.get("amount"),
            "description": desc_text or (item.get("extra") or item.get("_extra") or {}).get("desc", ""),
            "url": item["url"],
        }
