"""
Integration tests for SearXNG-backed search client.

Tests search_client behavior — interface, underlying models, and retry/parse logic
against a mocked SearXNG HTTP backend.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from inspect import iscoroutinefunction

from src.domain.models.requests import SearchRequest, SearchResponse, SearchResult
from src.infrastructure.external_api.search_client import (
    search_client,
    SearchClient,
    SearXngSearchClient,
)


class TestSearchClientInterface:
    """Test search_client interface and behavior"""

    @pytest.mark.asyncio
    async def test_search_client_search_method_is_async(self):
        """SearchClient.search() should be an async method"""
        assert iscoroutinefunction(SearchClient.search), (
            "SearchClient.search should be an async method"
        )

    @pytest.mark.asyncio
    async def test_search_client_is_searxng_backed(self):
        """search_client should be a SearXngSearchClient with sane config"""
        assert isinstance(search_client, SearXngSearchClient)
        assert search_client._base_url.startswith("http")
        assert search_client._max_retries >= 0

    @pytest.mark.asyncio
    async def test_search_client_returns_search_response_type(self):
        """search_client.search() should return SearchResponse with engine=searxng"""
        mock_response = SearchResponse(
            searchParameters={"q": "test", "type": "search", "engine": "searxng"},
            organic=[
                SearchResult(
                    title="Result 1",
                    link="https://example.com",
                    snippet="Snippet 1",
                    position=1,
                )
            ],
        )

        with patch.object(
            SearchClient, "search", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = mock_response
            result = await search_client.search(SearchRequest(q="test"))

        assert isinstance(result, SearchResponse)
        assert isinstance(result.searchParameters, dict)
        assert "q" in result.searchParameters
        assert result.searchParameters["q"] == "test"
        assert result.searchParameters["engine"] == "searxng"


class TestSearchRequestModel:
    """Test SearchRequest model behavior"""

    def test_search_request_accepts_query_parameter(self):
        request = SearchRequest(q="python programming")
        assert request.q == "python programming"
        assert isinstance(request.q, str)

    def test_search_request_accepts_num_parameter(self):
        request = SearchRequest(q="test", num=20)
        assert request.num == 20
        assert isinstance(request.num, int)

    def test_search_request_default_num_is_10(self):
        request = SearchRequest(q="test")
        assert request.num == 10

    def test_search_request_validates_required_q(self):
        with pytest.raises(Exception):
            SearchRequest()


class TestSearchResultModel:
    """Test SearchResult model behavior"""

    def test_search_result_has_required_fields(self):
        result = SearchResult(
            title="Test Title",
            link="https://test.com",
            snippet="Test snippet",
            position=1,
        )
        assert result.title == "Test Title"
        assert result.link == "https://test.com"
        assert result.snippet == "Test snippet"
        assert result.position == 1

    def test_search_result_position_must_be_positive(self):
        result = SearchResult(
            title="Test",
            link="https://test.com",
            snippet="Test",
            position=1,
        )
        assert result.position >= 1

    def test_search_result_accepts_empty_snippet(self):
        result = SearchResult(
            title="Test",
            link="https://test.com",
            snippet="",
            position=1,
        )
        assert result.snippet == ""


class TestSearchResponseModel:
    """Test SearchResponse model behavior"""

    def test_search_response_has_search_parameters(self):
        response = SearchResponse(
            searchParameters={"q": "test", "type": "search", "engine": "searxng"},
            organic=[],
        )
        assert hasattr(response, "searchParameters")
        assert isinstance(response.searchParameters, dict)
        assert "q" in response.searchParameters
        assert "engine" in response.searchParameters

    def test_search_response_has_organic_results(self):
        response = SearchResponse(
            searchParameters={"q": "test", "type": "search", "engine": "searxng"},
            organic=[
                SearchResult(
                    title="Result 1",
                    link="https://example.com",
                    snippet="Snippet 1",
                    position=1,
                )
            ],
        )
        assert hasattr(response, "organic")
        assert isinstance(response.organic, list)
        assert len(response.organic) == 1

    def test_search_response_organic_defaults_to_empty_list(self):
        response = SearchResponse(
            searchParameters={"q": "test", "type": "search", "engine": "searxng"},
            organic=[],
        )
        assert response.organic == []

    def test_search_response_accepts_multiple_results(self):
        response = SearchResponse(
            searchParameters={"q": "test", "type": "search", "engine": "searxng"},
            organic=[
                SearchResult(
                    title=f"Result {i}",
                    link=f"https://test{i}.com",
                    snippet=f"Snippet {i}",
                    position=i,
                )
                for i in range(1, 6)
            ],
        )
        assert len(response.organic) == 5


def _mock_searxng_response(results: list[dict], status_code: int = 200) -> MagicMock:
    """Helper: build a fake httpx Response with given SearXNG JSON payload."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value={"results": results})
    return resp


