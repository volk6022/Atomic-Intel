"""Scheduled demand-side monitor sweep.

One pass looks like this, per source:

    collect → keyword prefilter → dedup → detail → cheap filters
            → contour → score → threshold → draft → Telegram

``run_monitor_sweep`` is a plain async function so it can be unit-tested with
mocked scrapers and a mocked LLM; ``scheduled_monitor_sweep`` is the Taskiq
wrapper the scheduler fires.

Two rules the ordering encodes:

- **Cheap before expensive.** Budget floor, competition cap and the keyword
  dictionary all run before a single token is spent. kwork narrows further on its
  own side, so most of the noise never reaches us at all.
- **Nothing is dropped silently.** Every item that stops early is written to the
  result log with the reason, and only *then* marked seen. If the whole LLM chain
  is down the item stays unseen deliberately, so the next sweep retries it rather
  than losing it.
"""

from __future__ import annotations

import inspect
from typing import Any, Optional

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from src.actions.monitoring import SOURCE_REGISTRY, get_scraper, notify, scoring
from src.core.config import settings
from src.core.logging import get_logger
from src.infrastructure.external_api import llm_chain
from src.infrastructure.queue.broker import broker
from src.infrastructure.tasks import monitor_settings, monitor_store

logger = get_logger(__name__)


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def _resolve_sources(sources: Optional[list[str]]) -> list[str]:
    if sources:
        return [s for s in sources if s in SOURCE_REGISTRY]
    return [s for s in monitor_settings.sources() if s in SOURCE_REGISTRY]


def _matches_keywords(item, keywords: list[str]) -> bool:
    if not keywords:
        return True
    hay = (item.title + " " + str((item.extra or {}).get("desc", ""))).lower()
    return any(kw in hay for kw in keywords)


async def _collect(source: str, limit: int):
    """Collect from one source, pushing what we can onto the exchange itself."""
    scraper = get_scraper(source)
    kwargs: dict[str, Any] = {}

    if source == "kwork":
        # kwork answers "budget from N" and "fewer than five offers" server-side.
        # Asking it there costs one request; doing it here costs a scoring call
        # per posting we were going to throw away anyway.
        cap = monitor_settings.max_offers()
        kwargs = {
            "price_from": monitor_settings.min_price() or None,
            "few_offers": bool(cap and cap <= 5),
        }

    if kwargs:
        # Only pass what this scraper actually declares. The source interface
        # promises `collect(limit)` and nothing more, so a source that has not
        # (or cannot) implement exchange-side filtering must still work here.
        accepted = inspect.signature(scraper.collect).parameters
        kwargs = {k: v for k, v in kwargs.items() if k in accepted}

    return await scraper.collect(limit=limit, **kwargs)


async def _enrich(source: str, item) -> dict:
    """Item plus whatever the detail step can add. Never raises."""
    payload = item.model_dump()
    try:
        detail = await get_scraper(source).detail(payload)
    except Exception as exc:  # noqa: BLE001 - a failed detail is not a failed item
        logger.info("monitor: detail failed for %s/%s: %s", source, item.id, exc)
        return payload
    # Detail wins where it has something, but an empty detail field must never
    # overwrite a populated listing field — that is how the old parser turned a
    # usable RSS teaser into an empty brief.
    merged = {**payload, **{k: v for k, v in detail.items() if v not in (None, "", {}, [])}}
    merged["extra"] = {**(payload.get("extra") or {})}
    if detail.get("client"):
        merged["extra"]["client"] = detail["client"]
    return merged


def _log_drop(item: dict, stage: str, reason: str) -> None:
    monitor_store.record_result(
        {
            "source": item.get("source"),
            "id": item.get("id"),
            "title": item.get("title"),
            "url": item.get("url"),
            "amount": item.get("amount"),
            "stage": stage,
            "reason": reason,
            "notified": False,
        }
    )
    monitor_store.bump_stat(f"dropped_{stage}")


