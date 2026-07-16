"""kwork seller-profile scraper (benchmark the top players).

Async port of ``experiment_monitoring/experiment-kwork/kwork_profiles_scrape.py``.
Reuses the parsers/headers from :mod:`kwork_services`. Per seller:
  GET  /user/<name>         → profile meta from window.stateData
  POST /user_kworks/<name>  → full gig portfolio (offset/limit JSON)

The CLI variant picked sellers from local catalog samples; the service takes an
explicit ``usernames`` list (the caller ranks candidates from a prior /kwork-services
run).
"""

from __future__ import annotations

from src.actions.catalog.http import catalog_request, throttle
from src.actions.catalog.kwork_services import (
    CARD_HEADERS,
    LIST_HEADERS,
    THROTTLE_BASE,
    THROTTLE_JITTER,
    _extract_js_object,
    _is_block,
    html_to_text,
)
from src.core.logging import get_logger

logger = get_logger(__name__)


class KworkProfilesAction:
    async def fetch_profile_meta(self, name: str) -> dict | None:
        try:
            r = await catalog_request(
                "GET", f"https://kwork.ru/user/{name}", is_block=_is_block, headers=CARD_HEADERS
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("kwork profile meta %s failed: %s", name, exc)
            return None
        sd = _extract_js_object(r.text, "window.stateData")
        if not sd:
            return None
        return {
            "userName": sd.get("userProfileName"),
            "fullName": sd.get("userProfileFullName"),
            "profession": sd.get("userProfileProfession"),
            "description": html_to_text(sd.get("userProfileDescription")),
            "addTime": sd.get("userProfileAddTime"),
            "rating": sd.get("userRating"),
            "sellerLevel": sd.get("userSellerLevel"),
            "totalReviews": sd.get("totalReviewsCount"),
            "totalKworks": sd.get("totalKworks"),
            "skills": [s.get("name") for s in (sd.get("userSkills") or []) if isinstance(s, dict)],
            "location": sd.get("userLocation"),
        }

    async def fetch_user_gigs(self, name: str, page_limit: int = 24) -> list[dict]:
        gigs: list[dict] = []
        offset = 0
        headers = dict(LIST_HEADERS)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json, text/plain, */*"
        headers["Referer"] = f"https://kwork.ru/user/{name}"
        while True:
            try:
                r = await catalog_request(
                    "POST", f"https://kwork.ru/user_kworks/{name}", is_block=_is_block,
                    headers=headers, json={"username": name, "offset": offset, "limit": page_limit},
                )
                payload = r.json()
            except Exception as exc:  # noqa: BLE001
                logger.warning("kwork user gigs %s @offset %d failed: %s", name, offset, exc)
                break
            data = payload.get("data") or {}
            total = data.get("total") or 0
            batch = data.get("data") or []
            for g in batch:
                gigs.append({
                    "id": g.get("id"), "url": g.get("url"), "gtitle": g.get("gtitle"),
                    "price": g.get("price"), "days": g.get("days"),
                    "categoryName": g.get("categoryName"), "categoryId": g.get("categoryId"),
                    "baseVolume": g.get("baseVolume"), "baseVolumeShortName": g.get("baseVolumeShortName"),
                    "conversion": g.get("conversion"), "queueCount": g.get("queueCount"),
                })
            offset += len(batch)
            if not batch or offset >= total:
                break
            await throttle(THROTTLE_BASE, THROTTLE_JITTER)
        return gigs

    async def execute(self, usernames: list[str], with_gigs: bool = True) -> list[dict]:
        profiles: list[dict] = []
        for name in usernames:
            await throttle(THROTTLE_BASE, THROTTLE_JITTER)
            meta = await self.fetch_profile_meta(name) or {}
            gigs: list[dict] = []
            if with_gigs:
                await throttle(THROTTLE_BASE, THROTTLE_JITTER)
                gigs = await self.fetch_user_gigs(name)
            profiles.append({"userName": name, "meta": meta, "gigs": gigs, "gig_count": len(gigs)})
        return profiles
