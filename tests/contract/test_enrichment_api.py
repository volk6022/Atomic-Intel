"""
Contract test for enrichment API endpoint.

Tests real endpoint behavior via ASGITransport, mocking only the browser layer.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

TEST_API_KEY = "default_internal_key"


def create_mock_browser_context():
    mock_context = MagicMock()
    mock_context.new_page = AsyncMock()
    mock_context.close = AsyncMock()

    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(
        return_value="<html><body><main><p>Test content with words here.</p></main></body></html>"
    )
    mock_page.query_selector_all = AsyncMock(return_value=[])
    mock_page.locator = MagicMock(
        return_value=MagicMock(
            first=MagicMock(
                text_content=AsyncMock(return_value="Test"),
                count=AsyncMock(return_value=1),
                get_attribute=AsyncMock(return_value="https://example.com"),
            )
        )
    )

    mock_context.new_page = AsyncMock(return_value=mock_page)
    return mock_context


@pytest.mark.asyncio
async def test_enrichment_endpoint_returns_200():
    """Enrichment endpoint should return 200 OK with valid request"""
    from src.api.main import app

    mock_context = create_mock_browser_context()

    with patch(
        "src.infrastructure.browser.pool_manager.BrowserPoolManager.create_context",
        return_value=mock_context,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/enrich",
                    json={
                        "url": "https://example.com",
                    },
                    headers={"X-API-Key": TEST_API_KEY},
                )
                assert response.status_code == 200


@pytest.mark.asyncio
async def test_enrichment_response_format():
    """Enrichment should return proper response format with all required fields"""
    from src.api.main import app

    mock_context = create_mock_browser_context()

    with patch(
        "src.infrastructure.browser.pool_manager.BrowserPoolManager.create_context",
        return_value=mock_context,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/enrich",
                    json={
                        "url": "https://example.com",
                    },
                    headers={"X-API-Key": TEST_API_KEY},
                )
                assert response.status_code == 200
                data = response.json()
                assert "url" in data
                assert "text" in data
                assert "word_count" in data
                assert "truncated" in data
                assert "example.com" in data["url"]
                assert isinstance(data["word_count"], int)
                assert isinstance(data["truncated"], bool)


@pytest.mark.asyncio
async def test_enrichment_text_is_clean():
    """Enrichment text should be clean (not raw HTML)"""
    from src.api.main import app

    mock_context = create_mock_browser_context()

    with patch(
        "src.infrastructure.browser.pool_manager.BrowserPoolManager.create_context",
        return_value=mock_context,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/enrich",
                    json={
                        "url": "https://example.com",
                    },
                    headers={"X-API-Key": TEST_API_KEY},
                )
                assert response.status_code == 200
                data = response.json()
                text = data["text"]
                assert "<html" not in text.lower()
                assert "<div" not in text.lower()
                assert "<p>" not in text.lower()


@pytest.mark.asyncio
async def test_enrichment_word_limit():
    """Enrichment should respect word limit (≤500 words)"""
    from src.api.main import app

    mock_context = create_mock_browser_context()
    long_html = f"<html><body><main><p>{'word ' * 300}</p></main></body></html>"
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value=long_html)
    mock_page.query_selector_all = AsyncMock(return_value=[])
    mock_page.locator = MagicMock(
        return_value=MagicMock(
            first=MagicMock(
                text_content=AsyncMock(return_value=""), count=AsyncMock(return_value=0)
            )
        )
    )
    mock_context.new_page = AsyncMock(return_value=mock_page)

    with patch(
        "src.infrastructure.browser.pool_manager.BrowserPoolManager.create_context",
        return_value=mock_context,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/enrich",
                    json={
                        "url": "https://example.com",
                    },
                    headers={"X-API-Key": TEST_API_KEY},
                )
                assert response.status_code == 200
                data = response.json()
                word_count = data["word_count"]
                assert word_count <= 510


@pytest.mark.asyncio
async def test_enrichment_missing_url():
    """Missing URL should return 422 validation error"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/enrich",
            json={},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_enrichment_invalid_url():
    """Invalid URL should return 422 validation error"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/enrich",
            json={
                "url": "not-a-valid-url",
            },
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_enrichment_with_crawl_options():
    """Enrichment should support crawl options for about/services pages"""
    from src.api.main import app

    mock_context = create_mock_browser_context()

    with patch(
        "src.infrastructure.browser.pool_manager.BrowserPoolManager.create_context",
        return_value=mock_context,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/enrich",
                    json={
                        "url": "https://example.com",
                        "crawl_about": True,
                        "crawl_services": True,
                    },
                    headers={"X-API-Key": TEST_API_KEY},
                )
                assert response.status_code == 200
                data = response.json()
                assert "pages_crawled" in data


@pytest.mark.asyncio
async def test_enrichment_truncated_flag():
    """Enrichment should set truncated flag when content exceeds limit"""
    from src.api.main import app

    mock_context = create_mock_browser_context()
    long_html = f"<html><body><main><p>{'longword ' * 600}</p></main></body></html>"
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value=long_html)
    mock_page.query_selector_all = AsyncMock(return_value=[])
    mock_page.locator = MagicMock(
        return_value=MagicMock(
            first=MagicMock(
                text_content=AsyncMock(return_value=""), count=AsyncMock(return_value=0)
            )
        )
    )
    mock_context.new_page = AsyncMock(return_value=mock_page)

    with patch(
        "src.infrastructure.browser.pool_manager.BrowserPoolManager.create_context",
        return_value=mock_context,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/enrich",
                    json={
                        "url": "https://example.com",
                    },
                    headers={"X-API-Key": TEST_API_KEY},
                )
                assert response.status_code == 200
                data = response.json()
                assert isinstance(data["truncated"], bool)


@pytest.mark.asyncio
async def test_enrichment_requires_auth():
    """Enrichment should require API key"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/enrich",
            json={
                "url": "https://example.com",
            },
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_enrichment_handles_browser_error():
    """Enrichment should return 500 when browser fails"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.BrowserPoolManager.create_context",
        side_effect=Exception("Browser unavailable"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/enrich",
                json={
                    "url": "https://example.com",
                },
                headers={"X-API-Key": TEST_API_KEY},
            )
            assert response.status_code == 500