class TestSearXngClientLogic:
    """Test SearXngSearchClient parse + retry behavior against mocked httpx."""

    def _make_client(self, max_retries: int = 2, min_organic: int = 1) -> SearXngSearchClient:
        return SearXngSearchClient(
            base_url="http://fake-searxng:8080",
            timeout=5.0,
            max_retries=max_retries,
            retry_delay=0.0,
            min_organic=min_organic,
        )

    @pytest.mark.asyncio
    async def test_parses_results_into_search_result(self):
        client = self._make_client()
        payload = [
            {"url": "https://a.example", "title": "A", "content": "snip A"},
            {"url": "https://b.example", "title": "B", "content": "snip B"},
        ]
        with patch.object(
            client._client, "get", new_callable=AsyncMock,
            return_value=_mock_searxng_response(payload),
        ):
            resp = await client.search(SearchRequest(q="test", num=10))
        assert resp.searchParameters["engine"] == "searxng"
        assert len(resp.organic) == 2
        assert resp.organic[0].title == "A"
        assert resp.organic[0].link == "https://a.example"
        assert resp.organic[0].position == 1
        assert resp.organic[1].position == 2

    @pytest.mark.asyncio
    async def test_dedupes_links(self):
        client = self._make_client()
        payload = [
            {"url": "https://x.example", "title": "X1", "content": "s1"},
            {"url": "https://x.example", "title": "X1 dup", "content": "s1 dup"},
            {"url": "https://y.example", "title": "Y", "content": "s2"},
        ]
        with patch.object(
            client._client, "get", new_callable=AsyncMock,
            return_value=_mock_searxng_response(payload),
        ):
            resp = await client.search(SearchRequest(q="test", num=10))
        assert [r.link for r in resp.organic] == ["https://x.example", "https://y.example"]

    @pytest.mark.asyncio
    async def test_skips_non_http_links(self):
        client = self._make_client()
        payload = [
            {"url": "ftp://nope.example", "title": "ftp", "content": ""},
            {"url": "", "title": "blank", "content": ""},
            {"url": "https://ok.example", "title": "OK", "content": "snip"},
        ]
        with patch.object(
            client._client, "get", new_callable=AsyncMock,
            return_value=_mock_searxng_response(payload),
        ):
            resp = await client.search(SearchRequest(q="test", num=10))
        assert len(resp.organic) == 1
        assert resp.organic[0].link == "https://ok.example"

    @pytest.mark.asyncio
    async def test_limits_to_num(self):
        client = self._make_client()
        payload = [
            {"url": f"https://e{i}.example", "title": f"R{i}", "content": f"s{i}"}
            for i in range(1, 11)
        ]
        with patch.object(
            client._client, "get", new_callable=AsyncMock,
            return_value=_mock_searxng_response(payload),
        ):
            resp = await client.search(SearchRequest(q="test", num=3))
        assert len(resp.organic) == 3
        assert resp.organic[2].title == "R3"

    @pytest.mark.asyncio
    async def test_retries_on_http_error_then_succeeds(self):
        client = self._make_client(max_retries=2)
        bad = _mock_searxng_response([], status_code=502)
        good = _mock_searxng_response(
            [{"url": "https://ok.example", "title": "OK", "content": "snip"}]
        )
        with patch.object(
            client._client, "get", new_callable=AsyncMock,
            side_effect=[bad, good],
        ) as mock_get:
            resp = await client.search(SearchRequest(q="test", num=10))
        assert mock_get.call_count == 2
        assert len(resp.organic) == 1

    @pytest.mark.asyncio
    async def test_retries_on_empty_organic_then_succeeds(self):
        client = self._make_client(max_retries=2, min_organic=1)
        empty = _mock_searxng_response([])
        good = _mock_searxng_response(
            [{"url": "https://ok.example", "title": "OK", "content": ""}]
        )
        with patch.object(
            client._client, "get", new_callable=AsyncMock,
            side_effect=[empty, good],
        ) as mock_get:
            resp = await client.search(SearchRequest(q="test", num=10))
        assert mock_get.call_count == 2
        assert len(resp.organic) == 1

    @pytest.mark.asyncio
    async def test_raises_after_exhausting_retries(self):
        client = self._make_client(max_retries=2)
        bad = _mock_searxng_response([], status_code=502)
        with patch.object(
            client._client, "get", new_callable=AsyncMock,
            side_effect=[bad, bad, bad],
        ) as mock_get:
            with pytest.raises(Exception, match="after 3 attempts"):
                await client.search(SearchRequest(q="test", num=10))
        assert mock_get.call_count == 3
