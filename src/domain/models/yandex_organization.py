"""Domain model for a Yandex Maps organization.

Mirrors the structure returned by Yandex's internal `/maps/api/search` endpoint
(see `yandex_maps_experiment/results/04_playwright_xhr_intercept_items.json`).
All fields except identifiers are optional — Yandex's payload is partial for
most orgs. The `raw` field carries the full upstream JSON so downstream
consumers can read anything we did not promote to a typed field without us
having to chase every schema change.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class YandexCoordinates(BaseModel):
    """Geo coordinates. Yandex publishes `[lon, lat]` arrays; we normalise to named fields."""

    model_config = ConfigDict(populate_by_name=True)

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class YandexPhone(BaseModel):
    number: str = Field(..., description="Display form, e.g. '+7 (812) 218-28-10'")
    value: Optional[str] = Field(None, description="E.164 form, e.g. '+78122182810'")
    type: Optional[str] = Field(None, description="phone|fax|...")
    info: Optional[str] = Field(None, description="Free-text label, e.g. 'Администратор'")


class YandexCategory(BaseModel):
    id: Optional[str] = None
    name: str
    seoname: Optional[str] = None
    class_: Optional[str] = Field(None, alias="class")
    plural_name: Optional[str] = Field(None, alias="pluralName")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexFeatureValue(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class YandexFeature(BaseModel):
    """Generic feature record. `value` is polymorphic in the upstream schema
    (bool / str / list[{id,name}]), so we keep it as `Any`."""

    id: str
    name: Optional[str] = None
    type: Optional[str] = Field(None, description="bool|enum|text|...")
    value: Any = None
    important: bool = False
    aref: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class YandexPhoto(BaseModel):
    url_template: str = Field(..., alias="urlTemplate", description="`%s` or `{size}` placeholder for size")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexMetroStation(BaseModel):
    id: Optional[str] = None
    name: str
    distance: Optional[str] = None
    distance_value: Optional[float] = Field(None, alias="distanceValue")
    color: Optional[str] = None
    coordinates: Optional[list[float]] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexWorkingHours(BaseModel):
    """Working hours block as returned by Yandex (text + structured availabilities)."""

    text: Optional[str] = None
    availabilities: Optional[list[dict]] = None
    state: Optional[dict] = None
    today_working_status: Optional[dict] = Field(None, alias="todayWorkingStatus")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class YandexAdvertInfo(BaseModel):
    """Ad/promo info; if the org is an advertiser, contains `.ord_info.client.tin` = ИНН."""

    ord_info: Optional[dict] = Field(None, alias="ordInfo")
    promo: Optional[dict] = None
    text_data: Optional[dict] = Field(None, alias="textData")

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    @property
    def inn(self) -> Optional[str]:
        """Shortcut: extract ИНН (tax id) from the nested ordInfo block, if present."""
        if not self.ord_info:
            return None
        client = self.ord_info.get("client") if isinstance(self.ord_info, dict) else None
        if isinstance(client, dict):
            tin = client.get("tin")
            if tin:
                return str(tin)
        return None


class YandexOrganization(BaseModel):
    """A single organization extracted from Yandex Maps via XHR intercept."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # Identity
    oid: str = Field(..., description="Stable Yandex business id")
    seoname: str = Field(..., description="URL slug, e.g. 'dental_konfidens'")
    title: str = Field(..., description="Full name")
    permalink: Optional[str] = None

    # Address & geo
    address: Optional[str] = None
    full_address: Optional[str] = Field(None, alias="fullAddress")
    country: Optional[str] = None
    coordinates: Optional[YandexCoordinates] = None

    # Contacts
    phones: list[YandexPhone] = Field(default_factory=list)
    site: Optional[str] = None
    social_links: list[str] = Field(default_factory=list, alias="socialLinks")

    # Classification
    categories: list[YandexCategory] = Field(default_factory=list)
    rubric_ids: list[str] = Field(default_factory=list, alias="rubricIds")

    # Reputation
    rating: Optional[float] = None
    rating_count: Optional[int] = Field(None, alias="ratingCount")
    reviews_count: Optional[int] = Field(None, alias="reviewsCount")

    # Operations
    working_time: Optional[YandexWorkingHours] = Field(None, alias="workingTime")
    status: Optional[str] = None  # "open" | ...
    services: list[str] = Field(default_factory=list)
    features: list[YandexFeature] = Field(default_factory=list)

    # Media
    photos: list[YandexPhoto] = Field(default_factory=list)

    # Transport
    metro: list[YandexMetroStation] = Field(default_factory=list)

    # Advertiser data (contains ИНН via `.advert.inn`)
    advert: Optional[YandexAdvertInfo] = None

    # Anything we did not promote to a typed field
    raw: Optional[dict[str, Any]] = Field(
        default=None, description="Full upstream JSON, kept for downstream consumers"
    )

    # --- helpers ------------------------------------------------------------

    @property
    def inn(self) -> Optional[str]:
        return self.advert.inn if self.advert else None

    @classmethod
    def from_yandex_item(cls, item: dict[str, Any], *, keep_raw: bool = True) -> "YandexOrganization":
        """Map a raw `data.items[]` entry from `/maps/api/search` to this model.

        Yandex publishes `coordinates` as `[lon, lat]` arrays; flatten into a
        named `YandexCoordinates`. Rating is duplicated across `rating` (legacy)
        and `ratingData` (modern) — prefer the latter.
        """
        if not isinstance(item, dict):
            raise ValueError(f"expected dict, got {type(item)!r}")

        oid = str(item.get("id") or item.get("oid") or item.get("businessId") or "")
        if not oid:
            raise ValueError("yandex item is missing oid/id/businessId")

        coords = None
        raw_coords = item.get("coordinates") or item.get("displayCoordinates")
        if isinstance(raw_coords, (list, tuple)) and len(raw_coords) >= 2:
            try:
                coords = YandexCoordinates(lon=float(raw_coords[0]), lat=float(raw_coords[1]))
            except (TypeError, ValueError):
                coords = None

        rating_data = item.get("ratingData") if isinstance(item.get("ratingData"), dict) else {}
        rating_value = rating_data.get("ratingValue") if rating_data else item.get("rating")
        rating_count = rating_data.get("ratingCount") if rating_data else None
        reviews_count = rating_data.get("reviewCount") if rating_data else item.get("reviewsCount")

        photos_block = item.get("photos") if isinstance(item.get("photos"), dict) else {}
        photo_items = photos_block.get("items", []) if photos_block else []
        photos = [
            YandexPhoto.model_validate(p)
            for p in photo_items
            if isinstance(p, dict) and p.get("urlTemplate")
        ]

        phones_raw = item.get("phones") or []
        phones = [YandexPhone.model_validate(p) for p in phones_raw if isinstance(p, dict)]

        categories_raw = item.get("categories") or []
        categories = [
            YandexCategory.model_validate(c) for c in categories_raw if isinstance(c, dict)
        ]

        features_raw = item.get("features") or []
        features = [
            YandexFeature.model_validate(f) for f in features_raw if isinstance(f, dict)
        ]

        metro_raw = item.get("metro") or []
        metro = [YandexMetroStation.model_validate(m) for m in metro_raw if isinstance(m, dict)]

        wt = item.get("workingTime")
        working_time = YandexWorkingHours.model_validate(wt) if isinstance(wt, dict) else None

        advert_raw = item.get("advert")
        advert = YandexAdvertInfo.model_validate(advert_raw) if isinstance(advert_raw, dict) else None

        # Yandex sometimes lists a single canonical site URL under "urls"/"links";
        # fall back to the first `href` we can find.
        site = item.get("site") or item.get("url")
        if site and not isinstance(site, str):
            site = None
        if not site:
            for link in item.get("links") or []:
                if isinstance(link, dict) and link.get("href"):
                    site = link["href"]
                    break

        social = item.get("socialLinks") or []
        if not isinstance(social, list):
            social = []

        title = item.get("title") or item.get("shortTitle") or item.get("name") or ""

        # seoname: top-level preferred; fall back to chain.seoname (SSR format)
        seoname = item.get("seoname") or ""
        if not seoname:
            chain = item.get("chain")
            if isinstance(chain, dict):
                seoname = chain.get("seoname") or ""

        return cls(
            oid=oid,
            seoname=str(seoname),
            title=str(title),
            permalink=item.get("permalink") or item.get("uri"),
            address=item.get("address"),
            full_address=item.get("fullAddress"),
            country=item.get("country"),
            coordinates=coords,
            phones=phones,
            site=site,
            social_links=[s for s in social if isinstance(s, str)],
            categories=categories,
            rubric_ids=[str(r) for r in (item.get("rubricIds") or [])],
            rating=float(rating_value) if rating_value is not None else None,
            rating_count=int(rating_count) if rating_count is not None else None,
            reviews_count=int(reviews_count) if reviews_count is not None else None,
            working_time=working_time,
            status=item.get("status"),
            services=[s for s in (item.get("services") or []) if isinstance(s, str)],
            features=features,
            photos=photos,
            metro=metro,
            advert=advert,
            raw=item if keep_raw else None,
        )
