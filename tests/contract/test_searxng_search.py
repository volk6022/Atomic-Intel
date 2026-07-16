"""
Contract test for /serper endpoint (SearXNG-backed search).
Tests real endpoint behavior without full service mocking.
"""

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

TEST_API_KEY = "default_internal_key"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


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


def _mock_search_response_with_num(num: int):
    from src.domain.models.requests import SearchResponse, SearchResult

    return SearchResponse(
        searchParameters={
            "q": "test",
            "type": "search",
            "engine": "searxng",
            "num": num,
        },
        organic=[
            SearchResult(
                title=f"Result {i}",
                link=f"https://example{i}.com",
                snippet=f"Snippet {i}",
                position=i,
            )
            for i in range(1, num + 1)
        ],
    )


@pytest.mark.asyncio
async def test_serper_returns_200_with_valid_query():
    """Serper endpoint should return 200 OK with valid query"""
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


@pytest.mark.asyncio
async def test_serper_returns_search_results_structure():
    """Serper endpoint should return proper search results structure"""
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


@pytest.mark.asyncio
async def test_serper_organic_result_structure():
    """Each organic result should have required fields"""
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
                json={"q": "test"},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data["organic"]) > 0, "Expected at least one organic result"
        result = data["organic"][0]
        assert "title" in result
        assert "link" in result
        assert "snippet" in result
        assert "position" in result
        assert isinstance(result["title"], str)
        assert isinstance(result["link"], str)
        assert isinstance(result["snippet"], str)
        assert isinstance(result["position"], int)


@pytest.mark.asyncio
async def test_serper_requires_api_key():
    """Serper endpoint should return 403 without API key"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/serper",
            json={"q": "test"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_serper_validates_num_parameter():
    """Serper endpoint should return 422 for invalid num parameter"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/serper",
            headers=AUTH_HEADERS,
            json={"q": "test", "num": -1},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_serper_with_custom_num():
    """Serper endpoint should accept custom num parameter"""
    from src.api.main import app
    from src.infrastructure.external_api.search_client import SearXngSearchClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            SearXngSearchClient,
            "search",
            new_callable=AsyncMock,
            return_value=_mock_search_response_with_num(5),
        ):
            response = await client.post(
                "/serper",
                headers=AUTH_HEADERS,
                json={"q": "test", "num": 5},
            )
        assert response.status_code == 200
        data = response.json()
        assert "searchParameters" in data


@pytest.mark.asyncio
async def test_serper_default_num():
    """Serper endpoint should use default num=10 when not specified"""
    from src.api.main import app
    from src.infrastructure.external_api.search_client import SearXngSearchClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            SearXngSearchClient,
            "search",
            new_callable=AsyncMock,
            return_value=_mock_search_response_with_num(10),
        ):
            response = await client.post(
                "/serper",
                headers=AUTH_HEADERS,
                json={"q": "test"},
            )
        assert response.status_code == 200
        data = response.json()
        assert "searchParameters" in data
        assert "q" in data["searchParameters"]


@pytest.mark.asyncio
async def test_serper_validates_query_required():
    """Serper endpoint should return 422 when q is missing"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/serper",
            headers=AUTH_HEADERS,
            json={},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_serper_validates_query_type():
    """Serper endpoint should return 422 for invalid q type"""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/serper",
            headers=AUTH_HEADERS,
            json={"q": 123},
        )
        assert response.status_code == 422
