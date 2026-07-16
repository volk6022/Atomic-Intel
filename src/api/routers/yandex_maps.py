"""HTTP endpoints for Yandex Maps scraping.

Both routes are thin wrappers over the actions in `src.actions.yandex_maps`.
See `docs/yandex-maps-scraping-experiment-journal.md` for why we use the
XHR-intercept / observation-and-replay approaches.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.actions.yandex_maps import (
    YandexCaptchaError,
    YandexMapsCardAction,
    YandexMapsExtractAction,
    YandexMapsReviewsAction,
)
from src.api.auth import get_api_key
from src.domain.models.requests import (
    YandexMapsCardRequest,
    YandexMapsCardResponse,
    YandexMapsExtractRequest,
    YandexMapsExtractResponse,
    YandexMapsReviewsRequest,
    YandexMapsReviewsResponse,
)

router = APIRouter(dependencies=[Depends(get_api_key)])


@router.post("/extract", response_model=YandexMapsExtractResponse)
async def extract_organizations(request: YandexMapsExtractRequest) -> YandexMapsExtractResponse:
    """Search Yandex Maps for organizations by text query inside a region.

    Returns up to `target_count` unique organizations with the rich schema
    Yandex publishes via its internal `/maps/api/search` endpoint
    (phones, coordinates, hours, services, photos, metro, ИНН, etc.).
    """
    try:
        action = YandexMapsExtractAction()
        organizations = await action.execute(
            query=request.query,
            region_id=request.region_id,
            city_slug=request.city_slug,
            target_count=request.target_count,
            include_raw=request.include_raw,
            ll_lat=request.ll_lat,
            ll_lon=request.ll_lon,
        )
    except YandexCaptchaError as exc:
        raise HTTPException(status_code=503, detail=f"yandex captcha: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — surface upstream errors uniformly
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return YandexMapsExtractResponse(
        organizations=organizations,
        total=len(organizations),
        query=request.query,
        region_id=request.region_id,
    )


@router.post("/reviews", response_model=YandexMapsReviewsResponse)
async def fetch_reviews(request: YandexMapsReviewsRequest) -> YandexMapsReviewsResponse:
    """Fetch reviews for a single organization via httpx SSR pagination.

    GETs the org's `/reviews/?page=N&ranking=…` pages and parses the SSR-embedded
    `reviewResults.reviews` (50/page, no browser/CSRF). Stops on `since_months`
    date window or `max_count`. Falls back to the browser only on captcha.
    """
    try:
        action = YandexMapsReviewsAction()
        reviews = await action.execute(
            business_oid=request.business_oid,
            seoname=request.seoname,
            max_count=request.max_count,
            ranking=request.ranking,
            since_months=request.since_months,
            include_raw=request.include_raw,
        )
    except YandexCaptchaError as exc:
        raise HTTPException(status_code=503, detail=f"yandex captcha: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return YandexMapsReviewsResponse(
        reviews=reviews,
        total=len(reviews),
        business_oid=request.business_oid,
    )


@router.post("/card", response_model=YandexMapsCardResponse)
async def fetch_card(request: YandexMapsCardRequest) -> YandexMapsCardResponse:
    """Fetch the rich org CARD via httpx SSR.

    Returns `socialLinks` (VK/Telegram/WhatsApp with handles), `description`,
    full phones, hours and rating — the deterministic source of social-DM
    channels that the search results omit.
    """
    try:
        action = YandexMapsCardAction()
        card = await action.execute(
            business_oid=request.business_oid,
            seoname=request.seoname,
            include_raw=request.include_raw,
        )
    except YandexCaptchaError as exc:
        raise HTTPException(status_code=503, detail=f"yandex captcha: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return YandexMapsCardResponse(card=card, business_oid=request.business_oid)