async def run_monitor_sweep(
    sources: Optional[list[str]] = None,
    limit: Optional[int] = None,
    *,
    notify_enabled: bool = True,
) -> dict:
    """One sweep across sources. Returns a per-source summary."""
    limit = limit or settings.MONITOR_COLLECT_LIMIT
    keywords = [k.lower() for k in _csv(settings.MONITOR_KEYWORDS)]
    summary: dict[str, dict] = {}
    sent_total = 0
    new_total = 0

    client, llm_name = await llm_chain.get_scoring_client()
    if client is None:
        # Not an error worth failing on: collecting still refreshes the price
        # anchors, and leaving the items unseen means nothing is lost.
        logger.warning("monitor: no reachable LLM - collecting only, items stay unseen")

    for source in _resolve_sources(sources):
        try:
            items = await _collect(source, limit)
        except Exception as exc:  # noqa: BLE001 - one dead source must not abort the sweep
            summary[source] = {"ok": False, "error": str(exc)}
            logger.warning("monitor sweep: %s collect failed: %s", source, exc)
            continue

        # Remember which rubrics this source actually emits, so `/mon cats` can
        # offer real buttons instead of asking the operator to type ids.
        monitor_store.record_categories(
            source, [str((it.extra or {}).get("category") or "") for it in items]
        )

        contours = {
            it.id: monitor_settings.contour_for(source, (it.extra or {}).get("category"))
            for it in items
        }
        # A posting in one of "my" categories is never dropped on wording: the
        # keyword list is a blunt instrument and contour A exists precisely
        # because those categories deserve a look regardless of phrasing.
        matched = [
            it for it in items
            if contours[it.id] == monitor_settings.CONTOUR_A or _matches_keywords(it, keywords)
        ]
        new_ids = set(monitor_store.filter_new(source, [it.id for it in matched]))
        fresh = [it for it in matched if it.id in new_ids]

        monitor_store.bump_stat("collected", len(items))
        monitor_store.bump_stat("new", len(fresh))

        if client is None:
            summary[source] = {
                "ok": True, "collected": len(items), "matched": len(matched),
                "new": len(fresh), "scored": 0, "sent": 0, "note": "llm down",
            }
            continue

        monitor_store.record_new([it.model_dump() for it in fresh])
        new_total += len(fresh)

        scored_ok, sent = 0, 0
        for item in fresh:
            payload = await _enrich(source, item)
            contour = contours[item.id]

            ok, reason = scoring.passes_cheap_filters(payload)
            if not ok:
                _log_drop(payload, "prefilter", reason)
                monitor_store.mark_seen(source, [item.id])
                continue

            try:
                verdict = await scoring.score_item(
                    client, payload, contour=contour
                )
            except Exception as exc:  # noqa: BLE001 - a bad reply must not stall the sweep
                logger.warning("monitor: scoring failed for %s/%s: %s", source, item.id, exc)
                _log_drop(payload, "score_error", str(exc)[:200])
                monitor_store.mark_seen(source, [item.id])
                continue

            scored_ok += 1
            monitor_store.bump_stat("scored")
            threshold = monitor_settings.threshold(contour)
            passed = verdict["score"] >= threshold

            draft = ""
            if passed and notify_enabled:
                draft = await scoring.draft_reply(client, payload, verdict)

            monitor_store.record_result(
                {
                    "source": source,
                    "id": item.id,
                    "title": payload.get("title"),
                    "url": payload.get("url"),
                    "amount": payload.get("amount"),
                    "stage": "scored",
                    "contour": contour,
                    "score": verdict["score"],
                    "threshold": threshold,
                    "match_type": verdict.get("match_type"),
                    "matched_offer": verdict.get("matched_offer"),
                    "reason": verdict.get("reason"),
                    "notified": False,
                    "draft": draft,
                    "item": payload,
                }
            )

            if passed and notify_enabled:
                if await notify.send_notification(payload, verdict, draft):
                    sent += 1
                    monitor_store.bump_stat("sent")
            elif not passed:
                monitor_store.bump_stat("below_threshold")

            monitor_store.mark_seen(source, [item.id])

        sent_total += sent
        summary[source] = {
            "ok": True, "collected": len(items), "matched": len(matched),
            "new": len(fresh), "scored": scored_ok, "sent": sent,
        }
        logger.info(
            "monitor sweep: %s collected=%d matched=%d new=%d scored=%d sent=%d (llm=%s)",
            source, len(items), len(matched), len(fresh), scored_ok, sent, llm_name,
        )

    return {
        "sources": summary,
        "new_total": new_total,
        "sent_total": sent_total,
        "llm": llm_name,
    }


def _sweep_cron() -> str:
    """Cron expression from MONITOR_INTERVAL_MINUTES (every N min, or hourly).

    Read once, at import: Taskiq label schedules are static. Changing the
    interval from the bot takes effect on the next scheduler restart — the
    command says so rather than pretending otherwise.
    """
    n = max(1, settings.MONITOR_INTERVAL_MINUTES)
    return f"*/{n} * * * *" if n < 60 else "0 * * * *"


@broker.task(schedule=[{"cron": _sweep_cron()}])
async def scheduled_monitor_sweep() -> dict[str, Any]:
    if not monitor_settings.enabled():
        logger.info("monitor: disabled (/mon on to enable) - skipping sweep")
        return {"skipped": "disabled"}
    return await run_monitor_sweep()


# Scheduler entrypoint:  taskiq scheduler src.infrastructure.queue.monitor_worker:scheduler
scheduler = TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
