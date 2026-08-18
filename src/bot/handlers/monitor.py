"""``/mon`` — running the order-feed monitor from the phone.

Every knob the operator touches day to day lives here, because the alternative is
editing ``.env`` and rebuilding an image to change a number.

Two commands carry more weight than the rest. ``/mon last`` shows the items that
were *dropped* along with the reason, which is what makes a badly-set threshold
visible instead of merely suspected. ``/mon cats`` lists the rubrics the sweeps
have actually seen and toggles them into contour A — the catalogue builds itself,
so nobody has to keep a copy of two marketplaces' rubric trees in sync.
"""

from __future__ import annotations

import html
import re
import time
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.actions.monitoring import notify
from src.core.logging import get_logger
from src.infrastructure.tasks import monitor_settings, monitor_store

logger = get_logger(__name__)
router = Router(name="monitor")

CB_CAT_TOGGLE = "moncat"

HELP = (
    "<b>Монитор лент</b>\n\n"
    "/mon — статус\n"
    "/mon on | off — включить / выключить обход\n"
    "/mon run — прогнать прямо сейчас\n"
    "/mon sources fl,kwork — какие площадки опрашивать\n"
    "/mon every 15 — интервал в минутах\n"
    "/mon cats — кнопки категорий: отмеченные = контур A\n"
    "/mon threshold a 45 — порог по контуру (a или b)\n"
    "/mon minprice 8000 — не беспокоить дешевле\n"
    "/mon maxoffers 10 — не беспокоить, если откликов больше\n"
    "/mon last [N] — последние карточки, включая отсеянные и причину\n"
    "/mon stats — счётчики за сутки\n"
    "/mon mute 3h — тишина на срок\n"
)

_DURATION_RE = re.compile(r"^(\d+)\s*([mhd])?$", re.I)
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


def _parse_duration(value: str) -> Optional[int]:
    m = _DURATION_RE.match(value.strip())
    if not m:
        return None
    return int(m.group(1)) * _UNIT_SECONDS.get((m.group(2) or "m").lower(), 60)


def _status_text() -> str:
    marked = monitor_settings.contour_categories()
    marked_total = sum(len(v) for v in marked.values())
    lines = [
        f"обход: <b>{'включён' if monitor_settings.enabled() else 'выключен'}</b>",
        f"площадки: {', '.join(monitor_settings.sources())}",
        f"интервал: {monitor_settings.interval_minutes()} мин",
        f"порог A: {monitor_settings.threshold(monitor_settings.CONTOUR_A)} · "
        f"порог B: {monitor_settings.threshold(monitor_settings.CONTOUR_B)}",
        f"категорий в контуре A: {marked_total}",
    ]
    floor, cap = monitor_settings.min_price(), monitor_settings.max_offers()
    lines.append(f"минимальный бюджет: {floor or 'не задан'}")
    lines.append(f"потолок откликов: {cap or 'не задан'}")
    if monitor_settings.is_muted():
        left = int(monitor_settings.mute_until() - time.time())
        lines.append(f"<b>тишина ещё {left // 60} мин</b>")
    profile = monitor_settings.profile_text()
    lines.append(f"профиль: {len(profile)} символов" if profile else "<b>профиль пуст</b> — /profile")
    return "\n".join(lines)


