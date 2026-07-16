from fastapi import APIRouter, Depends
from src.domain.models.requests import (
    ScrapeRequest,
    ScrapeResponse,
    SearchRequest,
    SearchResponse,
    OmniParseRequest,
    HtmlToMdRequest,
    TaskStatus,
)
from src.domain.utils.content_cleaner import (
    clean_html_content,
    html_to_text,
    html_to_markdown,
)
from src.infrastructure.browser.pool_manager import pool_manager
from src.infrastructure.external_api.search_client import search_client
from src.infrastructure.external_api.facade import get_orchestration_client
from src.api.auth import get_api_key

router = APIRouter(dependencies=[Depends(get_api_key)])
orchestration_client = get_orchestration_client()


@router.post("/scraper", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest):
    try:
        context = await pool_manager.create_context(proxy=request.proxy, headless=True)
        page = await context.new_page()
        await page.goto(str(request.url), wait_until=request.wait_until)  # type: ignore
        content = await page.content()
        await context.close()

        if request.output_format == "markdown":
            content = html_to_markdown(content)
        elif request.output_format == "text":
            content = html_to_text(content)
        elif request.clean_html:
            content = clean_html_content(content)

        return ScrapeResponse(
            url=str(request.url), content=content, status=TaskStatus.SUCCESS
        )
    except Exception as e:
        return ScrapeResponse(
            url=str(request.url), status=TaskStatus.FAILED, error=str(e)
        )


@router.post("/serper", response_model=SearchResponse)
async def serper(request: SearchRequest):
    return await search_client.search(request)


@router.post("/omni-parse")
async def omni_parse(request: OmniParseRequest):
    # Use orchestration client for UI grounding tasks
    result = await orchestration_client.generate(
        prompt=f"Analyze this image (base64) for elements: {request.prompt or 'Find all interactive elements'}"
    )
    return {"raw_analysis": result}


@router.post("/html-to-md")
async def html_to_md(request: HtmlToMdRequest):
    if request.format == "markdown":
        content = html_to_markdown(request.html)
    else:
        content = html_to_text(request.html)
    return {"content": content}
