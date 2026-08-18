"""Unit tests for the sweep pipeline: dedup, contours, prefilters, notification.

No network, no Redis, no LLM — the scrapers and the scoring client are both
faked, which is the reason ``run_monitor_sweep`` is a plain function rather than
something welded to Taskiq.
"""

from unittest.mock import patch

import pytest

from src.domain.models.monitoring import MonitorItem
from src.infrastructure.queue import monitor_worker as mw
from src.infrastructure.tasks import monitor_settings, monitor_store


class _FakeScraper:
    def __init__(self, items):
        self._items = items

    async def collect(self, limit=25):
        return self._items

    async def detail(self, item):
        return {}


class _FakeLLM:
    """Scores by title length so a test can steer which items clear a threshold."""

    def __init__(self, score=90, match_type="listing"):
        self.score = score
        self.match_type = match_type
        self.calls = []

    async def generate_structured(self, *, prompt, system_prompt=None, schema, **kw):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        return {
            "score": self.score,
            "match_type": self.match_type,
            "matched_offer": "Парсер под ключ",
            "have": ["парсинг"],
            "gap": [],
            "verdict": "take",
            "reason": "подходит",
        }

    async def generate(self, prompt, system_prompt=None):
        return "черновик отклика"


@pytest.fixture(autouse=True)
def _clean_state():
    monitor_store._reset_local()
    # Settings share research_store's local mirror; wipe it so one test's
    # threshold does not leak into the next.
    from src.infrastructure.tasks import research_store

    research_store._local_settings.clear()
    yield
    monitor_store._reset_local()
    research_store._local_settings.clear()


def _items():
    return [
        MonitorItem(source="fl", id="1", title="Python parser bot", url="u1",
                    extra={"desc": "парсинг", "category": "Программирование"}),
        MonitorItem(source="fl", id="2", title="Логотип для кафе", url="u2",
                    extra={"desc": "нарисовать", "category": "Дизайн"}),
        MonitorItem(source="fl", id="3", title="ML data pipeline", url="u3",
                    extra={"category": "Программирование"}),
    ]


async def _sweep(items, llm=None, **kwargs):
    llm = llm or _FakeLLM()
    with patch.object(mw, "get_scraper", return_value=_FakeScraper(items)), \
         patch.object(mw.llm_chain, "get_scoring_client", return_value=(llm, "fake")), \
         patch.object(mw.notify, "send_notification", return_value=True):
        return await mw.run_monitor_sweep(sources=["fl"], **kwargs), llm


async def test_dedup_and_keyword_filter():
    items = _items()
    first, _ = await _sweep(items)
    second, _ = await _sweep(items)

    # id 2 (a logo) is filtered out by the keyword dictionary
    assert first["sources"]["fl"]["matched"] == 2
    assert first["new_total"] == 2
    # a second pass over the same feed emits nothing
    assert second["new_total"] == 0
    assert len(monitor_store.get_recent_new()) == 2


async def test_contour_a_survives_the_keyword_filter():
    """A category the operator marked as his is never dropped on wording."""
    monitor_settings.set_contour_categories({"fl": ["Дизайн"]})
    result, _ = await _sweep(_items())
    assert result["sources"]["fl"]["matched"] == 3


async def test_contour_picks_its_own_threshold_and_prompt():
    monitor_settings.set_contour_categories({"fl": ["Программирование"]})
    monitor_settings.set_threshold(monitor_settings.CONTOUR_A, 10)
    monitor_settings.set_threshold(monitor_settings.CONTOUR_B, 99)

    llm = _FakeLLM(score=50)
    result, llm = await _sweep(_items(), llm=llm)

    # Both matching items are in contour A, whose threshold 50 clears.
    assert result["sent_total"] == 2
    system_prompts = {c["system_prompt"] for c in llm.calls}
    assert len(system_prompts) == 1, "contour A must use a single prompt body"


async def test_below_threshold_is_recorded_but_not_sent():
    monitor_settings.set_threshold(monitor_settings.CONTOUR_B, 95)
    result, _ = await _sweep(_items(), llm=_FakeLLM(score=40))

    assert result["sent_total"] == 0
    scored = [r for r in monitor_store.get_results(10) if r["stage"] == "scored"]
    assert scored and all(r["score"] == 40 for r in scored)
    assert monitor_store.get_stats()["below_threshold"] == 2


async def test_cheap_filter_drops_before_the_model_and_says_why():
    monitor_settings.set_min_price(10_000)
    items = [
        MonitorItem(source="fl", id="1", title="Python parser", url="u1",
                    amount="3000 RUB", extra={"desc": "парсинг"}),
    ]
    llm = _FakeLLM()
    result, llm = await _sweep(items, llm=llm)

    assert result["sent_total"] == 0
    assert llm.calls == [], "the model must not be called for a filtered item"
    dropped = monitor_store.get_results(10)[0]
    assert dropped["stage"] == "prefilter"
    assert "3000" in dropped["reason"]


async def test_missing_budget_is_not_treated_as_zero():
    """fl.ru says 'negotiable' by omitting the price; that must not drop the item."""
    monitor_settings.set_min_price(10_000)
    items = [
        MonitorItem(source="fl", id="1", title="Python parser", url="u1",
                    amount=None, extra={"desc": "парсинг"}),
    ]
    result, _ = await _sweep(items)
    assert result["sent_total"] == 1


async def test_items_stay_unseen_when_every_llm_is_down():
    """Nothing may be lost because the GPU was busy for one sweep."""
    items = _items()
    with patch.object(mw, "get_scraper", return_value=_FakeScraper(items)), \
         patch.object(mw.llm_chain, "get_scoring_client", return_value=(None, None)):
        first = await mw.run_monitor_sweep(sources=["fl"])

    assert first["sources"]["fl"]["note"] == "llm down"
    # the same items must come back on the next sweep, once the model answers
    second, _ = await _sweep(items)
    assert second["new_total"] == 2


async def test_one_source_failure_is_isolated():
    class _Boom:
        async def collect(self, limit=25):
            raise RuntimeError("blocked")

    with patch.object(mw, "get_scraper", return_value=_Boom()), \
         patch.object(mw.llm_chain, "get_scoring_client", return_value=(_FakeLLM(), "fake")):
        result = await mw.run_monitor_sweep(sources=["kwork"])

    assert result["sources"]["kwork"]["ok"] is False
    assert "blocked" in result["sources"]["kwork"]["error"]


async def test_scoring_failure_does_not_stall_the_sweep():
    class _BadLLM(_FakeLLM):
        async def generate_structured(self, **kw):
            raise ValueError("garbage json")

    result, _ = await _sweep(_items(), llm=_BadLLM())
    assert result["sources"]["fl"]["scored"] == 0
    assert any(r["stage"] == "score_error" for r in monitor_store.get_results(10))
