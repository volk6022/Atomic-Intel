"""kwork.ru - one form-urlencoded POST returns the whole listing, including the
full brief. There is no second request to make.

What the first version of this module got wrong, and why it matters:

- It truncated ``description`` to 300 characters. The listing already carries the
  complete brief (103-1472 characters across a sample of twelve), so the cut threw
  away exactly the text scoring needs.
- It then fetched a detail page to recover that text. ``kwork.ru/projects/<id>``
  is a 334-byte stub with a ``<meta refresh>`` that httpx does not follow, so the
  parser was reading the stub. The real page at ``/projects/<id>/view`` does serve
  the brief to anonymous visitors - but there is no reason to ask for it twice.
- It dropped ``kwork_count`` (offers already submitted), ``possiblePriceLimit``
  (the client's real ceiling, often triple the stated one), the dates and the
  attachments. Those are what decide whether a job is worth answering.

Filter parameters are separated by hyphens, not underscores: ``price-from``, not
``price_from``. Underscored names are silently ignored, which reads exactly like
"filtering is not supported" - it is. ``kworks-filters[]=0`` means "fewer than
five offers", the slice worth watching.

Listing order is not chronological - postings from 2023 turn up on page one - so
freshness has to come from the dates, never from position.
"""

from __future__ import annotations

from typing import Any, Optional

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BaseSourceScraper, CHROME_UA
from src.core.logging import get_logger
from src.domain.models.monitoring import MonitorItem

logger = get_logger(__name__)

_KWORK_URL = "https://kwork.ru/projects"
_KWORK_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    # Without this header the same URL answers with HTML instead of JSON.
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://kwork.ru/projects",
    "Origin": "https://kwork.ru",
}
_KWORK_CATEGORIES = ["41", "11"]  # scripts/bots/python-ml ; programming

#: ``kworks-filters[]`` bucket for "fewer than five offers submitted".
FEW_OFFERS_FILTER = "0"

#: Listing fields worth carrying into ``extra`` - each one changes the decision
#: to answer a posting, and none of them can be recovered later.
_EXTRA_FIELDS = (
    "kwork_count",          # offers already submitted
    "possiblePriceLimit",   # the client's ceiling, not just the stated budget
    "views_dirty",          # views
    "timeLeft",
    "max_days",
    "date_create",
    "date_expire",
    "category_id",
)


def _kwork_list(data: dict) -> list[dict]:
    payload = data.get("data", {})
    pagination = payload.get("pagination")
    if isinstance(pagination, dict) and isinstance(pagination.get("data"), list):
        return pagination["data"]
    if isinstance(payload.get("wants"), list):
        return payload["wants"]
    return []


def _client_summary(user: Any) -> dict[str, Any]:
    """Flatten the buyer block down to the fields a human would actually weigh."""
    if not isinstance(user, dict):
        return {}
    data = user.get("data") if isinstance(user.get("data"), dict) else user
    return {
        k: data.get(k)
        for k in ("username", "wants_count", "profilePicture", "is_online")
        if data.get(k) is not None
    }


@register_source
class KworkScraper(BaseSourceScraper):
    source = "kwork"
    headers = _KWORK_HEADERS

    async def collect(
        self,
        limit: int = 50,
        *,
        queries: Optional[list[str]] = None,
        price_from: Optional[int] = None,
        few_offers: bool = False,
    ) -> list[MonitorItem]:
        """Collect the newest postings.

        ``queries`` are free-text searches run server-side; when empty the two
        default categories are swept instead. Doing the narrowing on kwork's side
        rather than ours is the whole point - the exchange can already answer
        "budget from N, fewer than five offers", and asking it costs one request
        instead of scoring a hundred irrelevant items.
        """
        requests: list[dict[str, Any]] = []
        if queries:
            requests = [{"keyword": q} for q in queries]
        else:
            requests = [{"c": c} for c in _KWORK_CATEGORIES]

        for req in requests:
            if price_from:
                req["price-from"] = str(int(price_from))
            if few_offers:
                req["kworks-filters[]"] = FEW_OFFERS_FILTER

        items: dict[str, dict] = {}
        for params in requests:
            try:
                payload = await self.fetch_json(_KWORK_URL, method="POST", data=params)
            except Exception as exc:  # noqa: BLE001 - one failed query must not abort the sweep
                logger.info("kwork: query %s failed: %s", params, exc)
                continue
            for posting in _kwork_list(payload):
                pid = str(posting.get("id") or posting.get("want_id") or "")
                if not pid or pid in items:
                    continue
                items[pid] = posting

        if not items:
            raise RuntimeError("No items returned from kwork.ru")

        return [self._to_item(pid, p) for pid, p in list(items.items())[:limit]]

    def _to_item(self, pid: str, posting: dict) -> MonitorItem:
        price = posting.get("priceLimit") or posting.get("possiblePriceLimit")
        extra: dict[str, Any] = {
            # Full brief. The listing is the only place it exists in one piece.
            "desc": (posting.get("description") or "").strip(),
            "category": str(posting.get("category_id") or ""),
        }
        for field in _EXTRA_FIELDS:
            if posting.get(field) is not None:
                extra[field] = posting[field]
        client = _client_summary(posting.get("user"))
        if client:
            extra["client"] = client
        files = posting.get("files")
        if isinstance(files, list) and files:
            extra["files"] = [
                {"name": f.get("name"), "size": f.get("size")}
                for f in files
                if isinstance(f, dict)
            ]

        return MonitorItem(
            source="kwork",
            id=pid,
            title=(posting.get("name") or "").strip(),
            # /projects/<id> is a redirect stub; /view is the real page, and it is
            # what the notification should link to.
            url=f"https://kwork.ru/projects/{pid}/view",
            amount=str(price) if price else None,
            date=str(posting.get("date_create") or ""),
            extra=extra,
        )

    async def detail(self, item: dict) -> dict:
        """No network call: the listing already carried everything.

        Kept because the source interface and the public ``/detail`` route expect
        it. Fetching the page here would spend a request to learn nothing new.
        """
        extra = item.get("extra") or item.get("_extra") or {}
        return {
            "id": item.get("id"),
            "title": item.get("title", ""),
            "amount": item.get("amount"),
            "description": extra.get("desc", ""),
            "url": item.get("url", ""),
            "category": extra.get("category", ""),
            "offers_count": extra.get("kwork_count"),
            "price_ceiling": extra.get("possiblePriceLimit"),
            "client": extra.get("client", {}),
        }
