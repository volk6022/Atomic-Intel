"""``/llm`` — the scoring LLM fallback chain, edited from the phone.

The house endpoint runs on the operator's own desktop and shares the GPU with
whatever he is doing. It is rarely *down*, but it is regularly *busy*, and a
sweep that lands during a long local job would otherwise queue behind it. Hence a
chain rather than a single endpoint, and hence editing it from Telegram: adding a
spare key at the moment you need it should not mean editing ``.env`` over ssh and
rebuilding an 11 GB image.

Keys are stored in Redis in the clear. Redis is not published outside the compose
network, but the Telegram message carrying the key stays in chat history — so the
add command says to delete it. Postgres alongside the tenants would be tidier and
costs a migration; if that trade ever stops being worth it, this is the note to
revisit.
"""

from __future__ import annotations

import html

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from src.core.config import settings
from src.core.logging import get_logger
from src.infrastructure.external_api import llm_chain
from src.infrastructure.tasks import monitor_settings

logger = get_logger(__name__)
router = Router(name="llm-chain")

HELP = (
    "<b>Цепочка LLM для скоринга</b>\n\n"
    "/llm — показать цепочку\n"
    "/llm add &lt;имя&gt; &lt;base_url&gt; &lt;ключ&gt; &lt;модель&gt; — добавить или заменить\n"
    "/llm rm &lt;имя&gt; — убрать\n"
    "/llm order house,openrouter — задать приоритет\n"
    "/llm test [имя] — простучать сейчас\n"
    "/llm use &lt;имя|auto&gt; — закрепить скоринг за одним звеном\n\n"
    "Звено <code>house</code> подставляется само и всегда берёт текущий адрес "
    "из /sethousellm — туннель меняет URL при каждом перезапуске."
)


def _is_superadmin(message: Message) -> bool:
    uid = message.from_user.id if message.from_user else None
    return bool(settings.SUPERADMIN_TG_ID and uid == settings.SUPERADMIN_TG_ID)


def _render_chain() -> str:
    entries = llm_chain.chain_entries()
    if not entries:
        return "цепочка пуста"
    pinned = monitor_settings.scoring_llm()
    lines = []
    for i, entry in enumerate(entries, 1):
        name = entry.get("name") or "?"
        mark = " ← закреплено" if pinned == name else ""
        lines.append(
            f"{i}. <b>{html.escape(name)}</b>{mark}\n"
            f"    {html.escape(entry.get('base_url') or '')}\n"
            f"    модель: {html.escape(entry.get('model') or '-')} · "
            f"ключ: {html.escape(llm_chain.mask_key(entry.get('api_key')))}"
        )
    return "\n".join(lines)


@router.message(Command("llm"))
async def cmd_llm(message: Message, command: CommandObject) -> None:
    if not _is_superadmin(message):
        await message.answer("Цепочкой LLM управляет только супер-админ.")
        return

    args = (command.args or "").split()
    if not args:
        await message.answer(_render_chain() + "\n\n" + HELP)
        return

    action, rest = args[0].lower(), args[1:]

    if action == "add":
        if len(rest) < 4:
            await message.answer("Формат: /llm add &lt;имя&gt; &lt;base_url&gt; &lt;ключ&gt; &lt;модель&gt;")
            return
        name, base_url, api_key, model = rest[0], rest[1], rest[2], " ".join(rest[3:])
        chain = [c for c in monitor_settings.llm_chain() if c.get("name") != name]
        chain.append({"name": name, "base_url": base_url, "api_key": api_key, "model": model})
        monitor_settings.set_llm_chain(chain)
        await message.answer(
            f"добавил <b>{html.escape(name)}</b>.\n\n"
            "<b>Удали это сообщение</b> — ключ остаётся в истории чата."
        )

    elif action == "rm" and rest:
        name = rest[0]
        chain = [c for c in monitor_settings.llm_chain() if c.get("name") != name]
        monitor_settings.set_llm_chain(chain)
        await message.answer(f"убрал {html.escape(name)}\n\n" + _render_chain())

    elif action == "order" and rest:
        wanted = [n.strip() for n in " ".join(rest).replace(" ", ",").split(",") if n.strip()]
        stored = {c.get("name"): c for c in monitor_settings.llm_chain()}
        ordered = [stored[n] for n in wanted if n in stored]
        ordered += [c for n, c in stored.items() if n not in wanted]
        monitor_settings.set_llm_chain(ordered)
        await message.answer(_render_chain())

    elif action == "test":
        target = rest[0] if rest else None
        await message.answer("стучусь…")
        results = await llm_chain.probe_chain(target)
        if not results:
            await message.answer("нечего проверять")
            return
        lines = [
            f"{'живо' if r['ok'] else 'молчит'} — <b>{html.escape(r['name'])}</b> "
            f"({r['ms']} мс)\n    {html.escape(r['base_url'] or '')}"
            for r in results
        ]
        await message.answer("\n".join(lines))

    elif action == "use" and rest:
        name = rest[0]
        if name == "auto":
            monitor_settings.set_scoring_llm(None)
            await message.answer("скоринг снова идёт по цепочке сверху вниз")
            return
        known = {e.get("name") for e in llm_chain.chain_entries()}
        if name not in known:
            await message.answer(f"нет такого звена: {html.escape(name)}")
            return
        monitor_settings.set_scoring_llm(name)
        await message.answer(f"скоринг закреплён за {html.escape(name)}")

    else:
        await message.answer(HELP)