def _cats_keyboard() -> Optional[InlineKeyboardMarkup]:
    marked = monitor_settings.contour_categories()
    rows: list[list[InlineKeyboardButton]] = []
    for source in monitor_settings.sources():
        known = monitor_store.get_categories(source)
        if not known:
            continue
        picked = {str(c) for c in marked.get(source, [])}
        for category in known[:40]:
            flag = "✓ " if category in picked else ""
            label = category if len(category) <= 28 else category[:27] + "…"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{flag}[{source}] {label}",
                        callback_data=f"{CB_CAT_TOGGLE}:{source}:{category}"[:64],
                    )
                ]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _format_result(entry: dict) -> str:
    when = time.strftime("%H:%M", time.localtime(entry.get("ts", 0)))
    title = html.escape((entry.get("title") or "")[:70])
    if entry.get("stage") == "scored":
        score, threshold = entry.get("score", 0), entry.get("threshold", 0)
        mark = "→" if score >= threshold else "×"
        tail = f"{score}/{threshold} {entry.get('match_type', '')}"
        if entry.get("notified"):
            tail += " отправлено"
    else:
        mark = "×"
        tail = f"{entry.get('stage', '')}: {entry.get('reason', '')}"[:70]
    return f"{when} {mark} <a href=\"{entry.get('url', '')}\">{title}</a>\n    {html.escape(tail)}"


@router.message(Command("mon"))
async def cmd_mon(message: Message, command: CommandObject) -> None:
    args = (command.args or "").split()
    if not args:
        await message.answer(_status_text() + "\n\n" + HELP, disable_web_page_preview=True)
        return

    action, rest = args[0].lower(), args[1:]

    if action in ("on", "off"):
        monitor_settings.set_enabled(action == "on")
        await message.answer(f"обход {'включён' if action == 'on' else 'выключен'}")

    elif action == "run":
        await message.answer("гоняю обход…")
        from src.infrastructure.queue.monitor_worker import run_monitor_sweep

        try:
            result = await run_monitor_sweep()
        except Exception as exc:  # noqa: BLE001 - report, do not crash the bot
            logger.exception("manual sweep failed")
            await message.answer(f"обход упал: <code>{html.escape(str(exc)[:300])}</code>")
            return
        parts = [
            f"{src}: собрано {d.get('collected', 0)}, новых {d.get('new', 0)}, "
            f"оценено {d.get('scored', 0)}, отправлено {d.get('sent', 0)}"
            if d.get("ok") else f"{src}: ошибка — {d.get('error', '')[:120]}"
            for src, d in result.get("sources", {}).items()
        ]
        parts.append(f"LLM: {result.get('llm') or 'нет живой'}")
        await message.answer("\n".join(parts) or "нечего собирать")

    elif action == "sources" and rest:
        value = [s.strip() for s in " ".join(rest).replace(" ", ",").split(",") if s.strip()]
        monitor_settings.set_sources(value)
        await message.answer(f"площадки: {', '.join(value)}")

    elif action == "every" and rest:
        monitor_settings.set_interval_minutes(int(rest[0]))
        await message.answer(
            f"интервал: {rest[0]} мин.\n"
            "Расписание читается планировщиком при старте — новая частота "
            "заработает после перезапуска сервиса <code>scheduler</code>."
        )

    elif action == "cats":
        keyboard = _cats_keyboard()
        if keyboard is None:
            await message.answer(
                "категорий пока не видел — прогони /mon run, они соберутся сами"
            )
            return
        await message.answer(
            "Отмеченные категории идут в контур A (низкий порог). Нажми, чтобы переключить.",
            reply_markup=keyboard,
        )

    elif action == "threshold" and len(rest) >= 2:
        contour = rest[0].lower()
        if contour not in (monitor_settings.CONTOUR_A, monitor_settings.CONTOUR_B):
            await message.answer("контур должен быть a или b")
            return
        monitor_settings.set_threshold(contour, int(rest[1]))
        await message.answer(f"порог {contour.upper()}: {monitor_settings.threshold(contour)}")

    elif action == "minprice" and rest:
        monitor_settings.set_min_price(int(rest[0]))
        await message.answer(f"минимальный бюджет: {monitor_settings.min_price()}")

    elif action == "maxoffers" and rest:
        monitor_settings.set_max_offers(int(rest[0]))
        await message.answer(f"потолок откликов: {monitor_settings.max_offers()}")

    elif action == "last":
        limit = int(rest[0]) if rest and rest[0].isdigit() else 10
        entries = monitor_store.get_results(limit)
        if not entries:
            await message.answer("пока пусто")
            return
        await message.answer(
            "\n".join(_format_result(e) for e in entries), disable_web_page_preview=True
        )

    elif action == "stats":
        stats = monitor_store.get_stats()
        if not stats:
            await message.answer("за сегодня счётчиков нет")
            return
        order = ["collected", "new", "scored", "sent", "below_threshold"]
        rows = [f"{k}: {stats[k]}" for k in order if k in stats]
        rows += [f"{k}: {v}" for k, v in sorted(stats.items()) if k not in order]
        await message.answer("\n".join(rows))

    elif action == "mute" and rest:
        seconds = _parse_duration(rest[0])
        if seconds is None:
            await message.answer("формат: /mon mute 3h (m, h, d)")
            return
        until = monitor_settings.set_mute_for(seconds)
        await message.answer(f"тишина до {time.strftime('%H:%M', time.localtime(until))}")

    else:
        await message.answer(HELP)


