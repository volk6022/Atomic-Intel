"""Dedup store for the monitor sweep — remembers which (source, id) pairs were
already seen so each sweep only emits genuinely new items.

Mirrors ``research_store.py``: a sync Redis client with a process-local dict
fallback so unit tests run without Redis. Seen ids live in a per-source Redis SET
with a sliding TTL; recently-emitted new items are pushed to a capped list for
inspection / the API.

Beyond dedup it also keeps what the sweep *decided*: every processed item, the
stage it stopped at, and the operator's later verdict. That record is the only
material calibration will ever have — a filter whose effect nobody can see is a
filter nobody can tune.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from src.core.config import settings

logger = logging.getLogger(__name__)

_SEEN_PREFIX = "monitor:seen:"     # + <source>  → Redis SET of ids
_NEW_KEY = "monitor:new"           # capped list of recently-emitted new items
_NEW_MAX = 500
_RESULTS_KEY = "monitor:results"   # capped list of processed items with verdicts
_RESULTS_MAX = 300
_FEEDBACK_KEY = "monitor:feedback"  # hash <source>:<id> → took | skip
_STATS_PREFIX = "monitor:stats:"   # + <YYYY-MM-DD> → hash of counters
_STATS_TTL_DAYS = 14
_CATS_PREFIX = "monitor:cats:"   # + <source> -> SET of category keys seen

# in-memory fallback
_local_seen: dict[str, set[str]] = {}
_local_new: list[dict] = []
_local_results: list[dict] = []
_local_feedback: dict[str, str] = {}
_local_stats: dict[str, dict[str, int]] = {}
_local_cats: dict[str, set[str]] = {}


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
    """Record ``ids`` as seen for ``source`` and refresh the sliding TTL.

    The sweep calls this **after** an item has been dealt with, not when it is
    collected. If scoring could not run — every LLM in the chain down — the item
    stays unseen on purpose, so the next sweep picks it up instead of losing it.
    """
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


# ------------------------------------------------------------------- results
def record_result(entry: dict) -> None:
    """Remember one processed item, including the ones that were filtered out.

    Dropped items matter more than kept ones here: ``/mon last`` showing *why*
    something never reached Telegram is what turns a wrong threshold into an
    obvious wrong threshold.
    """
    entry = {**entry, "ts": entry.get("ts") or time.time()}
    r = _get_redis()
    if r is None:
        _local_results.insert(0, entry)
        del _local_results[_RESULTS_MAX:]
        return
    try:
        r.lpush(_RESULTS_KEY, json.dumps(entry, default=_json_default))
        r.ltrim(_RESULTS_KEY, 0, _RESULTS_MAX - 1)
    except Exception as e:
        logger.error("monitor_store.record_result failed: %s", e)
        _local_results.insert(0, entry)


def get_results(limit: int = 20) -> list[dict]:
    r = _get_redis()
    if r is None:
        return _local_results[:limit]
    try:
        return [json.loads(x) for x in r.lrange(_RESULTS_KEY, 0, limit - 1)]
    except Exception as e:
        logger.error("monitor_store.get_results failed: %s", e)
        return _local_results[:limit]


def find_result(source: str, item_id: str) -> Optional[dict]:
    """Look one processed item back up — used when redrafting from a button."""
    for entry in get_results(_RESULTS_MAX):
        if entry.get("source") == source and str(entry.get("id")) == str(item_id):
            return entry
    return None


# ------------------------------------------------------------------ feedback
def record_feedback(source: str, item_id: str, verdict: str) -> None:
    field = f"{source}:{item_id}"
    r = _get_redis()
    if r is None:
        _local_feedback[field] = verdict
        return
    try:
        r.hset(_FEEDBACK_KEY, field, verdict)
    except Exception as e:
        logger.error("monitor_store.record_feedback failed: %s", e)
        _local_feedback[field] = verdict


def get_feedback() -> dict[str, str]:
    r = _get_redis()
    if r is None:
        return dict(_local_feedback)
    try:
        return r.hgetall(_FEEDBACK_KEY) or {}
    except Exception as e:
        logger.error("monitor_store.get_feedback failed: %s", e)
        return dict(_local_feedback)


# --------------------------------------------------------------------- stats
def _stats_key(day: Optional[str] = None) -> str:
    return _STATS_PREFIX + (day or time.strftime("%Y-%m-%d"))


def bump_stat(name: str, amount: int = 1) -> None:
    key = _stats_key()
    r = _get_redis()
    if r is None:
        _local_stats.setdefault(key, {})
        _local_stats[key][name] = _local_stats[key].get(name, 0) + amount
        return
    try:
        r.hincrby(key, name, amount)
        r.expire(key, _STATS_TTL_DAYS * 24 * 3600)
    except Exception as e:
        logger.error("monitor_store.bump_stat failed: %s", e)


def get_stats(day: Optional[str] = None) -> dict[str, int]:
    key = _stats_key(day)
    r = _get_redis()
    if r is None:
        return dict(_local_stats.get(key, {}))
    try:
        return {k: int(v) for k, v in (r.hgetall(key) or {}).items()}
    except Exception as e:
        logger.error("monitor_store.get_stats failed: %s", e)
        return dict(_local_stats.get(key, {}))


# ---------------------------------------------------------------- categories
# The catalogue fills itself as sweeps run. Hard-coding it would mean shipping a
# copy of two marketplaces' rubric trees and re-shipping them whenever either
# renames a section; observing what actually arrives costs nothing and never
# goes stale.
def record_categories(source: str, categories: list[str]) -> None:
    values = [str(c).strip() for c in categories if str(c).strip()]
    if not values:
        return
    key = f"{_CATS_PREFIX}{source}"
    r = _get_redis()
    if r is None:
        _local_cats.setdefault(source, set()).update(values)
        return
    try:
        r.sadd(key, *values)
        r.expire(key, _STATS_TTL_DAYS * 24 * 3600 * 2)
    except Exception as e:
        logger.error("monitor_store.record_categories failed: %s", e)
        _local_cats.setdefault(source, set()).update(values)


def get_categories(source: str) -> list[str]:
    r = _get_redis()
    if r is None:
        return sorted(_local_cats.get(source, set()))
    try:
        return sorted(r.smembers(f"{_CATS_PREFIX}{source}") or [])
    except Exception as e:
        logger.error("monitor_store.get_categories failed: %s", e)
        return sorted(_local_cats.get(source, set()))


def _reset_local() -> None:
    """Test helper: clear the in-memory fallback."""
    _local_cats.clear()
    _local_seen.clear()
    _local_new.clear()
    _local_results.clear()
    _local_feedback.clear()
    _local_stats.clear()


def _json_default(obj: Any):
    if isinstance(obj, set):
        return sorted(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
