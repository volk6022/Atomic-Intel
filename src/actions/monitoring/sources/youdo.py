"""youdo.com — httpx internal JSON API (listing POST + detail GET).

Ported verbatim from ``monitor_proto.py`` (YOUDO.COM section, verified 2026-06-18).
Both endpoints return JSON and need no proxy/browser.
"""

from __future__ import annotations

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BaseSourceScraper, CHROME_UA
from src.domain.models.monitoring import MonitorItem

_YOUDO_LIST_URL = "https://youdo.com/api/tasks/tasks/"
_YOUDO_DETAIL_URL = "https://youdo.com/api/tasks/task/{}/"
_YOUDO_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Content-Type": "application/json",
    "Referer": "https://youdo.com/tasks-all-opened-all",
    "Origin": "https://youdo.com",
}


@register_source
class YoudoScraper(BaseSourceScraper):
    source = "youdo"
    headers = _YOUDO_HEADERS

    async def collect(self, limit: int = 50) -> list[MonitorItem]:
        data = await self.fetch_json(
            _YOUDO_LIST_URL,
            method="POST",
            json={"status": "opened", "categories": [4194304], "page": 1},
        )
        result_obj = data.get("ResultObject") or {}
        items_raw = result_obj.get("Items") or []
        if not items_raw:
            raise RuntimeError(
                f"No items in ResultObject. Keys: {list(result_obj.keys())}. "
                f"IsSuccess={data.get('IsSuccess')}"
            )

        items = []
        for t in items_raw[:limit]:
            tid = str(t.get("Id", ""))
            url_rel = t.get("Url", f"/t{tid}")
            items.append(MonitorItem(
                source="youdo",
                id=tid,
                title=t.get("Name", ""),
                url=f"https://youdo.com{url_rel}",
                amount=t.get("BudgetDescription") or None,
                date=t.get("DateTimeString", ""),
                extra={
                    "category": t.get("CategoryFlag", ""),
                    "offers": t.get("OffersCount", 0),
                    "status": t.get("StatusFlag", ""),
                },
            ))
        return items

    async def detail(self, item: dict) -> dict:
        tid = item["id"]
        data = await self.fetch_json(_YOUDO_DETAIL_URL.format(tid), method="GET")

        task = (data.get("ResultObject") or {}).get("TaskData") or {}
        price = (task.get("Price") or {}).get("PriceInHeader") or {}
        creator = ((task.get("CreatorInfo") or {}).get("UserInfo") or {})
        dates = task.get("Dates") or {}

        amount_str = price.get("StringFormat") or None
        if not amount_str and price.get("Value"):
            amount_str = f"{price['Value']} {price.get('CurrencyShort', '')}"

        return {
            "id": tid,
            "title": task.get("Title", item["title"]),
            "amount": amount_str,
            "description": (task.get("Description") or "")[:500],
            "category": (task.get("CategoryInfo") or {}).get("Name", ""),
            "subcategory": (task.get("SubcategoryInfo") or {}).get("Name", ""),
            "status": (task.get("TaskStatus") or {}).get("Text", ""),
            "created": dates.get("CreationDateTime", ""),
            "creator": creator.get("UserName", ""),
            "offers_count": task.get("OffersCount", 0),
            "url": item["url"],
        }
