"""Redis-backed task store for research tasks.

Shared between FastAPI (writes initial task on POST /run) and Taskiq worker
(updates phase/iteration/result). Falls back to a process-local dict only when
Redis is unreachable so unit tests keep working.

Retention: 24h Redis TTL (per spec), plus a durable disk copy of completed
tasks (see ``_persist_to_disk`` / ``_load_from_disk``) so ``get_task`` still
resolves after Redis evicts the key. Concurrency counting iterates a SCAN over
the namespace prefix — fine for hundreds of in-flight tasks.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from src.core.config import settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "research:task:"
_TTL_SECONDS = 24 * 3600

# Statuses that occupy a tenant's concurrency slot. `queued_waiting_llm` still
# counts — the task hasn't finished from the tenant's point of view, and not
# counting it would let a tenant burst past their cap the moment the LLM blips.
_ACTIVE_STATUSES = {"running", "queued_waiting_llm"}

_local_fallback: dict[str, dict] = {}


def _key(task_id: str) -> str:
    return f"{_KEY_PREFIX}{task_id}"


def _get_redis():
    """Lazy-construct a sync Redis client. Returns None if unavailable."""
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        logger.warning("Redis unavailable for research_store, using in-memory fallback: %s", e)
        return None


def get_task(task_id: str) -> Optional[dict]:
    """Get research task from store (returns full dict or None).

    Read path is Redis-first (or the in-memory fallback), disk-second: once
    the 24h Redis TTL evicts a completed task, its durable copy on disk (see
    ``_persist_to_disk``) is loaded transparently so callers don't need to
    know which tier answered.
    """
    r = _get_redis()
    if r is None:
        return _local_fallback.get(task_id) or _load_from_disk(task_id)
    try:
        raw = r.get(_key(task_id))
        if raw is None:
            return _load_from_disk(task_id)
        return json.loads(raw)
    except Exception as e:
        logger.error("research_store.get_task failed for %s: %s", task_id, e)
        return _local_fallback.get(task_id) or _load_from_disk(task_id)


def set_task(task_id: str, data: dict) -> None:
    """Merge `data` into existing task entry (or create new). Preserves fields
    not present in the patch — fixes the prior bug where worker overwrote
    `created_at`/`query`/`mode` set by the router.

    Write path: always updates Redis (or the in-memory fallback); additionally
    persists the full merged record to disk once the task reaches `completed`,
    so the durable copy is symmetric with what Redis would have returned (no
    special-casing on read).
    """
    existing = get_task(task_id) or {}
    merged: dict[str, Any] = {**existing, **data}
    merged.setdefault("task_id", task_id)
    payload = json.dumps(merged, default=_json_default)

    r = _get_redis()
    if r is None:
        _local_fallback[task_id] = merged
    else:
        try:
            r.set(_key(task_id), payload, ex=_TTL_SECONDS)
        except Exception as e:
            logger.error("research_store.set_task failed for %s: %s", task_id, e)
            _local_fallback[task_id] = merged

    if merged.get("status") == "completed":
        _persist_to_disk(task_id, merged)


def _store_dir() -> Path:
    return Path(settings.RESEARCH_STORE_DIR)


def _disk_path(task_id: str) -> Path:
    return _store_dir() / f"{task_id}.json"


def _persist_to_disk(task_id: str, data: dict) -> None:
    """Durable copy of a completed task record. Atomic write (tmp file +
    ``os.replace``) so a concurrent reader never sees a half-written file."""
    try:
        directory = _store_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = _disk_path(task_id)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(data, default=_json_default, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(tmp_path, path)
    except Exception as e:
        logger.error("research_store._persist_to_disk failed for %s: %s", task_id, e)


def _load_from_disk(task_id: str) -> Optional[dict]:
    path = _disk_path(task_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("research_store._load_from_disk failed for %s: %s", task_id, e)
        return None


async def get_tasks_waiting_for_llm() -> list[dict]:
    """All tasks currently parked in `queued_waiting_llm` (for the LLM-health
    supervisor's drain pass — see ``src.infrastructure.queue.llm_health``)."""
    r = _get_redis()
    if r is None:
        return [
            t for t in _local_fallback.values() if t.get("status") == "queued_waiting_llm"
        ]
    try:
        out: list[dict] = []
        for k in r.scan_iter(match=f"{_KEY_PREFIX}*", count=200):
            raw = r.get(k)
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("status") == "queued_waiting_llm":
                out.append(data)
        return out
    except Exception as e:
        logger.error("research_store.get_tasks_waiting_for_llm failed: %s", e)
        return [
            t for t in _local_fallback.values() if t.get("status") == "queued_waiting_llm"
        ]


async def get_concurrent_task_count(tenant_id: str) -> int:
    """Count this tenant's currently active tasks (per-tenant concurrency cap).

    Tasks are stamped with ``tenant_id`` at creation (see routers/research.py);
    the scan filters on it so one tenant's load never counts against another's
    ``concurrent_research`` limit. "Active" includes `queued_waiting_llm`: a
    task parked behind a down LLM endpoint hasn't finished from the tenant's
    perspective, and excluding it would let a tenant burst past their cap the
    moment the LLM blips.
    """
    r = _get_redis()
    if r is None:
        return sum(
            1
            for t in _local_fallback.values()
            if t.get("status") in _ACTIVE_STATUSES and t.get("tenant_id") == tenant_id
        )
    try:
        count = 0
        for k in r.scan_iter(match=f"{_KEY_PREFIX}*", count=200):
            raw = r.get(k)
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("status") in _ACTIVE_STATUSES and data.get("tenant_id") == tenant_id:
                count += 1
        return count
    except Exception as e:
        logger.error("research_store.get_concurrent_task_count failed: %s", e)
        return sum(
            1
            for t in _local_fallback.values()
            if t.get("status") in _ACTIVE_STATUSES and t.get("tenant_id") == tenant_id
        )


def _json_default(obj):
    if isinstance(obj, set):
        return sorted(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
