"""Ordered LLM fallback chain for the monitor, managed from the Telegram bot.

The house endpoint is a llama-server on the operator's own desktop behind a
tunnel. It is up most of the time, but the GPU is shared with whatever he is
working on, so a sweep can arrive while the card is busy. That - not "the machine
is off" - is why scoring needs a backup endpoint, and why the operator has to be
able to add one from his phone without touching ``.env`` or rebuilding an image.

The chain lives in Redis (``monitor_settings.llm_chain``) as an ordered list of
``{name, base_url, api_key, model}``. :func:`get_scoring_client` walks it top to
bottom, probing each entry, and hands back the first one that answers. Probes are
cached by :func:`check_llm_reachable`, so a sweep over fifty items does not
re-ping the endpoint fifty times.

When the chain is empty the house endpoint is synthesised from settings, so
scoring works on a fresh install before anything has been configured.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from src.core.config import settings
from src.core.logging import get_logger
from src.infrastructure.external_api.facade import LLMFacade
from src.infrastructure.queue.llm_health import check_llm_reachable
from src.infrastructure.tasks import monitor_settings

logger = get_logger(__name__)

HOUSE = "house"


def _house_entry() -> dict[str, str]:
    """The implicit first link: whatever ``/sethousellm`` currently points at."""
    from src.infrastructure.tasks.research_store import house_llm_base_url

    return {
        "name": HOUSE,
        "base_url": house_llm_base_url(),
        "api_key": settings.ORCHESTRATION_API_KEY,
        "model": settings.ORCHESTRATION_MODEL_NAME,
    }


def chain_entries() -> list[dict[str, str]]:
    """The configured chain, with the house endpoint prepended when absent.

    The house entry is refreshed from ``settings:house_llm_base_url`` on every
    call rather than copied into the stored chain: the tunnel URL changes on
    every restart, and a stale copy would send scoring at a dead address.
    """
    stored = monitor_settings.llm_chain()
    entries: list[dict[str, str]] = []
    seen_house = False

    for entry in stored:
        if entry.get("name") == HOUSE:
            seen_house = True
            merged = dict(entry)
            merged["base_url"] = _house_entry()["base_url"]
            entries.append(merged)
        else:
            entries.append(dict(entry))

    if not seen_house:
        entries.insert(0, _house_entry())
    return entries


def _build(entry: dict[str, str]) -> LLMFacade:
    from src.infrastructure.external_api.clients.openai_client import (
        OpenAICompatibleClient,
    )

    return OpenAICompatibleClient(
        base_url=entry["base_url"],
        api_key=entry.get("api_key") or "none",
        model_name=entry.get("model") or settings.ORCHESTRATION_MODEL_NAME,
    )


def _as_provider_config(entry: dict[str, str]) -> dict[str, Any]:
    return {
        "base_url": entry.get("base_url"),
        "api_key": entry.get("api_key"),
        "model": entry.get("model"),
    }


async def get_scoring_client() -> tuple[Optional[LLMFacade], Optional[str]]:
    """First reachable client in the chain, as ``(client, name)``.

    Returns ``(None, None)`` when every link is down. Callers must treat that as
    "postpone", not "drop": items that could not be scored stay unseen so the
    next sweep picks them up again.
    """
    pinned = monitor_settings.scoring_llm()
    entries = chain_entries()
    if pinned:
        entries = [e for e in entries if e.get("name") == pinned] or entries

    for entry in entries:
        if await check_llm_reachable(_as_provider_config(entry)):
            return _build(entry), entry.get("name") or entry["base_url"]
        logger.info("llm_chain: %s is down, trying the next link", entry.get("name"))

    logger.warning("llm_chain: every endpoint is down (%d checked)", len(entries))
    return None, None


async def probe_chain(name: Optional[str] = None) -> list[dict[str, Any]]:
    """Ping every link (or just ``name``) and report status. Used by ``/llm test``."""
    results = []
    for entry in chain_entries():
        if name and entry.get("name") != name:
            continue
        started = time.monotonic()
        ok = await check_llm_reachable(_as_provider_config(entry), force=True)
        results.append(
            {
                "name": entry.get("name") or "?",
                "base_url": entry.get("base_url"),
                "model": entry.get("model"),
                "ok": ok,
                "ms": int((time.monotonic() - started) * 1000),
            }
        )
    return results


def mask_key(value: Optional[str]) -> str:
    """Show enough of an api key to recognise it, never enough to use it."""
    if not value:
        return "-"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"
