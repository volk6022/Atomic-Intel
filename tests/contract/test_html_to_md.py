"""
Contract test for /html-to-md endpoint.
T010: Contract test for /html-to-md endpoint.

Tests the endpoint that converts HTML to Markdown using markdownify library.
"""

import pytest
from httpx import AsyncClient, ASGITransport

TEST_API_KEY = "default_internal_key"


@pytest.mark.asyncio
async def test_html_to_md_returns_200():
    """HTML to Markdown endpoint should return 200 OK"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            json={
                "html": "<html><body><h1>Title</h1><p>Paragraph text</p></body></html>",
                "format": "markdown",
            },
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_html_to_md_returns_markdown_content():
    """HTML to Markdown should return proper markdown content"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            json={
                "html": "<html><body><h1>Header</h1><p>Some text</p></body></html>",
                "format": "markdown",
            },
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert isinstance(data["content"], str)


@pytest.mark.asyncio
async def test_html_to_md_requires_api_key():
    """HTML to Markdown should require API key"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            json={"html": "<html><body>test</body></html>"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_html_to_md_validates_html_field():
    """HTML to Markdown should validate HTML field is required"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/html-to-md",
            json={"format": "markdown"},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert response.status_code == 422
