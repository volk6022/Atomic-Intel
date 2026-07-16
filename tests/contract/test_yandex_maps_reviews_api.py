"""Contract tests for POST /api/v1/yandex-maps/reviews.

The action layer is mocked — these tests verify request/response shape and
validation at the HTTP boundary.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

TEST_API_KEY = "default_internal_key"
AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


def _mock_reviews():
    from src.domain.models.yandex_review import YandexReview, YandexReviewAuthor

    return [
        YandexReview(
            review_id="Y2uI6pYCxMQ4m4uKsxEHRjPGRfPTYvsqZ",
            business_id="82071161567",
            rating=5,
            text="отличная клиника",
            author=YandexReviewAuthor(name="Анастасия Б.", public_id="abc"),
        )
    ]


VALID_PAYLOAD = {
    "business_oid": "82071161567",
    "seoname": "dental_konfidens",
    "count": 50,
}


@pytest.mark.asyncio
async def test_reviews_returns_200_for_valid_payload():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsReviewsAction.execute",
            new_callable=AsyncMock,
            return_value=_mock_reviews(),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/reviews",
                headers=AUTH_HEADERS,
                json=VALID_PAYLOAD,
            )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_reviews_response_shape():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsReviewsAction.execute",
            new_callable=AsyncMock,
            return_value=_mock_reviews(),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/reviews",
                headers=AUTH_HEADERS,
                json=VALID_PAYLOAD,
            )
    data = response.json()
    assert {"reviews", "total", "business_oid"} <= data.keys()
    assert isinstance(data["reviews"], list)
    assert data["total"] == len(data["reviews"])
    assert data["business_oid"] == "82071161567"
    r = data["reviews"][0]
    # alias serialization → camelCase field names
    assert r["reviewId"] == "Y2uI6pYCxMQ4m4uKsxEHRjPGRfPTYvsqZ"
    assert r["rating"] == 5
    assert r["text"] == "отличная клиника"


@pytest.mark.asyncio
async def test_reviews_uses_defaults():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsReviewsAction.execute",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock:
            response = await client.post(
                "/api/v1/yandex-maps/reviews",
                headers=AUTH_HEADERS,
                json={"business_oid": "82071161567", "seoname": "dental_konfidens"},
            )
    assert response.status_code == 200
    assert mock.call_args.kwargs["count"] == 50
    assert mock.call_args.kwargs["ranking"] == "by_time"
    assert mock.call_args.kwargs["pages"] == 1


@pytest.mark.asyncio
async def test_reviews_missing_oid_returns_422():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/reviews",
            headers=AUTH_HEADERS,
            json={"seoname": "x"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reviews_oid_not_digits_returns_422():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/reviews",
            headers=AUTH_HEADERS,
            json={"business_oid": "not-a-number", "seoname": "x"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reviews_invalid_ranking_returns_422():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/reviews",
            headers=AUTH_HEADERS,
            json={
                "business_oid": "82071161567",
                "seoname": "x",
                "ranking": "by_random",
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reviews_count_too_high_returns_422():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/reviews",
            headers=AUTH_HEADERS,
            json={"business_oid": "1", "seoname": "x", "count": 999},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reviews_requires_api_key():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/yandex-maps/reviews",
            json=VALID_PAYLOAD,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reviews_captcha_returns_503():
    from src.actions.yandex_maps import YandexCaptchaError
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsReviewsAction.execute",
            new_callable=AsyncMock,
            side_effect=YandexCaptchaError("captcha on reviews"),
        ):
            response = await client.post(
                "/api/v1/yandex-maps/reviews",
                headers=AUTH_HEADERS,
                json=VALID_PAYLOAD,
            )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_reviews_action_called_with_request_parameters():
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.yandex_maps.YandexMapsReviewsAction.execute",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock:
            await client.post(
                "/api/v1/yandex-maps/reviews",
                headers=AUTH_HEADERS,
                json={
                    "business_oid": "82071161567",
                    "seoname": "dental_konfidens",
                    "count": 50,
                    "ranking": "by_rating",
                    "pages": 2,
                    "include_raw": False,
                },
            )
    kwargs = mock.call_args.kwargs
    assert kwargs["business_oid"] == "82071161567"
    assert kwargs["seoname"] == "dental_konfidens"
    assert kwargs["count"] == 50
    assert kwargs["ranking"] == "by_rating"
    assert kwargs["pages"] == 2
    assert kwargs["include_raw"] is False
