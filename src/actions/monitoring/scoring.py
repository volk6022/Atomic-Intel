"""Scoring a job posting against the operator's profile, and drafting the reply.

Two decisions are baked in here and both are worth stating, because either could
reasonably have gone the other way.

**The model returns a breakdown, not a number.** A bare 0-100 cannot be
calibrated: when a third of the notifications are wrong, a single number gives no
way to tell *which kind* of match is lying, so the threshold has to be moved
blind. With ``match_type`` on every result, two weeks of "skip" taps show that -
say - the misses are almost all ``adjacent``, and only that bucket needs
tightening.

**Budget, competition and freshness are not in the score.** They are not
relevance. Folded into the score they would be indistinguishable from a bad fit,
and a rejected item could never be explained.

Budget and competition run as flat prefilters before the model, which also saves
the tokens. Freshness has no filter: every source here is a date-ordered feed
read from the top, so a stale posting cannot reach the sweep in the first place.
Adding a filter would only matter if a source started returning by relevance.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from src.actions.monitoring import prompts
from src.core.logging import get_logger
from src.infrastructure.external_api.facade import LLMFacade
from src.infrastructure.tasks import monitor_settings

logger = get_logger(__name__)

MATCH_TYPES = ("listing", "product", "skill", "adjacent", "none")
VERDICTS = ("take", "look", "skip")

SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "match_type": {"type": "string", "enum": list(MATCH_TYPES)},
        "matched_offer": {"type": "string"},
        "have": {"type": "array", "items": {"type": "string"}},
        "gap": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
    },
    "required": ["score", "match_type", "matched_offer", "have", "gap", "verdict", "reason"],
    "additionalProperties": False,
}

_DIGITS_RE = re.compile(r"\d[\d\s ]*")


def parse_amount(value: Any) -> Optional[int]:
    """Best-effort rubles from the free-form amount field.

    ``None`` means "not stated", which is a normal state on fl.ru ("negotiable")
    and must never be read as zero - that would silently drop every posting whose
    budget is open to discussion.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = _DIGITS_RE.search(str(value))
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(0))
    return int(digits) if digits else None


def offers_count(item: dict) -> Optional[int]:
    """How many freelancers already answered, or ``None`` when unknown.

    fl.ru supplies it through ``offers/range``, kwork through ``kwork_count``.
    Unknown is not zero: a contest returns no stats at all, and treating that as
    "no competition" would be exactly backwards.
    """
    extra = item.get("extra") or {}
    stats = item.get("offers_stats") or extra.get("offers_stats") or {}
    if isinstance(stats, dict) and stats.get("freelancersCount") is not None:
        return int(stats["freelancersCount"])
    if extra.get("kwork_count") is not None:
        return int(extra["kwork_count"])
    return None


def passes_cheap_filters(item: dict) -> tuple[bool, str]:
    """Flat checks that run before the model. Returns ``(ok, reason_if_dropped)``.

    Every rejection here is recorded and visible in ``/mon last``: a filter whose
    effect cannot be seen is a filter nobody can tune.
    """
    floor = monitor_settings.min_price()
    if floor:
        amount = parse_amount(item.get("amount"))
        if amount is not None and amount < floor:
            return False, f"budget {amount} below the {floor} floor"

    cap = monitor_settings.max_offers()
    if cap:
        count = offers_count(item)
        if count is not None and count > cap:
            return False, f"{count} offers already, cap is {cap}"

    return True, ""


def _render_item(item: dict) -> str:
    extra = item.get("extra") or {}
    lines = [
        f"SOURCE: {item.get('source', '')}",
        f"TITLE: {item.get('title', '')}",
        f"CATEGORY: {extra.get('category') or item.get('category') or 'unknown'}",
        # Labelled as the client's, not as a quote: the drafting prompt was
        # reading a bare "BUDGET" as the price to name and quoting the client's
        # own ceiling straight back at him.
        f"BUDGET THE CLIENT NAMED: {item.get('amount') or 'not stated'}",
    ]
    count = offers_count(item)
    if count is not None:
        lines.append(f"OFFERS ALREADY SUBMITTED: {count}")
    brief = (item.get("description") or extra.get("desc") or "").strip()
    lines.append(f"BRIEF:\n{brief}")
    return "\n".join(lines)


async def score_item(
    client: LLMFacade,
    item: dict,
    *,
    contour: str,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Score one posting. Raises on an unusable model reply so the caller can retry.

    Items are scored one at a time rather than batched: an fl.ru brief runs to
    five thousand characters and the profile is another few thousand, so two or
    three postings would already crowd a 27k context.
    """
    system_prompt = monitor_settings.prompt(
        contour, prompts.default_prompt(contour)
    )
    profile_text = profile if profile is not None else monitor_settings.profile_text()
    user_prompt = (
        f"{profile_text}\n\n---\n\nJOB POSTING:\n{_render_item(item)}"
        if profile_text
        else f"JOB POSTING:\n{_render_item(item)}"
    )

    result = await client.generate_structured(
        prompt=user_prompt,
        system_prompt=system_prompt,
        schema=SCORE_SCHEMA,
        schema_name="job_score",
    )

    result["score"] = max(0, min(100, int(result.get("score", 0))))
    if result.get("match_type") not in MATCH_TYPES:
        result["match_type"] = "none"
    if result.get("verdict") not in VERDICTS:
        result["verdict"] = "skip"
    result["contour"] = contour
    return result


async def draft_reply(client: LLMFacade, item: dict, score: dict[str, Any]) -> str:
    """First message to the client. Falls back to empty text rather than failing.

    A missing draft costs a bit of typing; a failed sweep costs the posting. So a
    drafting error is logged and swallowed - the notification still goes out.
    """
    system_prompt = monitor_settings.prompt(
        prompts.DRAFT, prompts.default_prompt(prompts.DRAFT)
    )
    matched = score.get("matched_offer") or ""
    context = _render_item(item)
    if matched:
        context += f"\n\nCLOSEST THING I ALREADY SELL: {matched}"
    have = ", ".join(score.get("have") or [])
    if have:
        context += f"\nWHAT I HAVE DONE BEFORE THAT APPLIES: {have}"

    try:
        return (await client.generate(context, system_prompt)).strip()
    except Exception as exc:  # noqa: BLE001 - never lose the notification over a draft
        logger.warning("scoring: draft failed for %s: %s", item.get("id"), exc)
        return ""
