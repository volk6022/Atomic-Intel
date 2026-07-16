"""Taskiq task that executes the flat-loop research agent.

Also owns the LLM-health supervisor's process lifecycle: a single asyncio
background loop (``llm_health.run_supervisor_loop``) started once per worker
process on the taskiq ``WORKER_STARTUP`` event and cancelled on
``WORKER_SHUTDOWN``.

An in-process asyncio loop was chosen over a taskiq cron task (the
``@broker.task(schedule=[{"cron": ...}])`` pattern used by
``infrastructure/queue/monitor_worker.py``) because the cron pattern needs a
separate ``taskiq scheduler <broker>`` process to actually fire the schedule,
and docker-compose's ``worker`` service only runs ``taskiq worker ...`` — no
scheduler process is deployed. Hooking WORKER_STARTUP/SHUTDOWN needs no new
service or deploy step: the loop lives and dies with the same worker
container that already has ``restart: unless-stopped``.
"""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from taskiq import TaskiqEvents, TaskiqState

from src.infrastructure.queue.broker import broker
from src.infrastructure.queue.llm_health import (
    check_llm_reachable,
    endpoint_key,
    run_supervisor_loop,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _start_llm_health_supervisor(state: TaskiqState) -> None:
    state.llm_health_supervisor_task = asyncio.create_task(run_supervisor_loop())


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _stop_llm_health_supervisor(state: TaskiqState) -> None:
    task = getattr(state, "llm_health_supervisor_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@broker.task
async def execute_research_task(task_id: str):
    from src.actions.research.agent import run_research
    from src.infrastructure.tasks.research_store import get_task, set_task

    logger.info("Starting research task: %s", task_id)

    task_data = get_task(task_id)
    if not task_data:
        set_task(task_id, {"status": "failed", "error": "Task not found",
                           "updated_at": _now_iso()})
        return {"task_id": task_id, "status": "failed"}

    mode = task_data.get("mode", "balanced")
    query = task_data.get("query", "")
    target_language = task_data.get("language", "en")
    output_schema = task_data.get("output_schema")
    # BYO-LLM: this worker is a separate process from the API that enqueued
    # the task, so the tenant's LLM endpoint config travels as task payload
    # (via the Redis-backed research store) rather than a request-scoped
    # global. None = fall back to global ORCHESTRATION_* settings.
    llm_provider_config = task_data.get("llm_provider_config")

    # LLM-availability gate: a down endpoint parks the task instead of
    # failing it. This is checked BEFORE the try/except below on purpose —
    # only genuine errors raised while actually running the agent should ever
    # mark a task `failed`.
    if not await check_llm_reachable(llm_provider_config):
        logger.warning("Research task %s parked: LLM endpoint unreachable", task_id)
        set_task(task_id, {
            "status": "queued_waiting_llm",
            "phase": "waiting_llm",
            "llm_endpoint_key": endpoint_key(llm_provider_config),
            "updated_at": _now_iso(),
        })
        return {"task_id": task_id, "status": "queued_waiting_llm"}

    try:
        final_report = await run_research(
            query,
            mode=mode,
            language=target_language,
            output_schema=output_schema,
            max_turns=task_data.get("max_iters"),
            max_tokens=task_data.get("max_tokens"),
            llm_provider_config=llm_provider_config,
        )

        set_task(task_id, {
            "status": "completed",
            "phase": "completed",
            "result": final_report,
            "updated_at": _now_iso(),
        })
        logger.info("Research task completed: %s", task_id)
        return {"task_id": task_id, "status": "completed"}

    except Exception as e:
        logger.exception("Research task failed: %s", task_id)
        set_task(task_id, {
            "status": "failed",
            "error": str(e),
            "updated_at": _now_iso(),
        })
        return {"task_id": task_id, "status": "failed"}
