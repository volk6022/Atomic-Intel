from fastapi import APIRouter, Depends, HTTPException
from src.domain.models.requests import EnrichRequest, EnrichResponse
from src.actions.site_enricher import SiteEnrichAction
from src.api.auth import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])


@router.post("/enrich", response_model=EnrichResponse)
async def enrich_website(request: EnrichRequest):
    """
    Extract clean text content from a company website.

    Optionally crawls about/services pages for additional content.
    Content is truncated to approximately 500 words.
    """
    try:
        action = SiteEnrichAction()

        enriched = await action.execute(
            url=str(request.url),
            crawl_about=request.crawl_about,
            crawl_services=request.crawl_services,
        )

        return EnrichResponse(
            url=enriched.url,
            text=enriched.text,
            word_count=enriched.word_count,
            truncated=enriched.truncated,
            pages_crawled=enriched.pages_crawled,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
