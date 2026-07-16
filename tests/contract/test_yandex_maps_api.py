"""Contract tests for POST /api/v1/yandex-maps/extract.

The action layer (Playwright + XHR intercept) is mocked — these tests verify
the request/response shape and validation rules at the HTTP boundary.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

TEST_API_KEY = "default_internal_key"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


def _mock_orgs():
    from src.domain.models.yandex_organization import (
        YandexCoordinates,
        YandexOrganization,
        YandexPhone,
    )

    return [
        YandexOrganization(
            oid="82071161567",
            seoname="dental_konfidens",
            title="Дэнтал Конфидэнс",
            address="Бармалеева ул., 12",
            coordinates=YandexCoordinates(lat=59.964324, lon=30.3056),
            phones=[YandexPhone(number="+7 (812) 218-28-10", value="+78122182810")],
        )
    ]


VALID_PAYLOAD = {
    "query": "стоматология",
    "region_id": 2,
    "city_slug": "saint-petersburg",
    "target_count": 20,
}


@pytest.mark.asyncio
async def test_extract_returns_200_for_valid_payload():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsExtractAction.execute",
            new_callable=AsyncMock,
            return_value=_mock_orgs(),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json=VALID_PAYLOAD,
            )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_extract_response_shape():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsExtractAction.execute",
            new_callable=AsyncMock,
            return_value=_mock_orgs(),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json=VALID_PAYLOAD,
            )
    assert response.status_code == 200
    data = response.json()
    assert {"organizations", "total", "query", "region_id"} <= data.keys()
    assert isinstance(data["organizations"], list)
    assert isinstance(data["total"], int)
    assert data["total"] == len(data["organizations"])
    assert data["query"] == "стоматология"
    assert data["region_id"] == 2


@pytest.mark.asyncio
async def test_extract_organization_fields_present():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsExtractAction.execute",
            new_callable=AsyncMock,
            return_value=_mock_orgs(),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json=VALID_PAYLOAD,
            )
    org = response.json()["organizations"][0]
    assert org["oid"] == "82071161567"
    assert org["seoname"] == "dental_konfidens"
    assert org["title"] == "Дэнтал Конфидэнс"
    assert org["coordinates"]["lat"] == pytest.approx(59.964324)
    assert org["coordinates"]["lon"] == pytest.approx(30.3056)
    assert org["phones"][0]["number"] == "+7 (812) 218-28-10"
    assert org["phones"][0]["value"] == "+78122182810"


@pytest.mark.asyncio
async def test_extract_empty_results():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsExtractAction.execute",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json=VALID_PAYLOAD,
            )
    assert response.status_code == 200
    data = response.json()
    assert data["organizations"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_extract_uses_defaults_when_only_query_given():
    """Only `query` is required — region/city/target have defaults."""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsExtractAction.execute",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock:
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json={"query": "пиццерия"},
            )
    assert response.status_code == 200
    assert mock.call_args.kwargs["region_id"] == 2
    assert mock.call_args.kwargs["city_slug"] == "saint-petersburg"
    assert mock.call_args.kwargs["target_count"] == 40


@pytest.mark.asyncio
async def test_extract_missing_query_returns_422():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/extract",
            headers=AUTH_HEADERS,
            json={"region_id": 2},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_extract_empty_query_returns_422():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/extract",
            headers=AUTH_HEADERS,
            json={"query": "", "region_id": 2},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_extract_target_count_too_high_returns_422():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/extract",
            headers=AUTH_HEADERS,
            json={"query": "x", "target_count": 999},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_extract_region_id_below_1_returns_422():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/extract",
            headers=AUTH_HEADERS,
            json={"query": "x", "region_id": 0},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_extract_requires_api_key():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/extract",
            json=VALID_PAYLOAD,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_extract_action_called_with_request_parameters():
    """The router must forward all request fields to the action."""
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsExtractAction.execute",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock:
            await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json={
                    "query": "стоматология",
                    "region_id": 213,
                    "city_slug": "moscow",
                    "target_count": 100,
                    "include_raw": False,
                },
            )
    mock.assert_awaited_once()
    kwargs = mock.call_args.kwargs
    assert kwargs["query"] == "стоматология"
    assert kwargs["region_id"] == 213
    assert kwargs["city_slug"] == "moscow"
    assert kwargs["target_count"] == 100
    assert kwargs["include_raw"] is False


@pytest.mark.asyncio
async def test_extract_captcha_returns_503():
    from src.actions.yandex_maps import YandexCaptchaError
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsExtractAction.execute",
            new_callable=AsyncMock,
            side_effect=YandexCaptchaError("smartcaptcha on load"),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/extract",
                headers=AUTH_HEADERS,
                json=VALID_PAYLOAD,
            )
    assert response.status_code == 503
    assert "captcha" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_extract_handles_various_queries():
    from src.api.main import app

    queries = ["стоматология", "restaurants", "АТМ", "кафе с террасой"]

    for q in queries:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch(
                "src.actions.yandex_maps.YandexMapsExtractAction.execute",
                new_callable=AsyncMock,
                return_value=[],
            ):
                response = await client.post(
                    "/api/v1/yandex-maps/extract",
                    headers=AUTH_HEADERS,
                    json={"query": q, "region_id": 2},
                )
        assert response.status_code == 200, f"failed for query={q!r}"
