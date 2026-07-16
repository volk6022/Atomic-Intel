"""Contract tests for the catalog API — in-process via ASGITransport, actions mocked."""

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from src.domain.models.catalog import FreelancerProfile, Gig

_HEADERS = {"X-API-Key": "default_internal_key"}


def _client() -> AsyncClient:
    from src.api.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_kwork_services_returns_200_and_shape():
    fake = {"gigs": [Gig(id=1, gtitle="ML gig", price=1500, parent="script-programming", leaf="mashinnoe-obuchenie")], "cards": []}
    with patch("src.api.routers.catalog.KworkServicesAction.execute", new=AsyncMock(return_value=fake)):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/catalog/kwork-services", headers=_HEADERS,
                json={"parent": "script-programming", "leaf": "mashinnoe-obuchenie", "max_pages": 1},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert {"parent", "leaf", "total", "gigs", "cards"} <= data.keys()
    assert data["total"] == 1 and data["gigs"][0]["price"] == 1500


async def test_kwork_profiles_returns_200():
    fake = [{"userName": "seller1", "meta": {"profession": "ML"}, "gigs": [], "gig_count": 0}]
    with patch("src.api.routers.catalog.KworkProfilesAction.execute", new=AsyncMock(return_value=fake)):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/catalog/kwork-profiles", headers=_HEADERS,
                json={"usernames": ["seller1"], "with_gigs": False},
            )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_fl_freelancers_returns_200_and_shape():
    fake = {
        "freelancers": [FreelancerProfile(uid="9526847", is_pro=True, reviews=214, profession="neironnye-seti")],
        "rates": [{"login": "x", "hourly_rate": 2000}],
        "meta": {"scraped": 1, "hourly_median": 2000},
    }
    with patch("src.api.routers.catalog.FLFreelancersAction.execute", new=AsyncMock(return_value=fake)):
        async with _client() as client:
            resp = await client.post(
                "/api/v1/catalog/fl-freelancers", headers=_HEADERS,
                json={"profession": "neironnye-seti", "max_pages": 1},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert {"profession", "total", "freelancers", "rates", "meta"} <= data.keys()
    assert data["total"] == 1 and data["freelancers"][0]["uid"] == "9526847"


async def test_missing_api_key_returns_403():
    async with _client() as client:
        resp = await client.post(
            "/api/v1/catalog/kwork-services",
            json={"parent": "script-programming", "leaf": "", "max_pages": 1},
        )
    assert resp.status_code == 403
