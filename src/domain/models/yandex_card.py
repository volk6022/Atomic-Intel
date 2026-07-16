"""Domain model for a Yandex Maps organization CARD.

The org card page (`/maps/org/{seoname}/{oid}/`) exposes a richer SSR object than
the search results — notably `socialLinks` (VK/Telegram/WhatsApp with handles),
`description`, full phones and `ratingData`. Search-result items leave socialLinks
empty, so the card is the primary deterministic source of social-DM channels.

Parsed from `stack[0].results.items[0]` of the largest inline <script> JSON.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class YandexSocialLink(BaseModel):
    type: Optional[str] = None          # vkontakte | telegram | whatsapp | youtube | ...
    href: Optional[str] = None
    label: Optional[str] = Field(None, alias="readableHref")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexOrgCard(BaseModel):
    """Deterministically-scraped enrichment from the org card page."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    oid: str
    seoname: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    social_links: list[YandexSocialLink] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    hours: Optional[str] = None
    rating: Optional[float] = None
    reviews_count: Optional[int] = None
    raw: Optional[dict[str, Any]] = None

    @classmethod
    def from_card_item(cls, item: dict[str, Any], *, oid: str, seoname: str | None,
                       keep_raw: bool = False) -> "YandexOrgCard":
        if not isinstance(item, dict):
            raise ValueError(f"expected dict, got {type(item)!r}")

        social = [
            YandexSocialLink.model_validate(s)
            for s in (item.get("socialLinks") or [])
            if isinstance(s, dict) and s.get("href")
        ]
        phones = [
            str(p.get("number"))
            for p in (item.get("phones") or [])
            if isinstance(p, dict) and p.get("number")
        ]
        wt = item.get("workingTime")
        hours = wt.get("text") if isinstance(wt, dict) else None
        rd = item.get("ratingData") or {}
        return cls(
            oid=str(oid),
            seoname=seoname,
            title=item.get("title"),
            description=item.get("description") or None,
            social_links=social,
            phones=phones,
            hours=hours,
            rating=rd.get("ratingValue"),
            reviews_count=rd.get("reviewCount"),
            raw=item if keep_raw else None,
        )
