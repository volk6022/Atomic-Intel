"""Integration tests for Yandex Maps actions.

These tests exercise:
  * domain model parsing from real upstream JSON shapes (fixtures);
  * the XHR-intercept logic in :class:`YandexMapsExtractAction` with a fake
    Playwright `page` that synchronously fires a `response` event;
  * the observation-and-replay logic in :class:`YandexMapsReviewsAction` with
    a fake `page.request.get(...)`.

Real network access is mocked away. The fixtures live in
`tests/fixtures/yandex_*.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SEARCH_FIXTURE = FIXTURES / "yandex_search_response.json"
REVIEWS_FIXTURE = FIXTURES / "yandex_fetch_reviews_response.json"


def _load_fixture(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# YandexOrganization model
# ---------------------------------------------------------------------------


class TestYandexOrganizationModel:
    def test_from_yandex_item_full_org(self):
        from src.domain.models.yandex_organization import YandexOrganization

        fixture = _load_fixture(SEARCH_FIXTURE)
        full = fixture["data"]["items"][0]  # Дэнтал Конфидэнс
        org = YandexOrganization.from_yandex_item(full)

        assert org.oid == "82071161567"
        assert org.seoname == "dental_konfidens"
        assert org.title == "Дэнтал Конфидэнс"
        assert org.address == "Бармалеева ул., 12"
        assert org.full_address == "Санкт-Петербург, Бармалеева улица, 12"
        assert org.country == "Россия"
        assert org.status == "open"

        assert org.coordinates is not None
        assert org.coordinates.lat == pytest.approx(59.964324)
        assert org.coordinates.lon == pytest.approx(30.3056)

        assert len(org.phones) == 2
        assert org.phones[0].number == "+7 (812) 218-28-10"
        assert org.phones[0].value == "+78122182810"
        assert org.phones[1].info == "Администратор"

        assert org.rating == 5.0
        assert org.rating_count == 338
        assert org.reviews_count == 292

        assert len(org.categories) == 1
        assert org.categories[0].name == "Стоматологическая клиника"
        assert org.categories[0].seoname == "dental_clinic"

        assert any(f.id == "for_children" and f.value is True for f in org.features)
        assert any(f.id == "payment_method" and isinstance(f.value, list) for f in org.features)

        assert len(org.metro) == 1
        assert org.metro[0].name == "Петроградская"

        assert len(org.photos) == 2
        assert org.photos[0].url_template.startswith("https://avatars.mds.yandex.net")

        # ИНН via advertiser block
        assert org.inn == "7801234567"

    def test_from_yandex_item_minimal_org(self):
        from src.domain.models.yandex_organization import YandexOrganization

        fixture = _load_fixture(SEARCH_FIXTURE)
        minimal = fixture["data"]["items"][1]  # Houston
        org = YandexOrganization.from_yandex_item(minimal)

        assert org.oid == "178860213454"
        assert org.title == "Houston"
        assert len(org.phones) == 1
        assert org.metro == []
        assert org.photos == []
        assert org.inn is None

    def test_from_yandex_item_raw_field_kept_by_default(self):
        from src.domain.models.yandex_organization import YandexOrganization

        item = _load_fixture(SEARCH_FIXTURE)["data"]["items"][0]
        org = YandexOrganization.from_yandex_item(item)
        assert org.raw is not None
        assert org.raw["id"] == "82071161567"

    def test_from_yandex_item_raw_field_omitted(self):
        from src.domain.models.yandex_organization import YandexOrganization

        item = _load_fixture(SEARCH_FIXTURE)["data"]["items"][0]
        org = YandexOrganization.from_yandex_item(item, keep_raw=False)
        assert org.raw is None

    def test_from_yandex_item_missing_id_raises(self):
        from src.domain.models.yandex_organization import YandexOrganization

        with pytest.raises(ValueError):
            YandexOrganization.from_yandex_item({"title": "x", "seoname": "y"})

    def test_serialization_uses_camel_case_aliases(self):
        from src.domain.models.yandex_organization import YandexOrganization

        item = _load_fixture(SEARCH_FIXTURE)["data"]["items"][0]
        org = YandexOrganization.from_yandex_item(item)
        dumped = org.model_dump(by_alias=True)
        assert "fullAddress" in dumped
        assert "ratingCount" in dumped


# ---------------------------------------------------------------------------
# YandexReview model
# ---------------------------------------------------------------------------


class TestYandexReviewModel:
    def test_from_yandex_item_with_business_comment_and_translations(self):
        from src.domain.models.yandex_review import YandexReview

        fixture = _load_fixture(REVIEWS_FIXTURE)
        review = YandexReview.from_yandex_item(fixture["data"]["reviews"][0])

        assert review.review_id == "Y2uI6pYCxMQ4m4uKsxEHRjPGRfPTYvsqZ"
        assert review.business_id == "82071161567"
        assert review.rating == 5
        assert review.text.startswith("обратилась")
        assert review.author is not None
        assert review.author.name == "Анастасия Б."
        assert review.author.profession_level == "Знаток города 5 уровня"
        assert review.business_comment is not None
        assert review.business_comment.text == "Спасибо за ваш отклик"
        assert "tr" in review.text_translations

    def test_from_yandex_item_with_photos(self):
        from src.domain.models.yandex_review import YandexReview

        fixture = _load_fixture(REVIEWS_FIXTURE)
        review = YandexReview.from_yandex_item(fixture["data"]["reviews"][1])

        assert len(review.photos) == 1
        assert review.photos[0].url_template.startswith("https://avatars.mds.yandex.net")

    def test_from_yandex_item_minimal(self):
        from src.domain.models.yandex_review import YandexReview

        fixture = _load_fixture(REVIEWS_FIXTURE)
        review = YandexReview.from_yandex_item(fixture["data"]["reviews"][2])

        assert review.review_id == "TjgxHThS3_rtPg4jqWWbrGB0rxHxrNd"
        assert review.rating == 4
        assert review.text is None
        assert review.author is None

    def test_from_yandex_item_missing_id_raises(self):
        from src.domain.models.yandex_review import YandexReview

        with pytest.raises(ValueError):
            YandexReview.from_yandex_item({"rating": 5})


# ---------------------------------------------------------------------------
# YandexMapsExtractAction — XHR intercept logic
# ---------------------------------------------------------------------------


def _make_response_mock(url: str, body: str, status: int = 200):
    resp = MagicMock()
    resp.url = url
    resp.status = status
    resp.text = AsyncMock(return_value=body)
    return resp


def _make_page_mock(captured_responses: list):
    """A `page` whose `on('response', cb)` fires `cb(resp)` for each preloaded resp.

    Captures async-callable methods so the action's loop pump works.
    """
    page = MagicMock()
    handlers: list = []

    def _on(event: str, cb):
        handlers.append((event, cb))

    page.on = _on

    async def _goto(*a, **kw):
        # Fire the responses on goto, just like a real browser would.
        for resp in captured_responses:
            for event, cb in handlers:
                if event == "response":
                    cb(resp)
        return MagicMock()

    page.goto = _goto
    page.content = AsyncMock(return_value="<html><body></body></html>")
    page.wait_for_selector = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock(return_value=99)
    return page


class TestYandexMapsExtractAction:
    @pytest.mark.asyncio
    async def test_extract_parses_xhr_responses_and_filters_non_businesses(self):
        from src.actions.yandex_maps import YandexMapsExtractAction

        fixture_body = SEARCH_FIXTURE.read_text(encoding="utf-8")
        responses = [
            _make_response_mock(
                "https://yandex.ru/maps/api/search?text=foo&ajax=1", fixture_body
            )
        ]
        page = _make_page_mock(responses)

        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        ctx.close = AsyncMock()

        action = YandexMapsExtractAction()
        action.scroll_limit = 1  # don't actually loop
        with patch.object(
            action.pool_manager, "create_context", new=AsyncMock(return_value=ctx)
        ), patch("src.actions.yandex_maps.proxy_provider") as proxy_mock, patch(
            "src.actions.yandex_maps.asyncio.sleep", new=AsyncMock()
        ):
            proxy_mock.get_proxy.return_value = None
            orgs = await action.execute(query="стоматология", target_count=3)

        oids = {o.oid for o in orgs}
        assert oids == {"82071161567", "178860213454"}, (
            "must keep both real businesses and filter out transit/metro entries"
        )

    @pytest.mark.asyncio
    async def test_extract_dedup_by_oid(self):
        from src.actions.yandex_maps import YandexMapsExtractAction

        fixture_body = SEARCH_FIXTURE.read_text(encoding="utf-8")
        # Same body delivered three times — dedup must collapse to 2 unique orgs.
        responses = [
            _make_response_mock(f"https://yandex.ru/maps/api/search?p={i}", fixture_body)
            for i in range(3)
        ]
        page = _make_page_mock(responses)

        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        ctx.close = AsyncMock()

        action = YandexMapsExtractAction()
        action.scroll_limit = 1
        with patch.object(
            action.pool_manager, "create_context", new=AsyncMock(return_value=ctx)
        ), patch("src.actions.yandex_maps.proxy_provider") as proxy_mock, patch(
            "src.actions.yandex_maps.asyncio.sleep", new=AsyncMock()
        ):
            proxy_mock.get_proxy.return_value = None
            orgs = await action.execute(query="x", target_count=10)

        assert len(orgs) == 2

    @pytest.mark.asyncio
    async def test_extract_captcha_raises(self):
        from src.actions.yandex_maps import YandexCaptchaError, YandexMapsExtractAction

        page = _make_page_mock([])
        page.content = AsyncMock(
            return_value="<html><body><div class='smartcaptcha'>captcha</div></body></html>"
        )

        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        ctx.close = AsyncMock()

        action = YandexMapsExtractAction()
        action.scroll_limit = 1
        with patch.object(
            action.pool_manager, "create_context", new=AsyncMock(return_value=ctx)
        ), patch("src.actions.yandex_maps.proxy_provider") as proxy_mock:
            proxy_mock.get_proxy.return_value = None
            with pytest.raises(YandexCaptchaError):
                await action.execute(query="x", target_count=1)

    @pytest.mark.asyncio
    async def test_extract_skips_non_search_xhrs(self):
        from src.actions.yandex_maps import YandexMapsExtractAction

        # Unrelated XHR — should be ignored.
        responses = [
            _make_response_mock(
                "https://yandex.ru/maps/api/photos?id=42",
                json.dumps({"data": {"items": [{"id": "x", "permalink": "x", "seoname": "x"}]}}),
            )
        ]
        page = _make_page_mock(responses)

        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        ctx.close = AsyncMock()

        action = YandexMapsExtractAction()
        action.scroll_limit = 1
        with patch.object(
            action.pool_manager, "create_context", new=AsyncMock(return_value=ctx)
        ), patch("src.actions.yandex_maps.proxy_provider") as proxy_mock, patch(
            "src.actions.yandex_maps.asyncio.sleep", new=AsyncMock()
        ):
            proxy_mock.get_proxy.return_value = None
            orgs = await action.execute(query="x", target_count=1)

        assert orgs == []


# ---------------------------------------------------------------------------
# YandexMapsReviewsAction — observation + replay logic
# ---------------------------------------------------------------------------


class TestYandexMapsReviewsAction:
    @pytest.mark.asyncio
    async def test_reviews_observes_and_replays(self):
        from src.actions.yandex_maps import YandexMapsReviewsAction

        fixture = _load_fixture(REVIEWS_FIXTURE)

        observed_url = (
            "https://yandex.ru/maps/api/business/fetchReviews"
            "?ajax=1&businessId=82071161567&from=0&count=50"
        )

        page = _make_page_mock([_make_response_mock(observed_url, "{}", 200)])

        # `page.request.get(...)` returns the actual fixture body.
        replay_resp = MagicMock()
        replay_resp.status = 200
        replay_resp.json = AsyncMock(return_value=fixture)
        request_proxy = MagicMock()
        request_proxy.get = AsyncMock(return_value=replay_resp)
        page.request = request_proxy

        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        ctx.close = AsyncMock()

        action = YandexMapsReviewsAction()
        action.scroll_iterations = 1
        with patch.object(
            action.pool_manager, "create_context", new=AsyncMock(return_value=ctx)
        ), patch("src.actions.yandex_maps.proxy_provider") as proxy_mock, patch(
            "src.actions.yandex_maps.asyncio.sleep", new=AsyncMock()
        ):
            proxy_mock.get_proxy.return_value = None
            reviews = await action.execute(
                business_oid="82071161567", seoname="dental_konfidens", pages=1
            )

        assert len(reviews) == 3
        ids = {r.review_id for r in reviews}
        assert "Y2uI6pYCxMQ4m4uKsxEHRjPGRfPTYvsqZ" in ids
        # `page.request.get` must have been called against the observed URL
        request_proxy.get.assert_awaited_once()
        assert request_proxy.get.await_args.args[0] == observed_url

    @pytest.mark.asyncio
    async def test_reviews_dedup_by_review_id(self):
        from src.actions.yandex_maps import YandexMapsReviewsAction

        fixture = _load_fixture(REVIEWS_FIXTURE)

        page = _make_page_mock(
            [
                _make_response_mock(
                    f"https://yandex.ru/maps/api/business/fetchReviews?ajax=1&p={i}",
                    "{}",
                    200,
                )
                for i in range(2)
            ]
        )
        replay_resp = MagicMock()
        replay_resp.status = 200
        replay_resp.json = AsyncMock(return_value=fixture)
        page.request = MagicMock()
        page.request.get = AsyncMock(return_value=replay_resp)

        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        ctx.close = AsyncMock()

        action = YandexMapsReviewsAction()
        action.scroll_iterations = 1
        with patch.object(
            action.pool_manager, "create_context", new=AsyncMock(return_value=ctx)
        ), patch("src.actions.yandex_maps.proxy_provider") as proxy_mock, patch(
            "src.actions.yandex_maps.asyncio.sleep", new=AsyncMock()
        ):
            proxy_mock.get_proxy.return_value = None
            reviews = await action.execute(
                business_oid="1", seoname="x", pages=2
            )

        # Same fixture replayed twice → still only 3 unique reviewIds.
        assert len(reviews) == 3

    @pytest.mark.asyncio
    async def test_reviews_captcha_raises(self):
        from src.actions.yandex_maps import YandexCaptchaError, YandexMapsReviewsAction

        page = _make_page_mock([])
        page.content = AsyncMock(
            return_value="<html><body><div class='smartcaptcha'></div></body></html>"
        )

        ctx = MagicMock()
        ctx.new_page = AsyncMock(return_value=page)
        ctx.close = AsyncMock()

        action = YandexMapsReviewsAction()
        with patch.object(
            action.pool_manager, "create_context", new=AsyncMock(return_value=ctx)
        ), patch("src.actions.yandex_maps.proxy_provider") as proxy_mock:
            proxy_mock.get_proxy.return_value = None
            with pytest.raises(YandexCaptchaError):
                await action.execute(business_oid="1", seoname="x")


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------


class TestActionRegistry:
    def test_yandex_maps_extract_registered(self):
        from src.domain.models.dsl import CommandType
        from src.domain.registry.action_registry import action_registry

        # Importing triggers registration as a side effect.
        from src.actions import yandex_maps  # noqa: F401

        assert action_registry.get_action(CommandType.YANDEX_MAPS_EXTRACT) is not None

    def test_yandex_maps_reviews_registered(self):
        from src.domain.models.dsl import CommandType
        from src.domain.registry.action_registry import action_registry

        from src.actions import yandex_maps  # noqa: F401

        assert action_registry.get_action(CommandType.YANDEX_MAPS_REVIEWS) is not None
