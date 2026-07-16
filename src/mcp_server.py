# /// script
# dependencies = [
#   "fastmcp",
#   "httpx",
#   "pydantic",
# ]
# ///

import json
import httpx
from typing import Optional, Dict, Any
from fastmcp import FastMCP

# Configuration
BASE_URL = "http://localhost:8000"
API_KEY = "your_internal_key"
HEADERS = {"X-API-Key": API_KEY}

mcp = FastMCP("Atomic Scraper Service")


async def send_command(session_id: str, command: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a DSL command to an active session via the REST command endpoint.

    Uses POST /sessions/{session_id}/command instead of a WebSocket connection.
    This works correctly with MCP over stdio because every call is an independent
    HTTP request-response cycle with no persistent connection required.
    """
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{BASE_URL}/sessions/{session_id}/command",
            headers=HEADERS,
            json=command,
        )
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def scrape(
    url: str, proxy: Optional[str] = None, wait_until: str = "domcontentloaded"
) -> str:
    """
    Scrape full HTML content of a URL (Stateless).
    :param url: The URL to scrape.
    :param proxy: Optional proxy URL.
    :param wait_until: Playwright wait condition (domcontentloaded, load, networkidle).
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{BASE_URL}/scraper",
            headers=HEADERS,
            json={"url": url, "proxy": proxy, "wait_until": wait_until},
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def search(q: str, num: int = 10) -> str:
    """
    Perform a Google search (Stateless).
    :param q: Search query.
    :param num: Number of results to return.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{BASE_URL}/serper",
            headers=HEADERS,
            json={"q": q, "num": num},
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def omni_parse(base64_image: str, prompt: Optional[str] = None) -> str:
    """
    Stateless AI element analysis (Omni-Parser).
    :param base64_image: Base64 encoded image to analyze.
    :param prompt: Analysis prompt.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{BASE_URL}/omni-parse",
            headers=HEADERS,
            json={"base64_image": base64_image, "prompt": prompt},
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def jina_extract(
    html: str, extraction_schema: Optional[Dict[str, Any]] = None
) -> str:
    """
    Stateless AI structured extraction (Jina Reader LM).
    :param html: HTML content to extract from.
    :param extraction_schema: Optional extraction schema.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{BASE_URL}/jina-extract",
            headers=HEADERS,
            json={"html": html, "extraction_schema": extraction_schema},
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def create_session() -> str:
    """
    Initialize a persistent browser session. Returns a session_id.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{BASE_URL}/sessions", headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        return f"Session created: {data.get('session_id')}"


@mcp.tool()
async def delete_session(session_id: str) -> str:
    """
    Terminate a persistent browser session.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(f"{BASE_URL}/sessions/{session_id}", headers=HEADERS)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def session_goto(session_id: str, url: str) -> str:
    """Navigate an active session to a URL."""
    result = await send_command(session_id, {"type": "goto", "params": {"url": url}})
    return json.dumps(result, indent=2)


@mcp.tool()
async def session_scroll(
    session_id: str, direction: str = "down", amount: int = 400
) -> str:
    """Scroll the page in an active session."""
    result = await send_command(
        session_id,
        {"type": "scroll", "params": {"direction": direction, "amount": amount}},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def session_click(session_id: str, x: float, y: float) -> str:
    """Click at relative coordinates (0.0 to 1.0) in an active session."""
    result = await send_command(
        session_id, {"type": "click_coord", "params": {"x": x, "y": y}}
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def session_type(session_id: str, selector: str, text: str) -> str:
    """Type text into a CSS selector in an active session."""
    result = await send_command(
        session_id, {"type": "type", "params": {"selector": selector, "text": text}}
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def session_screenshot(session_id: str) -> str:
    """Capture a base64 screenshot of the active session's viewport."""
    result = await send_command(session_id, {"type": "screenshot", "params": {}})
    return json.dumps(result, indent=2)


@mcp.tool()
async def session_click_omni(session_id: str, element_description: str) -> str:
    """AI-enhanced click based on element description."""
    result = await send_command(
        session_id,
        {"type": "click_omni", "params": {"element_description": element_description}},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def session_extract_jina(
    session_id: str, extraction_schema: Dict[str, Any]
) -> str:
    """AI-enhanced data extraction using a schema."""
    result = await send_command(
        session_id,
        {"type": "extract_jina", "params": {"extraction_schema": extraction_schema}},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def yandex_maps_extract(
    category: str, lat: float, lng: float, radius: int = 1000
) -> str:
    """
    Extract business data from Yandex Maps.
    :param category: Business category (e.g., "restaurants", "cafes", "hotels").
    :param lat: Latitude of search center (-90 to 90).
    :param lng: Longitude of search center (-180 to 180).
    :param radius: Search radius in meters (100-5000).
    """
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/yandex-maps/extract",
            headers=HEADERS,
            json={
                "category": category,
                "center": {"lat": lat, "lng": lng},
                "radius": radius,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def enrich_website(
    url: str, crawl_about: bool = False, crawl_services: bool = False
) -> str:
    """
    Extract clean text content from a company website.
    :param url: The URL of the website to enrich.
    :param crawl_about: Whether to crawl the /about page for additional content.
    :param crawl_services: Whether to crawl the /services page for additional content.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/enrich",
            headers=HEADERS,
            json={
                "url": url,
                "crawl_about": crawl_about,
                "crawl_services": crawl_services,
            },
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def research_run(query: str, mode: str = "balanced") -> str:
    """
    Start a research task using the AI agent.
    :param query: Research question or topic.
    :param mode: Research mode - "speed" (fast), "balanced" (default), "quality" (deep).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{BASE_URL}/api/v1/research/run",
            headers=HEADERS,
            json={"query": query, "mode": mode},
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def research_status(task_id: str) -> str:
    """
    Get the status of a research task.
    :param task_id: The task ID returned from research_run.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{BASE_URL}/api/v1/research/status/{task_id}",
            headers=HEADERS,
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)


@mcp.tool()
async def research_stream(task_id: str) -> str:
    """
    Stream progress events from a research task (SSE).
    :param task_id: The task ID returned from research_run.
    """
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(
            f"{BASE_URL}/api/v1/research/stream/{task_id}",
            headers=HEADERS,
        )
        resp.raise_for_status()
        return resp.text


if __name__ == "__main__":
    mcp.run()
