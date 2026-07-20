"""Research Agent API endpoints."""

import asyncio
import json
import logging
import uuid
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from src.api.auth import get_api_key
from src.core.config import settings
from src.domain.models.principal import Principal
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


class _TaskCache:
    """Simple in-memory TTL cache for task payloads (store reads only).

    Caches task objects fetched from the store to reduce repeated reads during
    rapid polling (e.g., a client calling /status every 1-2s). Only caches the
    payload; authorization checks (via _owns_task) ALWAYS run on the cached
    copy so cross-tenant leaks cannot occur.

    Eviction is lazy-on-hit PLUS a bounded sweep on insert. Lazy-on-hit alone is
    not enough: a task polled once and then abandoned is never looked up again,
    so its entry would live forever, and an entry holds a whole ResearchReport
    (answer, sources, stats). Without the ceiling a long-lived API process
    serving many tasks grows without bound.
    """

    _MAX_ENTRIES = 512

    def __init__(self, ttl_seconds: float):
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[dict, float]] = {}  # task_id -> (task, expires_at)

    def get(self, task_id: str) -> dict | None:
        """Fetch from cache if hit and not expired; return None otherwise."""
        if task_id not in self._cache:
            return None
        task, expires_at = self._cache[task_id]
        if time.time() >= expires_at:
            # Expired: evict lazily.
            del self._cache[task_id]
            return None
        return task

    def set(self, task_id: str, task: dict) -> None:
        """Store task with expiry timestamp, sweeping if over budget."""
        if len(self._cache) >= self._MAX_ENTRIES:
            self._sweep()
        self._cache[task_id] = (task, time.time() + self._ttl)

    def _sweep(self) -> None:
        """Drop expired entries; if still at the ceiling, drop the oldest."""
        now = time.time()
        for key in [k for k, (_, exp) in self._cache.items() if now >= exp]:
            del self._cache[key]
        overflow = len(self._cache) - self._MAX_ENTRIES + 1
        if overflow > 0:
            oldest = sorted(self._cache, key=lambda k: self._cache[k][1])[:overflow]
            for key in oldest:
                del self._cache[key]


_task_cache = _TaskCache(settings.STATUS_CACHE_TTL_SECONDS)

# Backwards-compat alias used by existing tests.
get_research_task = get_task

router = APIRouter(tags=["research"])


# How long the SSE stream stays open while waiting for the worker. 30 min is
# the same cap as the longest mode's deadline (`quality` = 1200s) plus margin.
SSE_MAX_DURATION_SECONDS = 1800
SSE_POLL_INTERVAL_SECONDS = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _owns_task(principal: Principal, task: dict) -> bool:
    """Tenant isolation for status/stream reads: a tenant may only see its own
    tasks (matched on the ``tenant_id`` stamped at creation). The bootstrap
    admin key can read any task. Returned as 404 (not 403) so task existence
    isn't leaked across tenants."""
    if getattr(principal, "is_bootstrap", False):
        return True
    return task.get("tenant_id") == principal.tenant_id


@router.post(
    "/run",
    response_model=ResearchTaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_research(
    request: ResearchRequest,
    principal: Principal = Depends(get_api_key),
):
    concurrent = await get_concurrent_task_count(principal.tenant_id)
    if concurrent >= principal.concurrent_research:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum {principal.concurrent_research} concurrent tasks allowed",
        )

    task_id = str(uuid.uuid4())
    now = _now_iso()

    set_task(task_id, {
        "task_id": task_id,
        "tenant_id": principal.tenant_id,
        "query": request.query,
        "mode": request.mode,
        "language": request.language,
        "output_schema": request.output_schema,
        # BYO-LLM: threaded through Redis (not a request-scoped global) so the
        # taskiq worker — a separate process — can honor this tenant's
        # endpoint. None = fall back to global ORCHESTRATION_* settings.
        "llm_provider_config": (
            principal.llm_provider_config.to_dict()
            if principal.llm_provider_config
            else None
        ),
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
    principal: Principal = Depends(get_api_key),
):
    # Try cache first to avoid repeated store reads during polling.
    task = _task_cache.get(task_id)
    if task is None:
        # Cache miss: read from store and cache for future polls.
        task = get_task(task_id)
        if task:
            _task_cache.set(task_id, task)

    # CRITICAL: _owns_task MUST run on every request (including cache hits) to
    # prevent cross-tenant access via task UUID enumeration. Never cache the
    # authorization decision; always check against the resolved tenant.
    if not task or not _owns_task(principal, task):
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
    principal: Principal = Depends(get_api_key),
):
    # Initial ownership check: try cache, then store.
    task = _task_cache.get(task_id)
    if task is None:
        task = get_task(task_id)
        if task:
            _task_cache.set(task_id, task)

    # CRITICAL: _owns_task MUST run on every request (including cache hits) to
    # prevent cross-tenant access via task UUID enumeration.
    if not task or not _owns_task(principal, task):
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

            # Try cache first; if miss, read from store and cache.
            current = _task_cache.get(task_id)
            if current is None:
                current = get_task(task_id)
                if current:
                    _task_cache.set(task_id, current)

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
