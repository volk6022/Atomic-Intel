"""Entrypoint for the Atomic Intel admin bot (aiogram v3, long polling).

Admin-only front for the tenant/key control-plane living in Postgres — issue
and revoke api keys, tune per-tenant quota/concurrency, bind or clear a
tenant's BYO-LLM endpoint, and check usage. See ``src/bot/handlers/tenants.py``
for the command set and ``src/bot/middlewares/admin_guard.py`` for the
``ADMIN_TG_IDS`` allowlist gate.

Run via ``uv run python -m src.bot.main`` (see the ``bot`` service in
``docker-compose.yml``).
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot.handlers.tenants import router as tenants_router
from src.bot.middlewares.admin_guard import AdminGuardMiddleware
from src.core.config import settings
from src.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


async def main() -> None:
    setup_logging()
    if not settings.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set — cannot start the admin bot")
    if not settings.ADMIN_TG_IDS:
        logger.warning(
            "ADMIN_TG_IDS is not set — the bot will reject every command until configured"
        )

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.message.middleware(AdminGuardMiddleware())
    dispatcher.include_router(tenants_router)

    logger.info("Atomic Intel admin bot starting (long polling)")
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
