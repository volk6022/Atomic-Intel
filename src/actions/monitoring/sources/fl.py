"""fl.ru - RSS feeds for the listing, the project page plus one hidden endpoint
for the detail.

Three things this module knows that are not obvious from the site:

1. The project page carries everything in a ``Product`` LD+JSON block: the full
   brief, the budget under ``offers.price``, and the client's rating under
   ``aggregateRating``. The old ``b-post-text`` class the first parser looked for
   no longer exists on the page at all, which is why detail used to come back
   empty.
2. ``GET /projects/<id>/offers/range/`` answers to anonymous callers and returns
   how many freelancers already responded and the min/max of what they asked for.
   Nothing in the interface shows ``offersWithAttachCount`` at all. The payload is
   base64 wrapping a JWT; the signature is irrelevant, only the body is read.
3. The site's own filters (country, budget, "fewer than 2 offers") are stored
   server-side against the session, not in the URL, so a logged-out scraper cannot
   reproduce them. Only the category path, the section and pagination are
   addressable - competition filtering has to happen on our side, via point 2.

Nothing here needs a login. The only thing behind the wall is file attachments.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Optional

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BASE_HEADERS, BaseSourceScraper, CHROME_UA
from src.core.logging import get_logger
from src.domain.models.monitoring import MonitorItem

logger = get_logger(__name__)

# category feeds: 5=programming, 31=AI/ML; the base feed guarantees freshness.
FL_FEEDS = [
    "https://www.fl.ru/rss/all.xml",
    "https://www.fl.ru/rss/all.xml?category=5",
    "https://www.fl.ru/rss/all.xml?category=31",
]
_FL_RSS_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "application/rss+xml, application/xml, */*",
}
_OFFERS_RANGE_URL = "https://www.fl.ru/projects/{pid}/offers/range/"

_LD_JSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_BUDGET_IN_TITLE_RE = re.compile(r"Бюджет:\s*([\d\s]+(?:руб|₽|р\.)[^,)]*)")


def _fl_numeric_id(link: str) -> str:
    """Numeric project id from an fl.ru URL (the dedup key), else the URL itself."""
    m = re.search(r"/projects/(\d+)/", link)
    return m.group(1) if m else link


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", value)).strip()


def _b64(value: str) -> bytes:
    """urlsafe base64 with the padding the encoder left off."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decode_offers_range(raw: Any) -> dict[str, Any]:
    """Unwrap the ``offers/range`` payload: JSON -> base64 -> JWT body -> JSON.

    The token is never verified. We are reading a number the site already renders
    to anonymous visitors; the signature protects fl.ru, not us, and checking it
    would need a key we have no business holding.

    Returns ``{}`` for the shapes that mean "no data" - notably contests, which
    answer ``{"error": "auth_failed"}``.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict) or raw.get("error") or not raw.get("result"):
        return {}
    try:
        jwt = _b64(str(raw["result"])).decode("utf-8", "replace")
        payload = json.loads(_b64(jwt.split(".")[1]))
    except (ValueError, IndexError, binascii.Error, UnicodeDecodeError) as exc:
        logger.info("fl: could not read offers/range payload: %s", exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_product_ld(html: str) -> dict[str, Any]:
    """Pull the ``Product`` LD+JSON block out of a project page.

    A project with no stated budget simply has no ``offers`` block - that is the
    site saying "negotiable", not a parsing failure, so the caller must keep the
    item rather than drop it.
    """
    for block in _LD_JSON_RE.findall(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return {}


@register_source
class FLScraper(BaseSourceScraper):
    source = "fl"
    headers = _FL_RSS_HEADERS

    async def collect(self, limit: int = 50) -> list[MonitorItem]:
        items: dict[str, dict] = {}
        for url in FL_FEEDS:
            try:
                resp = await self.http.get(url)
            except Exception as exc:  # noqa: BLE001 - one dead feed must not kill the sweep
                logger.info("fl: feed %s failed: %s", url, exc)
                continue
            if resp.status_code != 200:
                continue
            raw_bytes = resp.content
            # Parse from bytes: ElementTree refuses a str carrying an encoding
            # declaration.
            if not raw_bytes.lstrip().startswith((b"<?xml", b"<rss")):
                continue
            try:
                root = ET.fromstring(raw_bytes)
            except ET.ParseError:
                continue
            channel = root.find("channel")
            if channel is None:
                continue
            for entry in channel.findall("item"):
                link = (entry.findtext("link") or "").strip()
                if not link:
                    continue
                numeric_id = _fl_numeric_id(link)
                if numeric_id in items:
                    continue
                title = (entry.findtext("title") or "").strip()
                budget = _BUDGET_IN_TITLE_RE.search(title)
                items[numeric_id] = {
                    "id": numeric_id,
                    "title": title,
                    "url": link,
                    "pub_date": (entry.findtext("pubDate") or "").strip(),
                    # No truncation: the RSS teaser is already cut by fl.ru (36 of
                    # 60 entries in a sample ended mid-word), and cutting it again
                    # loses the little that survived.
                    "description": _strip_html(entry.findtext("description") or ""),
                    # The feed's own rubric. More reliable than keyword matching,
                    # and it is what routes an item to contour A or B.
                    "category": (entry.findtext("category") or "").strip(),
                    "amount": budget.group(1).strip() if budget else None,
                }

        if not items:
            raise RuntimeError("No RSS items returned from fl.ru feeds")

        return [
            MonitorItem(
                source="fl",
                id=v["id"],
                title=v["title"],
                url=v["url"],
                amount=v.get("amount"),
                date=v.get("pub_date", ""),
                extra={
                    "desc": v.get("description", ""),
                    "category": v.get("category", ""),
                },
            )
            for v in list(items.values())[:limit]
        ]

    async def offers_range(self, project_id: str) -> dict[str, Any]:
        """Competition stats for one project, or ``{}`` when unavailable.

        Cheap enough to call on every new item: one request, no page render. What
        comes back is the reason to open the posting at all - four freelancers
        who asked 1200-25000 is a different proposition from forty who asked 500.
        """
        url = _OFFERS_RANGE_URL.format(pid=project_id)
        try:
            resp = await self.http.get(
                url,
                headers={
                    "Accept": "application/json, */*",
                    "Referer": f"https://www.fl.ru/projects/{project_id}/",
                },
            )
        except Exception as exc:  # noqa: BLE001 - stats are a bonus, never a blocker
            logger.info("fl: offers/range failed for %s: %s", project_id, exc)
            return {}
        if resp.status_code != 200:
            return {}
        return decode_offers_range(resp.text)

    async def detail(self, item: dict) -> dict:
        html = await self.fetch_text(item["url"], headers=BASE_HEADERS)
        extra = item.get("extra") or item.get("_extra") or {}

        product = parse_product_ld(html)
        description = _strip_html(str(product.get("description") or ""))

        offers = product.get("offers") or {}
        amount: Optional[str] = None
        price = offers.get("price")
        if price and str(price) not in ("0", ""):
            amount = f"{price} {offers.get('priceCurrency', 'RUB')}"

        rating = product.get("aggregateRating") or {}
        client = {
            "rating": rating.get("ratingValue"),
            "reviews": rating.get("reviewCount") or rating.get("ratingCount"),
        }

        if not description:
            title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
            logger.info(
                "fl: no LD+JSON description for %s (page %s bytes, h1=%s)",
                item.get("id"), len(html), bool(title_m),
            )

        stats = await self.offers_range(str(item["id"]))

        title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
        return {
            "id": item["id"],
            "title": title_m.group(1).strip() if title_m else item.get("title", ""),
            "amount": amount or item.get("amount"),
            "description": description or extra.get("desc", ""),
            "url": item["url"],
            "category": extra.get("category", ""),
            "client": {k: v for k, v in client.items() if v is not None},
            # Empty for contests and for postings with no offers yet; the caller
            # must treat "missing" as "unknown", not as "zero competition".
            "offers_stats": stats,
        }
