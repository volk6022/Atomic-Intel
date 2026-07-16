"""Admin commands: issue/revoke keys, set quota/concurrency, bind BYO-LLM,
show usage. All state lives in the same Postgres the API/worker read from
(``src.infrastructure.db``).
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from src.core.config import settings
from src.core.logging import get_logger
from src.infrastructure.db.keys import generate_raw_key, hash_api_key
from src.infrastructure.db.session import session_scope
from src.infrastructure.db.tenant_repository import TenantNotFoundError, TenantRepository
from src.infrastructure.tasks.research_store import get_concurrent_task_count

logger = get_logger(__name__)
router = Router(name="tenants")

HELP_TEXT = (
    "<b>Atomic Intel control-plane</b>\n\n"
    "/newkey &lt;name&gt; [quota_per_hour] [concurrent_research] — create a "
    "tenant (if new) + issue a key\n"
    "/revoke &lt;name&gt; — deactivate all keys for a tenant\n"
    "/setquota &lt;name&gt; &lt;quota_per_hour&gt;\n"
    "/setconcurrency &lt;name&gt; &lt;concurrent_research&gt;\n"
    "/setllm &lt;name&gt; &lt;base_url&gt; &lt;api_key&gt; &lt;model&gt; — bind BYO-LLM\n"
    "/clearllm &lt;name&gt; — fall back to the global orchestration LLM\n"
    "/usage &lt;name&gt; — quota, concurrency, running tasks, BYO-LLM status\n"
    "/listtenants — list all tenants\n"
)


@router.message(Command("start", "help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("newkey"))
async def cmd_newkey(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        await message.answer("Usage: /newkey <name> [quota_per_hour] [concurrent_research]")
        return

    name = args[0]
    try:
        quota = int(args[1]) if len(args) > 1 else settings.DEFAULT_TENANT_QUOTA_PER_HOUR
        concurrent = (
            int(args[2]) if len(args) > 2 else settings.DEFAULT_TENANT_CONCURRENT_RESEARCH
        )
    except ValueError:
        await message.answer("quota_per_hour and concurrent_research must be integers")
        return

    raw_key = generate_raw_key()
    async with session_scope() as session:
        repo = TenantRepository(session)
        try:
            tenant = await repo.get_tenant(name)
        except TenantNotFoundError:
            tenant = await repo.create_tenant(
                name, quota_per_hour=quota, concurrent_research=concurrent
            )
        await repo.issue_key(tenant.name, hash_api_key(raw_key))

    await message.answer(
        f"Tenant <code>{name}</code> ready — quota={quota}/h, concurrent={concurrent}.\n"
        f"New key (shown once, store it now):\n<code>{raw_key}</code>"
    )


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.answer("Usage: /revoke <name>")
        return
    async with session_scope() as session:
        repo = TenantRepository(session)
        try:
            count = await repo.revoke_all_keys_for_tenant(name)
        except TenantNotFoundError:
            await message.answer(f"No such tenant: {name}")
            return
    await message.answer(f"Revoked {count} key(s) for {name}.")


@router.message(Command("setquota"))
async def cmd_setquota(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if len(args) != 2 or not args[1].isdigit():
        await message.answer("Usage: /setquota <name> <quota_per_hour>")
        return
    name, quota = args[0], int(args[1])
    async with session_scope() as session:
        try:
            await TenantRepository(session).set_quota(name, quota)
        except TenantNotFoundError:
            await message.answer(f"No such tenant: {name}")
            return
    await message.answer(f"{name}: quota_per_hour={quota}")


@router.message(Command("setconcurrency"))
async def cmd_setconcurrency(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if len(args) != 2 or not args[1].isdigit():
        await message.answer("Usage: /setconcurrency <name> <concurrent_research>")
        return
    name, concurrent = args[0], int(args[1])
    async with session_scope() as session:
        try:
            await TenantRepository(session).set_concurrent_research(name, concurrent)
        except TenantNotFoundError:
            await message.answer(f"No such tenant: {name}")
            return
    await message.answer(f"{name}: concurrent_research={concurrent}")


@router.message(Command("setllm"))
async def cmd_setllm(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split(maxsplit=3)
    if len(args) != 4:
        await message.answer("Usage: /setllm <name> <base_url> <api_key> <model>")
        return
    name, base_url, api_key, model = args
    config = {"base_url": base_url, "api_key": api_key, "model": model}
    async with session_scope() as session:
        try:
            await TenantRepository(session).set_llm_provider_config(name, config)
        except TenantNotFoundError:
            await message.answer(f"No such tenant: {name}")
            return
    await message.answer(f"{name}: BYO-LLM bound to {base_url} ({model})")


@router.message(Command("clearllm"))
async def cmd_clearllm(message: Message, command: CommandObject) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.answer("Usage: /clearllm <name>")
        return
    async with session_scope() as session:
        try:
            await TenantRepository(session).set_llm_provider_config(name, None)
        except TenantNotFoundError:
            await message.answer(f"No such tenant: {name}")
            return
    await message.answer(f"{name}: BYO-LLM cleared — falling back to the global orchestration LLM.")


@router.message(Command("usage"))
async def cmd_usage(message: Message, command: CommandObject) -> None:
    name = (command.args or "").strip()
    if not name:
        await message.answer("Usage: /usage <name>")
        return

    async with session_scope() as session:
        try:
            tenant = await TenantRepository(session).get_tenant(name)
        except TenantNotFoundError:
            await message.answer(f"No such tenant: {name}")
            return
        tenant_id = str(tenant.id)
        active = tenant.active
        quota = tenant.quota_per_hour
        concurrent_cap = tenant.concurrent_research
        has_llm = tenant.llm_provider_config is not None

    running = await get_concurrent_task_count(tenant_id)
    await message.answer(
        f"<b>{name}</b>\n"
        f"active: {active}\n"
        f"quota_per_hour: {quota}\n"
        f"concurrent_research: {running}/{concurrent_cap} running\n"
        f"BYO-LLM: {'bound' if has_llm else 'not set (global fallback)'}"
    )


@router.message(Command("listtenants"))
async def cmd_listtenants(message: Message) -> None:
    async with session_scope() as session:
        tenants = await TenantRepository(session).list_tenants()
    if not tenants:
        await message.answer("No tenants yet.")
        return
    lines = [
        f"- {t.name} (active={t.active}, quota={t.quota_per_hour}/h, "
        f"concurrent={t.concurrent_research}, byo_llm={t.llm_provider_config is not None})"
        for t in tenants
    ]
    await message.answer("\n".join(lines))
