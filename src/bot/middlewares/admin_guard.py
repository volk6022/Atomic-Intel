"""Admin-only allowlist for the TG control-plane bot.

The bot issues/revokes api keys and binds BYO-LLM endpoints, so every update
is gated on the sender's Telegram user id being in ``ADMIN_TG_IDS`` (CSV env
var). Fails closed: an unset/empty allowlist admits nobody.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)


def _admin_ids() -> set[int]:
    ids: set[int] = set()
    for raw in settings.ADMIN_TG_IDS.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ids.add(int(raw))
        except ValueError:
            logger.warning("ADMIN_TG_IDS contains a non-numeric entry: %r", raw)
    return ids


class AdminGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        admin_ids = _admin_ids()
        if not admin_ids:
            logger.warning("ADMIN_TG_IDS is empty — rejecting all bot commands")
            return None

        user = event.from_user if isinstance(event, Message) else None
        if user is None or user.id not in admin_ids:
            logger.warning(
                "Rejected bot update from non-admin tg id=%s",
                user.id if user else "unknown",
            )
            return None

        return await handler(event, data)
