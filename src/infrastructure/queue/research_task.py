"""Taskiq task that executes the flat-loop research agent."""

import logging
from datetime import datetime, timezone

from src.infrastructure.queue.broker import broker

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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

    try:
        final_report = await run_research(
            query,
            mode=mode,
            language=target_language,
            output_schema=output_schema,
            max_turns=task_data.get("max_iters"),
            max_tokens=task_data.get("max_tokens"),
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
