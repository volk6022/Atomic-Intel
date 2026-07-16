"""
Contract test for /scraper endpoint with new parameters.
Tests endpoint contract with minimal mocking.
"""

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

TEST_API_KEY = "default_internal_key"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


def _create_mock_context():
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(
        return_value="<html><body><h1>Test Page</h1><p>Test content here</p></body></html>"
    )
    mock_page.goto = AsyncMock()
    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()
    return mock_context


@pytest.mark.asyncio
async def test_scraper_returns_200_with_valid_url():
    """Scraper endpoint should return 200 OK with valid url"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_context(),
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
            assert "status" in data
            assert data["status"] == "success"
            assert "url" in data
            assert "content" in data


@pytest.mark.asyncio
async def test_scraper_returns_content_structure():
    """Scraper endpoint should return proper content structure"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_context(),
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
            assert "url" in data
            assert "content" in data
            assert "status" in data
            assert isinstance(data["url"], str)
            assert isinstance(data["content"], str)
            assert data["status"] in ("success", "failed")


@pytest.mark.asyncio
async def test_scraper_accepts_clean_html_param():
    """Scraper endpoint should accept clean_html parameter"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_context(),
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
async def test_scraper_accepts_output_format_param():
    """Scraper endpoint should accept output_format parameter"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_context(),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/scraper",
                headers=AUTH_HEADERS,
                json={
                    "url": "https://example.com",
                    "output_format": "markdown",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "url" in data


@pytest.mark.asyncio
async def test_scraper_validates_output_format_values():
    """Scraper endpoint should accept valid output_format values"""
    from src.api.main import app

    valid_values = ["html", "text", "markdown"]
    for val in valid_values:
        with patch(
            "src.infrastructure.browser.pool_manager.pool_manager.create_context",
            new_callable=AsyncMock,
            return_value=_create_mock_context(),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/scraper",
                    headers=AUTH_HEADERS,
                    json={
                        "url": "https://example.com",
                        "output_format": val,
                    },
                )
                assert response.status_code == 200, f"Failed for value: {val}"


@pytest.mark.asyncio
async def test_scraper_rejects_invalid_url():
    """Scraper endpoint should return 422 for invalid URL"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/scraper",
            headers=AUTH_HEADERS,
            json={
                "url": "not-a-valid-url",
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_scraper_accepts_both_new_params():
    """Scraper endpoint should accept both clean_html and output_format together"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_context(),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/scraper",
                headers=AUTH_HEADERS,
                json={
                    "url": "https://example.com",
                    "clean_html": True,
                    "output_format": "text",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"


@pytest.mark.asyncio
async def test_scraper_output_format_all_valid_values():
    """Scraper endpoint should accept all valid output_format values"""
    from src.api.main import app

    valid_formats = ["html", "text", "markdown"]

    for fmt in valid_formats:
        with patch(
            "src.infrastructure.browser.pool_manager.pool_manager.create_context",
            new_callable=AsyncMock,
            return_value=_create_mock_context(),
        ):
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
                assert response.status_code == 200, f"Failed for format: {fmt}"


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
async def test_scraper_rejects_missing_url():
    """Scraper endpoint should return 422 when url is missing"""
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
async def test_scraper_with_proxy_param():
    """Scraper endpoint should accept optional proxy parameter"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_context(),
    ) as mock_create:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/scraper",
                headers=AUTH_HEADERS,
                json={
                    "url": "https://example.com",
                    "proxy": "http://proxy.example.com:8080",
                },
            )
            assert response.status_code == 200
            mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_scraper_with_wait_until_param():
    """Scraper endpoint should accept wait_until parameter"""
    from src.api.main import app

    with patch(
        "src.infrastructure.browser.pool_manager.pool_manager.create_context",
        new_callable=AsyncMock,
        return_value=_create_mock_context(),
    ) as mock_create:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/scraper",
                headers=AUTH_HEADERS,
                json={
                    "url": "https://example.com",
                    "wait_until": "networkidle",
                },
            )
            assert response.status_code == 200
