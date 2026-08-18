"""Runtime settings for the demand-side monitor, editable from the Telegram bot.

Everything the operator tunes day to day — thresholds, prompts, which categories
count as "mine", the LLM fallback chain — lives here rather than in ``.env``, so
changing any of it never needs a redeploy. Storage is the same Redis key/value
pair already used by ``/sethousellm`` (``research_store.get_setting`` /
``set_setting``), namespaced under ``mon:``. The bot writes, the worker reads.

Values are JSON-encoded so lists and dicts survive the round-trip. Every getter
falls back to a code default, so an empty Redis behaves like a fresh install
rather than erroring.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from src.core.config import settings
from src.core.logging import get_logger
from src.infrastructure.tasks.research_store import get_setting, set_setting

logger = get_logger(__name__)

_NS = "mon:"

# How many previous versions of a prompt to keep so `/prompt <name> undo` can
# step back after a bad edit. Small on purpose: this is an undo, not a history.
_PROMPT_HISTORY_MAX = 5


# ----------------------------------------------------------------- primitives
def _get_json(key: str, default: Any) -> Any:
    raw = get_setting(_NS + key)
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("monitor_settings: %s holds non-JSON %r - using default", key, raw)
        return default


def _set_json(key: str, value: Any) -> None:
    set_setting(_NS + key, json.dumps(value, ensure_ascii=False))


# ---------------------------------------------------------------- sweep basics
def enabled() -> bool:
    return bool(_get_json("enabled", False))


def set_enabled(value: bool) -> None:
    _set_json("enabled", bool(value))


def sources() -> list[str]:
    """Sources to sweep. Falls back to MONITOR_SOURCES, then to fl+kwork.

    The final default is deliberately narrow: an unset ``MONITOR_SOURCES`` means
    "every registered source" to the old sweep code, which drags in the
    Playwright-backed ones nobody asked for.
    """
    configured = _get_json("sources", None)
    if configured:
        return [str(s) for s in configured]
    env = [s.strip() for s in settings.MONITOR_SOURCES.split(",") if s.strip()]
    return env or ["fl", "kwork"]


def set_sources(value: list[str]) -> None:
    _set_json("sources", value)


def interval_minutes() -> int:
    return int(_get_json("interval", settings.MONITOR_INTERVAL_MINUTES))


def set_interval_minutes(value: int) -> None:
    _set_json("interval", max(1, int(value)))


# --------------------------------------------------------------- two contours
# Contour A is "my patch": the categories the operator marked as his. Everything
# else is B. Routing happens before the LLM is called - fl.ru ships the category
# in RSS and kwork ships ``category_id`` in the listing - so it costs nothing.
CONTOUR_A = "a"
CONTOUR_B = "b"

_DEFAULT_THRESHOLDS = {CONTOUR_A: 45, CONTOUR_B: 75}


def contour_categories() -> dict[str, list[str]]:
    """``{source: [category key, ...]}`` - the categories that route to contour A."""
    return _get_json("contour_a", {})


def set_contour_categories(value: dict[str, list[str]]) -> None:
    _set_json("contour_a", value)


def contour_for(source: str, category: Optional[str]) -> str:
    """Contour for one item. A missing/unknown category falls to B, the strict one."""
    if not category:
        return CONTOUR_B
    marked = contour_categories().get(source) or []
    return CONTOUR_A if str(category) in {str(m) for m in marked} else CONTOUR_B


def threshold(contour: str) -> int:
    return int(_get_json(f"threshold_{contour}", _DEFAULT_THRESHOLDS.get(contour, 75)))


def set_threshold(contour: str, value: int) -> None:
    _set_json(f"threshold_{contour}", max(0, min(100, int(value))))


# ------------------------------------------------------------- cheap prefilters
# These run before the LLM and cost nothing but a comparison. They are NOT part
# of the score: budget and competition are not relevance, and folding them into
# one number makes it impossible to say why an item was dropped.
def min_price() -> int:
    """Budget floor in RUB. 0 disables it. Items with no stated budget always pass."""
    return int(_get_json("min_price", 0))


def set_min_price(value: int) -> None:
    _set_json("min_price", max(0, int(value)))


def max_offers() -> int:
    """Drop items that already collected more than this many offers. 0 disables."""
    return int(_get_json("max_offers", 0))


def set_max_offers(value: int) -> None:
    _set_json("max_offers", max(0, int(value)))


# -------------------------------------------------------------------- muting
def mute_until() -> float:
    return float(_get_json("mute_until", 0))


def set_mute_for(seconds: int) -> float:
    """Silence notifications for ``seconds``; returns the unix time it lifts."""
    until = time.time() + max(0, int(seconds))
    _set_json("mute_until", until)
    return until


def is_muted() -> bool:
    return time.time() < mute_until()


# ------------------------------------------------------------------- prompts
def prompt(name: str, default: str = "") -> str:
    value = _get_json(f"prompt:{name}", None)
    return value if isinstance(value, str) and value.strip() else default


def set_prompt(name: str, text: str) -> None:
    """Store a prompt, pushing the previous body onto the undo stack."""
    previous = _get_json(f"prompt:{name}", None)
    if isinstance(previous, str) and previous.strip():
        history = _get_json(f"prompt_hist:{name}", [])
        history.insert(0, previous)
        _set_json(f"prompt_hist:{name}", history[:_PROMPT_HISTORY_MAX])
    _set_json(f"prompt:{name}", text)


def undo_prompt(name: str) -> bool:
    """Restore the previous body. False when there is nothing to go back to."""
    history = _get_json(f"prompt_hist:{name}", [])
    if not history:
        return False
    _set_json(f"prompt:{name}", history[0])
    _set_json(f"prompt_hist:{name}", history[1:])
    return True


def reset_prompt(name: str) -> None:
    """Drop the override so the built-in default from ``prompts.py`` applies again."""
    _set_json(f"prompt:{name}", "")
    _set_json(f"prompt_hist:{name}", [])


# ------------------------------------------------------------------- profile
# Three blocks, kept apart because each implies a different pitch: an existing
# marketplace listing ("here is my ready-made offer"), an own product not listed
# anywhere ("I have a working service"), and general competence.
PROFILE_BLOCKS = ("shopfront", "atomic", "skills")

_PROFILE_TITLES = {
    "shopfront": "MY LISTINGS ON THE MARKETPLACES",
    "atomic": "WHAT MY OWN PRODUCTS CAN DO (not listed on any marketplace yet)",
    "skills": "WHAT I HAVE ACTUALLY WORKED WITH",
}


def profile_block(name: str) -> str:
    value = _get_json(f"profile:{name}", "")
    return value if isinstance(value, str) else ""


def set_profile_block(name: str, text: str) -> None:
    _set_json(f"profile:{name}", text)


def profile_text() -> str:
    """All three blocks joined, ready to paste into a scoring prompt."""
    parts = []
    for block in PROFILE_BLOCKS:
        body = profile_block(block).strip()
        if body:
            parts.append(f"## {_PROFILE_TITLES[block]}\n{body}")
    return "\n\n".join(parts)


# ----------------------------------------------------------------- LLM chain
# Ordered fallback list. The house LLM shares a GPU with the operator's own work,
# so the reason to keep a backup is "the card is busy", not "the machine is off".
def llm_chain() -> list[dict[str, str]]:
    chain = _get_json("llm_chain", [])
    return [c for c in chain if isinstance(c, dict) and c.get("base_url")]


def set_llm_chain(value: list[dict[str, str]]) -> None:
    _set_json("llm_chain", value)


def scoring_llm() -> Optional[str]:
    """Pin scoring to one chain entry by name; None walks the chain in order."""
    value = _get_json("scoring_llm", None)
    return value or None


def set_scoring_llm(name: Optional[str]) -> None:
    _set_json("scoring_llm", name or "")
