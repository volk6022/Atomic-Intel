"""``/prompt`` and ``/profile`` — the text the scoring model actually reads.

A prompt does not fit on a command line, so both commands work in two steps: the
command names the target and shows what is stored now, and the **next** message
becomes the new body. That is also why every write keeps the previous version —
one ``undo`` is worth more than a full history nobody will read.

The pending-target map is process-local on purpose. There is exactly one bot
process and one operator; putting this in Redis would buy nothing but a second
place for it to go stale. If the bot restarts mid-edit, the operator retypes one
command.
"""

from __future__ import annotations

import html
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from src.actions.monitoring import prompts as prompt_defaults
from src.core.logging import get_logger
from src.infrastructure.tasks import monitor_settings

logger = get_logger(__name__)
router = Router(name="content")

# user id -> ("prompt", name) | ("profile", block)
_pending: dict[int, tuple[str, str]] = {}

PROMPT_HELP = (
    "<b>Промпты</b>\n\n"
    "/prompt a — скоринг в моих категориях (низкий порог)\n"
    "/prompt b — скоринг во всех остальных\n"
    "/prompt draft — черновик отклика\n\n"
    "Команда показывает текущий текст и ждёт следующего сообщения — оно "
    "заменит его целиком.\n"
    "/prompt &lt;имя&gt; reset — вернуть встроенный\n"
    "/prompt &lt;имя&gt; undo — откатить на предыдущий\n"
)

PROFILE_HELP = (
    "<b>Профиль для скоринга</b>\n\n"
    "/profile — что сейчас лежит\n"
    "/profile shopfront — мои услуги, уже выставленные на биржах\n"
    "/profile atomic — что умеют мои продукты (на биржах их нет)\n"
    "/profile skills — с чем я реально работал\n\n"
    "Три блока разделены не для красоты: каждый даёт свой сценарий отклика, "
    "и модель должна их различать."
)


def _preview(text: str, limit: int = 700) -> str:
    body = text.strip() or "(пусто)"
    if len(body) > limit:
        body = body[:limit] + "\n[…]"
    return f"<pre>{html.escape(body)}</pre>"


@router.message(Command("prompt"))
async def cmd_prompt(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        await message.answer(PROMPT_HELP)
        return

    name = args[0].lower()
    if name not in prompt_defaults.PROMPT_NAMES:
        await message.answer(
            f"имена промптов: {', '.join(prompt_defaults.PROMPT_NAMES)}"
        )
        return

    action = args[1].lower() if len(args) > 1 else ""
    if action == "reset":
        monitor_settings.reset_prompt(name)
        await message.answer(f"вернул встроенный промпт {name}")
        return
    if action == "undo":
        if monitor_settings.undo_prompt(name):
            await message.answer(f"откатил промпт {name}")
        else:
            await message.answer("откатывать не на что")
        return

    current = monitor_settings.prompt(name, prompt_defaults.default_prompt(name))
    overridden = bool(monitor_settings.prompt(name))
    _pending[message.from_user.id] = ("prompt", name)
    await message.answer(
        f"Промпт <b>{name}</b> ({'свой' if overridden else 'встроенный'}):\n"
        f"{_preview(current)}\n"
        "Следующее сообщение заменит его целиком. Любая команда отменяет."
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        lines = [PROFILE_HELP, ""]
        for block in monitor_settings.PROFILE_BLOCKS:
            body = monitor_settings.profile_block(block)
            lines.append(f"<b>{block}</b>: {len(body)} символов" if body else f"<b>{block}</b>: пусто")
        await message.answer("\n".join(lines))
        return

    block = args[0].lower()
    if block not in monitor_settings.PROFILE_BLOCKS:
        await message.answer(f"блоки: {', '.join(monitor_settings.PROFILE_BLOCKS)}")
        return

    if len(args) > 1 and args[1].lower() == "clear":
        monitor_settings.set_profile_block(block, "")
        await message.answer(f"очистил блок {block}")
        return

    _pending[message.from_user.id] = ("profile", block)
    await message.answer(
        f"Блок <b>{block}</b>:\n{_preview(monitor_settings.profile_block(block))}\n"
        "Следующее сообщение заменит его целиком. Любая команда отменяет."
    )


@router.message(F.text, ~F.text.startswith("/"))
async def on_pending_text(message: Message) -> None:
    """Consume the follow-up message for whichever target is pending."""
    target: Optional[tuple[str, str]] = _pending.pop(
        message.from_user.id if message.from_user else 0, None
    )
    if not target:
        return

    kind, name = target
    body = message.text or ""
    if kind == "prompt":
        monitor_settings.set_prompt(name, body)
        await message.answer(
            f"промпт <b>{name}</b> обновлён ({len(body)} символов). "
            f"/prompt {name} undo — откатить."
        )
    else:
        monitor_settings.set_profile_block(name, body)
        await message.answer(f"блок <b>{name}</b> обновлён ({len(body)} символов)")
