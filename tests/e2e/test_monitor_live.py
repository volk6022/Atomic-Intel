"""Live smoke for the monitor — hits real sites. Skipped unless MONITOR_LIVE=1.

    MONITOR_LIVE=1 uv run python -m pytest tests/e2e/test_monitor_live.py -q -s

httpx-friendly sources only (fl/kwork/youdo/habr/superjob) — hh/avito need the
browser and are exercised manually. Asserts collect() returns items live.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MONITOR_LIVE") != "1", reason="live smoke; set MONITOR_LIVE=1 to run"
)

_HTTPX_SOURCES = ["fl", "kwork", "youdo", "habr", "superjob"]


@pytest.mark.parametrize("source", _HTTPX_SOURCES)
async def test_collect_live(source):
    from src.actions.monitoring import get_scraper

    items = await get_scraper(source).collect(limit=5)
    assert items, f"{source}: collect returned no items"
    first = items[0]
    assert first.source == source and first.id and first.url
    print(f"\n[{source}] {len(items)} items; first: {first.title[:60]!r} {first.url}")
