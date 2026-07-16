"""HTTP endpoints for the demand-side monitor (job/order feeds).

Source-agnostic: routes take a ``{source}`` path param and dispatch through
``SOURCE_REGISTRY`` (hh, avito, superjob, habr, zarplata, fl, kwork, youdo). Each
scraper implements the hybrid httpx→browser fetch from ``BaseSourceScraper``.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.actions.monitoring import SOURCE_REGISTRY, get_scraper
from src.actions.monitoring.base import AntibotBlockedError
from src.api.auth import get_api_key
from src.domain.models.monitoring import (
    MonitorCollectRequest,
    MonitorCollectResponse,
    MonitorDetailRequest,
    MonitorDetailResponse,
)

router = APIRouter(dependencies=[Depends(get_api_key)])


@router.get("/sources")
async def list_sources() -> dict:
    """List the registered source keys."""
    return {"sources": sorted(SOURCE_REGISTRY.keys())}


@router.post("/{source}/collect", response_model=MonitorCollectResponse)
async def collect(source: str, request: MonitorCollectRequest) -> MonitorCollectResponse:
    """Collect the newest normalised items for one source."""
    if source not in SOURCE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown source: {source}")
    try:
        items = await get_scraper(source).collect(limit=request.limit)
    except AntibotBlockedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface upstream errors uniformly
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MonitorCollectResponse(source=source, total=len(items), items=items)


@router.post("/{source}/detail", response_model=MonitorDetailResponse)
async def detail(source: str, request: MonitorDetailRequest) -> MonitorDetailResponse:
    """Fetch the detail page for one item (an item dict from /collect)."""
    if source not in SOURCE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown source: {source}")
    try:
        item = await get_scraper(source).detail(request.item)
    except AntibotBlockedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MonitorDetailResponse(source=source, item=item)
