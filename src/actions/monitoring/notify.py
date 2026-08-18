"""Turning a scored posting into the Telegram message the operator actually reads.

The shape is fixed by how it gets used: link first (so the posting is one tap
away), then the title and the brief **verbatim** - not summarised, because a
summary is one more thing that can be wrong and the point is to decide without
opening the site. The draft reply goes in a code block so a single tap copies it
with no Telegram formatting glued on.

"Skip" is not decoration. It is the only labelling that will ever exist here, and
after a couple of weeks it says which ``match_type`` is over-reporting - which is
what makes the threshold tunable without rewriting prompts by hand.
"""

from __future__ import annotations

import html
from typing import Any, Optional

from src.core.logging import get_logger
from src.infrastructure.tasks import monitor_settings

logger = get_logger(__name__)

# Telegram hard-caps a message at 4096 characters. The brief is the one part that
# can run long, so it is the part that gets trimmed - never the draft, which is
# the whole reason the notification is worth sending.
TG_LIMIT = 4096
_BRIEF_BUDGET = 2200

CB_TOOK = "mon:took"
CB_SKIP = "mon:skip"
CB_REDRAFT = "mon:redraft"

_MATCH_LABELS = {
    "listing": "витрина",
    "product": "свой продукт",
    "skill": "опыт",
    "adjacent": "смежное",
    "none": "мимо",
}


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _money(value: Any) -> str:
    from src.actions.monitoring.scoring import parse_amount

    amount = parse_amount(value)
    if amount is None:
        return "бюджет не указан"
    return f"{amount:,}".replace(",", " ") + " ₽"


def _summary_line(item: dict, score: dict[str, Any]) -> str:
    from src.actions.monitoring.scoring import offers_count

    parts = [f"score {score.get('score', 0)}"]

    label = _MATCH_LABELS.get(score.get("match_type", ""), score.get("match_type", ""))
    matched = (score.get("matched_offer") or "").strip()
    parts.append(f"{label} «{matched}»" if matched else label)

    count = offers_count(item)
    if count is not None:
        parts.append(f"{count} {_plural(count, 'отклик', 'отклика', 'откликов')}")

    parts.append(_money(item.get("amount")))
    parts.append(f"контур {score.get('contour', '?').upper()}")
    return " · ".join(parts)


def _price_anchor(item: dict) -> str:
    """What competitors actually asked, when fl.ru told us.

    Nowhere in the site's own interface is this visible; it is the single most
    useful number for deciding what to quote.
    """
    stats = (item.get("offers_stats") or (item.get("extra") or {}).get("offers_stats") or {})
    low, high = stats.get("minCost"), stats.get("maxCost")
    if not low and not high:
        return ""
    with_files = stats.get("offersWithAttachCount")
    tail = f", из них с примерами работ: {with_files}" if with_files else ""
    return f"Конкуренты просят: {low}–{high} ₽{tail}"


def format_notification(item: dict, score: dict[str, Any], draft: str = "") -> str:
    """Render the message body (HTML parse mode)."""
    extra = item.get("extra") or {}
    brief = (item.get("description") or extra.get("desc") or "").strip()
    if len(brief) > _BRIEF_BUDGET:
        brief = brief[:_BRIEF_BUDGET].rsplit(" ", 1)[0] + " […]"

    blocks = [
        html.escape(item.get("url", "")),
        f"<b>{html.escape(item.get('title', ''))}</b>",
        html.escape(brief),
        _summary_line(item, score),
    ]

    anchor = _price_anchor(item)
    if anchor:
        blocks.append(anchor)

    reason = (score.get("reason") or "").strip()
    if reason:
        blocks.append(f"<i>{html.escape(reason)}</i>")

    gap = [g for g in (score.get("gap") or []) if g]
    if gap:
        blocks.append("Чего у меня нет: " + html.escape(", ".join(gap)))

    if draft:
        blocks.append(f"<pre>{html.escape(draft)}</pre>")

    text = "\n\n".join(b for b in blocks if b)
    if len(text) > TG_LIMIT:
        text = text[: TG_LIMIT - 20].rsplit("\n", 1)[0] + "\n\n[…]"
    return text


def build_keyboard(item: dict):
    """Взял / Мимо / Ещё вариант, or ``None`` when aiogram is unavailable."""
    try:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    except ImportError:  # the worker image has aiogram, unit tests may not
        return None

    ref = f"{item.get('source', '')}:{item.get('id', '')}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Взял", callback_data=f"{CB_TOOK}:{ref}"),
                InlineKeyboardButton(text="Мимо", callback_data=f"{CB_SKIP}:{ref}"),
                InlineKeyboardButton(text="Ещё вариант", callback_data=f"{CB_REDRAFT}:{ref}"),
            ]
        ]
    )


async def send_notification(
    item: dict, score: dict[str, Any], draft: str = "", *, chat_id: Optional[int] = None
) -> bool:
    """Send one notification from whatever process is running the sweep.

    The worker opens its own short-lived ``Bot`` rather than talking to the bot
    process: ``BOT_TOKEN`` is already in its environment (compose hands all three
    services the same ``env_file``), and a queue between them would buy nothing.
    """
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from src.core.config import settings

    target = chat_id or settings.SUPERADMIN_TG_ID
    if not settings.BOT_TOKEN or not target:
        logger.warning("notify: BOT_TOKEN or SUPERADMIN_TG_ID missing - not sending")
        return False

    if monitor_settings.is_muted():
        logger.info("notify: muted, dropping notification for %s", item.get("id"))
        return False

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(
            chat_id=target,
            text=format_notification(item, score, draft),
            reply_markup=build_keyboard(item),
            disable_web_page_preview=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - a failed send must not abort the sweep
        logger.error("notify: send failed for %s: %s", item.get("id"), exc)
        return False
    finally:
        await bot.session.close()
