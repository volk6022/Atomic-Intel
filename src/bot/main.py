"""Entrypoint for the Atomic Intel admin bot (aiogram v3, long polling).

Admin-only front for two things: the tenant/key control-plane living in
Postgres (issue and revoke api keys, tune quota/concurrency, bind a tenant's
BYO-LLM endpoint) and the order-feed monitor (``/mon``, ``/llm``, ``/prompt``,
``/profile``). See ``src/bot/handlers/`` for the command sets and
``src/bot/middlewares/admin_guard.py`` for the ``ADMIN_TG_IDS`` allowlist gate.

Run via ``uv run python -m src.bot.main`` (see the ``bot`` service in
``docker-compose.yml``).
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot.handlers.content import router as content_router
from src.bot.handlers.llm import router as llm_router
from src.bot.handlers.monitor import router as monitor_router
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
    dispatcher.callback_query.middleware(AdminGuardMiddleware())
    dispatcher.include_router(tenants_router)
    dispatcher.include_router(monitor_router)
    dispatcher.include_router(llm_router)
    # Last on purpose: this router owns the catch-all "next message replaces the
    # prompt" handler, and anything registered after it would never be reached.
    dispatcher.include_router(content_router)

    logger.info("Atomic Intel admin bot starting (long polling)")
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