@router.callback_query(F.data.startswith(f"{CB_CAT_TOGGLE}:"))
async def on_category_toggle(callback: CallbackQuery) -> None:
    _, source, category = callback.data.split(":", 2)
    marked = monitor_settings.contour_categories()
    picked = [str(c) for c in marked.get(source, [])]
    if category in picked:
        picked.remove(category)
        note = "убрал из контура A"
    else:
        picked.append(category)
        note = "добавил в контур A"
    marked[source] = picked
    monitor_settings.set_contour_categories(marked)

    await callback.answer(note)
    try:
        await callback.message.edit_reply_markup(reply_markup=_cats_keyboard())
    except Exception:  # noqa: BLE001 - Telegram rejects a no-op edit; harmless
        pass


@router.callback_query(F.data.startswith(f"{notify.CB_TOOK}:"))
async def on_took(callback: CallbackQuery) -> None:
    await _record_verdict(callback, "took", "отметил: взял")


@router.callback_query(F.data.startswith(f"{notify.CB_SKIP}:"))
async def on_skip(callback: CallbackQuery) -> None:
    await _record_verdict(callback, "skip", "отметил: мимо")


async def _record_verdict(callback: CallbackQuery, verdict: str, note: str) -> None:
    try:
        _, _, source, item_id = callback.data.split(":", 3)
    except ValueError:
        await callback.answer("не разобрал кнопку")
        return
    monitor_store.record_feedback(source, item_id, verdict)
    monitor_store.bump_stat(f"feedback_{verdict}")
    await callback.answer(note)


@router.callback_query(F.data.startswith(f"{notify.CB_REDRAFT}:"))
async def on_redraft(callback: CallbackQuery) -> None:
    """Regenerate the reply draft — cheaper than editing a bad one by hand."""
    try:
        _, _, source, item_id = callback.data.split(":", 3)
    except ValueError:
        await callback.answer("не разобрал кнопку")
        return

    entry = monitor_store.find_result(source, item_id)
    if not entry or not entry.get("item"):
        await callback.answer("карточки уже нет в памяти")
        return

    await callback.answer("пишу другой вариант…")

    from src.actions.monitoring import scoring
    from src.infrastructure.external_api import llm_chain

    client, _name = await llm_chain.get_scoring_client()
    if client is None:
        await callback.message.answer("все LLM недоступны — попробуй позже")
        return

    verdict = {
        "score": entry.get("score", 0),
        "match_type": entry.get("match_type", ""),
        "matched_offer": entry.get("matched_offer", ""),
        "contour": entry.get("contour", "?"),
        "reason": entry.get("reason", ""),
        "have": [],
    }
    draft = await scoring.draft_reply(client, entry["item"], verdict)
    if not draft:
        await callback.message.answer("не получилось — попробуй ещё раз")
        return
    await callback.message.answer(f"<pre>{html.escape(draft)}</pre>")
