"""Scheduled demand-side monitor sweep.

``run_monitor_sweep`` is a plain async function (unit-testable with mocked
scrapers) that, per source: collects the newest items, keeps only those matching
the IT keyword filter, diffs them against :mod:`monitor_store`, marks them seen and
emits the genuinely new ones. ``scheduled_monitor_sweep`` is the Taskiq wrapper the
scheduler fires on a cron cadence derived from ``MONITOR_INTERVAL_MINUTES``.
"""

from __future__ import annotations

from typing import Optional

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from src.actions.monitoring import SOURCE_REGISTRY, get_scraper
from src.core.config import settings
from src.core.logging import get_logger
from src.infrastructure.queue.broker import broker
from src.infrastructure.tasks import monitor_store

logger = get_logger(__name__)


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def _resolve_sources(sources: Optional[list[str]]) -> list[str]:
    if sources:
        return [s for s in sources if s in SOURCE_REGISTRY]
    configured = _csv(settings.MONITOR_SOURCES)
    if configured:
        return [s for s in configured if s in SOURCE_REGISTRY]
    return sorted(SOURCE_REGISTRY.keys())


def _matches(item, keywords: list[str]) -> bool:
    if not keywords:
        return True
    hay = (item.title + " " + str((item.extra or {}).get("desc", ""))).lower()
    return any(kw in hay for kw in keywords)


async def run_monitor_sweep(
    sources: Optional[list[str]] = None,
    limit: Optional[int] = None,
) -> dict:
    """One sweep across sources → emit new, keyword-matching items. Returns a summary."""
    limit = limit or settings.MONITOR_COLLECT_LIMIT
    keywords = [k.lower() for k in _csv(settings.MONITOR_KEYWORDS)]
    summary: dict[str, dict] = {}
    new_total = 0

    for src in _resolve_sources(sources):
        try:
            items = await get_scraper(src).collect(limit=limit)
        except Exception as exc:  # noqa: BLE001 — one source failing must not abort the sweep
            summary[src] = {"ok": False, "error": str(exc)}
            logger.warning("monitor sweep: %s collect failed: %s", src, exc)
            continue

        matched = [it for it in items if _matches(it, keywords)]
        ids = [it.id for it in matched]
        new_ids = set(monitor_store.filter_new(src, ids))
        new_items = [it for it in matched if it.id in new_ids]

        monitor_store.mark_seen(src, ids)
        if new_items:
            monitor_store.record_new([it.model_dump() for it in new_items])

        new_total += len(new_items)
        summary[src] = {
            "ok": True,
            "collected": len(items),
            "matched": len(matched),
            "new": len(new_items),
        }
        logger.info("monitor sweep: %s collected=%d matched=%d new=%d",
                    src, len(items), len(matched), len(new_items))

    return {"sources": summary, "new_total": new_total}


def _sweep_cron() -> str:
    """Cron expression from MONITOR_INTERVAL_MINUTES (every N min, or hourly)."""
    n = max(1, settings.MONITOR_INTERVAL_MINUTES)
    return f"*/{n} * * * *" if n < 60 else "0 * * * *"


@broker.task(schedule=[{"cron": _sweep_cron()}])
async def scheduled_monitor_sweep() -> dict:
    return await run_monitor_sweep()


# Scheduler entrypoint:  taskiq scheduler src.infrastructure.queue.monitor_worker:scheduler
scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
