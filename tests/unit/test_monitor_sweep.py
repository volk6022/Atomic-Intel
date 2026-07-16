"""Unit tests for the scheduled sweep dedup + keyword filter (no network, no Redis)."""

from unittest.mock import patch

from src.domain.models.monitoring import MonitorItem
from src.infrastructure.queue import monitor_worker as mw
from src.infrastructure.tasks import monitor_store


class _FakeScraper:
    def __init__(self, items):
        self._items = items

    async def collect(self, limit=25):
        return self._items


async def test_sweep_dedup_and_keyword_filter():
    monitor_store._reset_local()
    items = [
        MonitorItem(source="fl", id="1", title="Python parser bot", url="u1", extra={"desc": "парсинг"}),
        MonitorItem(source="fl", id="2", title="Логотип для кафе", url="u2", extra={"desc": "нарисовать"}),
        MonitorItem(source="fl", id="3", title="ML data pipeline", url="u3"),
    ]
    with patch.object(mw, "get_scraper", return_value=_FakeScraper(items)):
        r1 = await mw.run_monitor_sweep(sources=["fl"])
        r2 = await mw.run_monitor_sweep(sources=["fl"])

    # id 2 (logo) filtered out by keywords; ids 1 & 3 are new on run 1
    assert r1["new_total"] == 2
    assert r1["sources"]["fl"]["matched"] == 2
    # second run emits nothing new (dedup)
    assert r2["new_total"] == 0
    assert len(monitor_store.get_recent_new()) == 2


async def test_sweep_one_source_failure_isolated():
    monitor_store._reset_local()

    class _Boom:
        async def collect(self, limit=25):
            raise RuntimeError("blocked")

    with patch.object(mw, "get_scraper", return_value=_Boom()):
        r = await mw.run_monitor_sweep(sources=["kwork"])
    assert r["sources"]["kwork"]["ok"] is False
    assert "blocked" in r["sources"]["kwork"]["error"]


def test_sweep_cron_expression():
    with patch.object(mw.settings, "MONITOR_INTERVAL_MINUTES", 15):
        assert mw._sweep_cron() == "*/15 * * * *"
    with patch.object(mw.settings, "MONITOR_INTERVAL_MINUTES", 90):
        assert mw._sweep_cron() == "0 * * * *"
