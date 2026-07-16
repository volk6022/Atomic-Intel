"""Research Agent API endpoints."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from src.api.auth import get_api_key
from src.core.config import settings
from src.domain.models.research import (
    ResearchRequest,
    ResearchTaskCreateResponse,
    ResearchTaskStatus,
    ResearchReport,
)
from src.infrastructure.queue.research_task import execute_research_task
from src.infrastructure.tasks.research_store import (
    get_concurrent_task_count,
    get_task,
    set_task,
)

logger = logging.getLogger(__name__)

# Backwards-compat alias used by existing tests.
get_research_task = get_task

router = APIRouter(tags=["research"])


# How long the SSE stream stays open while waiting for the worker. 30 min is
# the same cap as the longest mode's deadline (`quality` = 1200s) plus margin.
SSE_MAX_DURATION_SECONDS = 1800
SSE_POLL_INTERVAL_SECONDS = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@router.post(
    "/run",
    response_model=ResearchTaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_research(
    request: ResearchRequest,
    api_key: str = Depends(get_api_key),
):
    concurrent = await get_concurrent_task_count(api_key)
    if concurrent >= settings.MAX_CONCURRENT_RESEARCH_TASKS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum {settings.MAX_CONCURRENT_RESEARCH_TASKS} concurrent tasks allowed",
        )

    task_id = str(uuid.uuid4())
    now = _now_iso()

    set_task(task_id, {
        "task_id": task_id,
        "query": request.query,
        "mode": request.mode,
        "language": request.language,
        "output_schema": request.output_schema,
        "status": "running",
        "phase": "starting",
        "iteration": 0,
        "created_at": now,
        "updated_at": now,
    })

    # Best-effort enqueue. If the broker is unavailable (test stub, Redis down)
    # we still return 202 so the client gets a task_id — the failure is recorded
    # in the store and surfaced via /status.
    try:
        await execute_research_task.kiq(task_id)
    except Exception as e:
        logger.exception("Failed to enqueue research task %s", task_id)
        set_task(task_id, {
            "status": "failed",
            "error": f"Enqueue failed: {e}",
            "updated_at": _now_iso(),
        })

    return ResearchTaskCreateResponse(
        task_id=task_id,
        status="pending",
        message="Research task queued",
    )


@router.get("/status/{task_id}", response_model=ResearchTaskStatus)
async def get_research_status(
    task_id: str,
    api_key: str = Depends(get_api_key),
):
    task = get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found or expired",
        )

    if task.get("status") == "completed" and task.get("result"):
        return ResearchTaskStatus(
            task_id=task_id,
            status="completed",
            result=ResearchReport(**task["result"]),
            created_at=task.get("created_at", _now_iso()),
            updated_at=task.get("updated_at"),
        )

    return ResearchTaskStatus(
        task_id=task_id,
        status=task.get("status", "running"),
        progress={
            "phase": task.get("phase", "unknown"),
            "percent": min(task.get("iteration", 0) * 10, 100),
            "message": f"Iteration {task.get('iteration', 0)}",
        },
        created_at=task.get("created_at", _now_iso()),
        updated_at=task.get("updated_at"),
    )


def _sse(event: str, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/stream/{task_id}")
async def stream_research_events(
    task_id: str,
    api_key: str = Depends(get_api_key),
):
    task = get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found or expired",
        )

    async def event_generator():
        yield _sse("started", {"task_id": task_id})

        deadline = asyncio.get_event_loop().time() + SSE_MAX_DURATION_SECONDS
        last_payload: str | None = None

        while True:
            now = asyncio.get_event_loop().time()
            if now >= deadline:
                yield _sse("timeout", {"task_id": task_id})
                break

            current = get_task(task_id)
            if not current:
                yield _sse("error", {"task_id": task_id, "error": "Task disappeared"})
                break

            payload = {
                "task_id": task_id,
                "status": current.get("status"),
                "phase": current.get("phase"),
                "iteration": current.get("iteration", 0),
            }
            serialised = json.dumps(payload)
            if serialised != last_payload:
                yield _sse("progress", payload)
                last_payload = serialised

            status_value = current.get("status")
            if status_value == "completed":
                yield _sse("completed", {"task_id": task_id})
                break
            if status_value == "failed":
                yield _sse("failed", {
                    "task_id": task_id,
                    "error": current.get("error", "unknown"),
                })
                break

            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
