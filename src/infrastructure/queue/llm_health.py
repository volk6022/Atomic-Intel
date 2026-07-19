"""LLM-endpoint reachability probe + drain supervisor for the research queue.

Before a research task actually runs the agent, ``execute_research_task``
(see ``research_task.py``) calls :func:`check_llm_reachable` against the
task's LLM endpoint (the tenant's BYO config, else the global
``ORCHESTRATION_*`` settings). If the endpoint is down, the task is parked in
the ``queued_waiting_llm`` status instead of failing (see
``research_store.get_tasks_waiting_for_llm`` / ``set_task``).

:func:`run_supervisor_loop` runs once per worker process, started from
``research_task.py`` on the taskiq ``WORKER_STARTUP`` event. Each tick it
re-probes every *distinct* endpoint currently blocking at least one task and
re-enqueues (drains) every task parked behind an endpoint that has come back.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

# endpoint_key -> (checked_at monotonic seconds, healthy)
_probe_cache: dict[str, tuple[float, bool]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def endpoint_key(llm_provider_config: Optional[dict[str, Any]]) -> str:
    """Stable identity for an LLM endpoint (its base_url).

    Tasks are grouped/drained by this key so the supervisor pings each
    distinct endpoint once per tick, not once per waiting task.
    """
    if llm_provider_config:
        base_url = llm_provider_config.get("base_url")
        if base_url:
            return str(base_url)
    from src.infrastructure.tasks.research_store import house_llm_base_url

    return house_llm_base_url()


async def _ping(llm_provider_config: Optional[dict[str, Any]]) -> bool:
    """Single reachability probe.

    Distinguishes "endpoint unreachable" (connection error / timeout ->
    unhealthy, task should wait) from "endpoint reachable but erroring
    otherwise" (any HTTP response, even 401/404/500, means something is
    listening -> healthy). A misconfigured API key or model name on an
    otherwise-live endpoint is a genuine task error, not an availability gap,
    and surfaces later as a normal `failed` task rather than
    `queued_waiting_llm`.
    """
    from src.infrastructure.tasks.research_store import house_llm_base_url

    if llm_provider_config:
        base_url = llm_provider_config.get("base_url") or house_llm_base_url()
        api_key = llm_provider_config.get("api_key") or settings.ORCHESTRATION_API_KEY
    else:
        base_url = house_llm_base_url()
        api_key = settings.ORCHESTRATION_API_KEY

    url = f"{base_url.rstrip('/')}/models"
    timeout = settings.LLM_HEALTH_PING_TIMEOUT_SECONDS
    try:
        # Belt-and-suspenders timeout: httpx's own timeout plus an outer
        # asyncio.wait_for, so a hung endpoint (or a client bug) can never
        # block the supervisor loop past `timeout` seconds.
        async with httpx.AsyncClient(timeout=timeout) as client:
            await asyncio.wait_for(
                client.get(url, headers={"Authorization": f"Bearer {api_key}"}),
                timeout=timeout,
            )
        return True
    except Exception as e:  # noqa: BLE001 — any network failure means "down"
        logger.warning("llm_health: endpoint %s unreachable: %s", base_url, e)
        return False


async def check_llm_reachable(
    llm_provider_config: Optional[dict[str, Any]], *, force: bool = False
) -> bool:
    """Cached reachability check.

    ``force=True`` bypasses the cache (used by the supervisor, which wants a
    fresh probe every tick). The default cached path is used by the
    per-task pre-flight check in ``execute_research_task`` — it caps how
    often a burst of tasks against the same endpoint actually hits the
    network (see ``LLM_HEALTH_PROBE_CACHE_SECONDS``).
    """
    key = endpoint_key(llm_provider_config)
    now = time.monotonic()
    if not force:
        cached = _probe_cache.get(key)
        if cached is not None and (now - cached[0]) < settings.LLM_HEALTH_PROBE_CACHE_SECONDS:
            return cached[1]

    healthy = await _ping(llm_provider_config)
    _probe_cache[key] = (now, healthy)
    return healthy


async def run_supervisor_once() -> dict[str, int]:
    """One drain pass: probe every distinct endpoint with waiting tasks, and
    re-enqueue every task parked behind an endpoint that answered."""
    from src.infrastructure.tasks.research_store import (
        get_tasks_waiting_for_llm,
        set_task,
        try_claim_drain,
    )

    waiting = await get_tasks_waiting_for_llm()
    if not waiting:
        return {"waiting": 0, "drained": 0}

    groups: dict[str, list[dict]] = {}
    for task in waiting:
        key = task.get("llm_endpoint_key") or endpoint_key(task.get("llm_provider_config"))
        groups.setdefault(key, []).append(task)

    drained = 0
    for group in groups.values():
        sample_config = group[0].get("llm_provider_config")
        reachable = await check_llm_reachable(sample_config, force=True)
        if not reachable:
            continue

        # Lazy import: research_task imports this module at top level to
        # register the supervisor's startup/shutdown hooks, so importing it
        # back here eagerly would be circular.
        from src.infrastructure.queue.research_task import execute_research_task

        for task in group:
            task_id = task["task_id"]
            # Single-flight: the supervisor runs in every worker process, so
            # only the one that claims the task re-enqueues it (else both
            # workers would run the same drained task).
            if not try_claim_drain(task_id):
                continue
            set_task(task_id, {
                "status": "running",
                "phase": "starting",
                "updated_at": _now_iso(),
            })
            try:
                await execute_research_task.kiq(task_id)
                drained += 1
            except Exception:
                logger.exception("llm_health: failed to re-enqueue drained task %s", task_id)
                set_task(task_id, {
                    "status": "queued_waiting_llm",
                    "phase": "waiting_llm",
                    "updated_at": _now_iso(),
                })

    return {"waiting": len(waiting), "drained": drained}


async def run_supervisor_loop() -> None:
    """Runs for the life of the worker process — started on WORKER_STARTUP,
    cancelled on WORKER_SHUTDOWN (see ``research_task.py``)."""
    interval = settings.LLM_HEALTH_POLL_INTERVAL_SECONDS
    logger.info("llm_health supervisor started (interval=%ss)", interval)
    while True:
        try:
            result = await run_supervisor_once()
            if result["waiting"]:
                logger.info(
                    "llm_health supervisor: waiting=%d drained=%d",
                    result["waiting"], result["drained"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("llm_health supervisor iteration failed")
        await asyncio.sleep(interval)
