"""HTTP endpoints for the supply-side catalog scrapers.

These page deep through a category and can take a while (throttled + block-aware),
so treat them as heavier than the monitor endpoints. One endpoint per scraper.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.actions.catalog.fl_freelancers import FLFreelancersAction
from src.actions.catalog.kwork_profiles import KworkProfilesAction
from src.actions.catalog.kwork_services import KworkServicesAction
from src.api.auth import get_api_key
from src.domain.models.catalog import (
    FLFreelancersRequest,
    FLFreelancersResponse,
    KworkProfilesRequest,
    KworkProfilesResponse,
    KworkServicesRequest,
    KworkServicesResponse,
)

router = APIRouter(dependencies=[Depends(get_api_key)])


@router.post("/kwork-services", response_model=KworkServicesResponse)
async def kwork_services(request: KworkServicesRequest) -> KworkServicesResponse:
    """Scrape the kwork gig catalog for a category (+ optional card enrichment)."""
    try:
        result = await KworkServicesAction().execute(
            parent=request.parent,
            leaf=request.leaf,
            max_pages=request.max_pages,
            cards=request.cards,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return KworkServicesResponse(
        parent=request.parent,
        leaf=request.leaf,
        total=len(result["gigs"]),
        gigs=result["gigs"],
        cards=result["cards"],
    )


@router.post("/kwork-profiles", response_model=KworkProfilesResponse)
async def kwork_profiles(request: KworkProfilesRequest) -> KworkProfilesResponse:
    """Scrape kwork seller profiles (+ gig portfolios) for the given usernames."""
    try:
        profiles = await KworkProfilesAction().execute(
            usernames=request.usernames, with_gigs=request.with_gigs
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return KworkProfilesResponse(total=len(profiles), profiles=profiles)


@router.post("/fl-freelancers", response_model=FLFreelancersResponse)
async def fl_freelancers(request: FLFreelancersRequest) -> FLFreelancersResponse:
    """Scrape the fl.ru freelancer catalog for a profession (+ optional rate sampling)."""
    try:
        result = await FLFreelancersAction().execute(
            profession=request.profession,
            max_pages=request.max_pages,
            profiles=request.profiles,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FLFreelancersResponse(
        profession=request.profession,
        total=len(result["freelancers"]),
        freelancers=result["freelancers"],
        rates=result["rates"],
        meta=result["meta"],
    )
