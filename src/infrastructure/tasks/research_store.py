"""Redis-backed task store for research tasks.

Shared between FastAPI (writes initial task on POST /run) and Taskiq worker
(updates phase/iteration/result). Falls back to a process-local dict only when
Redis is unreachable so unit tests keep working.

Retention: 24h (per spec). Concurrency counting iterates a SCAN over the
namespace prefix — fine for hundreds of in-flight tasks.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.core.config import settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "research:task:"
_TTL_SECONDS = 24 * 3600

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
    """Get research task from store (returns full dict or None)."""
    r = _get_redis()
    if r is None:
        return _local_fallback.get(task_id)
    try:
        raw = r.get(_key(task_id))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.error("research_store.get_task failed for %s: %s", task_id, e)
        return _local_fallback.get(task_id)


def set_task(task_id: str, data: dict) -> None:
    """Merge `data` into existing task entry (or create new). Preserves fields
    not present in the patch — fixes the prior bug where worker overwrote
    `created_at`/`query`/`mode` set by the router.
    """
    existing = get_task(task_id) or {}
    merged: dict[str, Any] = {**existing, **data}
    payload = json.dumps(merged, default=_json_default)

    r = _get_redis()
    if r is None:
        _local_fallback[task_id] = merged
        return
    try:
        r.set(_key(task_id), payload, ex=_TTL_SECONDS)
    except Exception as e:
        logger.error("research_store.set_task failed for %s: %s", task_id, e)
        _local_fallback[task_id] = merged


async def get_concurrent_task_count(api_key: str) -> int:
    """Count currently running tasks. `api_key` is reserved for per-tenant
    accounting (current impl is global — single tenant deployment).
    """
    r = _get_redis()
    if r is None:
        return sum(1 for t in _local_fallback.values() if t.get("status") == "running")
    try:
        count = 0
        for k in r.scan_iter(match=f"{_KEY_PREFIX}*", count=200):
            raw = r.get(k)
            if raw and json.loads(raw).get("status") == "running":
                count += 1
        return count
    except Exception as e:
        logger.error("research_store.get_concurrent_task_count failed: %s", e)
        return sum(1 for t in _local_fallback.values() if t.get("status") == "running")


def _json_default(obj):
    if isinstance(obj, set):
        return sorted(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
