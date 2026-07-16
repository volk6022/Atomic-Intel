"""Dedup store for the monitor sweep — remembers which (source, id) pairs were
already seen so each sweep only emits genuinely new items.

Mirrors ``research_store.py``: a sync Redis client with a process-local dict
fallback so unit tests run without Redis. Seen ids live in a per-source Redis SET
with a sliding TTL; recently-emitted new items are pushed to a capped list for
inspection / the API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.config import settings

logger = logging.getLogger(__name__)

_SEEN_PREFIX = "monitor:seen:"     # + <source>  → Redis SET of ids
_NEW_KEY = "monitor:new"           # capped list of recently-emitted new items
_NEW_MAX = 500

# in-memory fallback
_local_seen: dict[str, set[str]] = {}
_local_new: list[dict] = []


def _get_redis():
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        logger.warning("Redis unavailable for monitor_store, using in-memory fallback: %s", e)
        return None


def filter_new(source: str, ids: list[str]) -> list[str]:
    """Return the subset of ``ids`` not previously seen for ``source`` (order-preserving)."""
    ids = [str(i) for i in ids if i]
    if not ids:
        return []
    r = _get_redis()
    if r is None:
        seen = _local_seen.get(source, set())
        return [i for i in ids if i not in seen]
    try:
        key = f"{_SEEN_PREFIX}{source}"
        # SMISMEMBER preserves input order; returns 1/0 per id.
        flags = r.smismember(key, ids)
        return [i for i, f in zip(ids, flags) if not f]
    except Exception as e:
        logger.error("monitor_store.filter_new failed for %s: %s", source, e)
        seen = _local_seen.get(source, set())
        return [i for i in ids if i not in seen]


def mark_seen(source: str, ids: list[str]) -> None:
    """Record ``ids`` as seen for ``source`` and refresh the sliding TTL."""
    ids = [str(i) for i in ids if i]
    if not ids:
        return
    r = _get_redis()
    if r is None:
        _local_seen.setdefault(source, set()).update(ids)
        return
    try:
        key = f"{_SEEN_PREFIX}{source}"
        r.sadd(key, *ids)
        r.expire(key, settings.MONITOR_SEEN_TTL_DAYS * 24 * 3600)
    except Exception as e:
        logger.error("monitor_store.mark_seen failed for %s: %s", source, e)
        _local_seen.setdefault(source, set()).update(ids)


def record_new(items: list[dict]) -> None:
    """Push newly-emitted items onto the capped inspection list."""
    if not items:
        return
    r = _get_redis()
    if r is None:
        _local_new[:0] = items
        del _local_new[_NEW_MAX:]
        return
    try:
        payloads = [json.dumps(it, default=_json_default) for it in items]
        r.lpush(_NEW_KEY, *payloads)
        r.ltrim(_NEW_KEY, 0, _NEW_MAX - 1)
    except Exception as e:
        logger.error("monitor_store.record_new failed: %s", e)


def get_recent_new(limit: int = 50) -> list[dict]:
    """Most-recently emitted new items (newest first)."""
    r = _get_redis()
    if r is None:
        return _local_new[:limit]
    try:
        return [json.loads(x) for x in r.lrange(_NEW_KEY, 0, limit - 1)]
    except Exception as e:
        logger.error("monitor_store.get_recent_new failed: %s", e)
        return _local_new[:limit]


def _reset_local() -> None:
    """Test helper: clear the in-memory fallback."""
    _local_seen.clear()
    _local_new.clear()


def _json_default(obj: Any):
    if isinstance(obj, set):
        return sorted(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
