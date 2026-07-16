"""
Contract test for stateless endpoints: /scraper, /serper, /html-to-md, /omni-parse.
Tests real endpoint behavior with minimal mocking.
"""

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

TEST_API_KEY = "default_internal_key"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


def _create_mock_browser_context():
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(
        return_value="<html><body><h1>Test Page</h1><p>Content here</p></body></html>"
    )
    mock_page.goto = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()
    return mock_context


def _mock_search_response():
    from src.domain.models.requests import SearchResponse, SearchResult

    return SearchResponse(
        searchParameters={"q": "test query", "type": "search", "engine": "searxng"},
        organic=[
            SearchResult(
                title="Test Result",
                link="https://example.com",
                snippet="Test snippet",
                position=1,
            )
        ],
    )


@pytest.mark.asyncio
async def test_scraper_returns_html():
    """Scraper endpoint should return HTML content by default"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_browser_context(),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/scraper",
                headers=AUTH_HEADERS,
                json={"url": "https://example.com"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "url" in data
            assert "content" in data
            assert isinstance(data["content"], str)


@pytest.mark.asyncio
async def test_scraper_with_clean_html():
    """Scraper endpoint should clean HTML when clean_html=True"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_browser_context(),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/scraper",
                headers=AUTH_HEADERS,
                json={
                    "url": "https://example.com",
                    "clean_html": True,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "content" in data


@pytest.mark.asyncio
async def test_scraper_with_output_format():
    """Scraper endpoint should respect output_format parameter"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_browser_context(),
    ):
        for fmt in ["html", "text", "markdown"]:
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/scraper",
                    headers=AUTH_HEADERS,
                    json={
                        "url": "https://example.com",
                        "output_format": fmt,
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "success"


@pytest.mark.asyncio
async def test_serper_returns_search_results():
    """Serper endpoint should return search results with mocked client"""
    from src.api.main import app
    from src.infrastructure.external_api.search_client import SearXngSearchClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            SearXngSearchClient,
            "search",
            new_callable=AsyncMock,
            return_value=_mock_search_response(),
        ):
            response = await client.post(
                "/serper",
                headers=AUTH_HEADERS,
                json={"q": "test query"},
            )
            assert response.status_code == 200
            data = response.json()
            assert "searchParameters" in data
            assert "organic" in data
            assert isinstance(data["organic"], list)
            assert len(data["organic"]) > 0
            assert data["organic"][0]["title"] == "Test Result"


@pytest.mark.asyncio
async def test_serper_requires_api_key():
    """Serper endpoint should require API key"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/serper",
            json={"q": "test"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_html_to_md_converts():
    """HTML to MD endpoint should convert HTML to markdown - NO MOCKS NEEDED"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            headers=AUTH_HEADERS,
            json={
                "html": "<html><body><h1>Title</h1><p>Paragraph</p></body></html>",
                "format": "markdown",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert isinstance(data["content"], str)
        assert "Title" in data["content"] or "# Title" in data["content"]


@pytest.mark.asyncio
async def test_html_to_md_text_format():
    """HTML to MD endpoint should convert to text format - NO MOCKS NEEDED"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            headers=AUTH_HEADERS,
            json={
                "html": "<html><body><h1>Header</h1><p>Text</p></body></html>",
                "format": "text",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert isinstance(data["content"], str)


@pytest.mark.asyncio
async def test_html_to_md_requires_api_key():
    """HTML to MD endpoint should require API key - REAL TEST"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            json={"html": "<html><body>test</body></html>"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_html_to_md_validates_html_required():
    """HTML to MD endpoint should validate html is required - REAL TEST"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            headers=AUTH_HEADERS,
            json={"format": "markdown"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_html_to_md_accepts_text_format():
    """HTML to MD endpoint should accept 'text' format - REAL TEST"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            headers=AUTH_HEADERS,
            json={"html": "<html><body><h1>Test</h1></body></html>", "format": "text"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert "Test" in data["content"]


@pytest.mark.asyncio
async def test_omni_parse_returns_analysis():
    """Omni-parse endpoint should return analysis with mocked LLM client"""
    from src.api.main import app
    from src.api.routers import stateless

    mock_response = "detected_button_at_100_200"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            stateless.orchestration_client,
            "generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.post(
                "/omni-parse",
                headers=AUTH_HEADERS,
                json={
                    "base64_image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    "prompt": "Find all interactive elements",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "raw_analysis" in data
            assert isinstance(data["raw_analysis"], str)


@pytest.mark.asyncio
async def test_omni_parse_requires_api_key():
    """Omni-parse endpoint should require API key - REAL TEST"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/omni-parse",
            json={"base64_image": "test"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_omni_parse_validates_base64():
    """Omni-parse endpoint should require base64_image field - REAL TEST"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/omni-parse",
            headers=AUTH_HEADERS,
            json={"prompt": "test"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_scraper_requires_api_key():
    """Scraper endpoint should require API key - REAL TEST"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/scraper",
            json={"url": "https://example.com"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_scraper_validates_url_required():
    """Scraper endpoint should validate url is required - REAL TEST"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/scraper",
            headers=AUTH_HEADERS,
            json={},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_scraper_validates_url_format():
    """Scraper endpoint should validate url format - REAL TEST"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/scraper",
            headers=AUTH_HEADERS,
            json={"url": "not-a-valid-url"},
        )
        assert response.status_code == 422
