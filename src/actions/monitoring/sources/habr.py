"""career.habr.com — httpx, data-ssr-state JSON blob (listing + detail).

Ported verbatim from ``monitor_proto.py`` (HABR CAREER section, verified 2026-06-18).
"""

from __future__ import annotations

import json
import re

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BASE_HEADERS, BaseSourceScraper
from src.domain.models.monitoring import MonitorItem

_HABR_URL = "https://career.habr.com/vacancies?sort=date&page=1"


def _habr_extract_ssr(html: str) -> list[dict]:
    m = re.search(
        r'<script[^>]+data-ssr-state="true"[^>]*>(\{.+\})</script>',
        html, re.DOTALL,
    )
    if not m:
        return []
    try:
        state = json.loads(m.group(1))
    except Exception:
        return []
    vacs = state.get("vacancies", [])
    if isinstance(vacs, dict):  # new format (2026-06): {"list": [...], "meta": {...}}
        vacs = vacs.get("list", [])
    return vacs if isinstance(vacs, list) else []


@register_source
class HabrScraper(BaseSourceScraper):
    source = "habr"
    headers = BASE_HEADERS

    async def collect(self, limit: int = 25) -> list[MonitorItem]:
        html = await self.fetch_text(_HABR_URL)
        raw = _habr_extract_ssr(html)
        if not raw:
            raise RuntimeError("SSR state not found or vacancies list empty in habr response")

        items = []
        for v in raw[:limit]:
            vid = str(v.get("id", ""))
            href = v.get("href", f"/vacancies/{vid}")
            sal = v.get("salary") or {}
            pub = (v.get("publishedDate") or {}).get("date", "")
            company = (v.get("company") or {}).get("title", "")
            items.append(MonitorItem(
                source="habr",
                id=vid,
                title=v.get("title", ""),
                url=f"https://career.habr.com{href}",
                amount=sal.get("formatted") or None,
                date=pub,
                extra={"company": company, "remote": v.get("remoteWork", False)},
            ))
        return items

    async def detail(self, item: dict) -> dict:
        html = await self.fetch_text(item["url"])
        m = re.search(
            r'<script[^>]+data-ssr-state="true"[^>]*>(\{.+\})</script>',
            html, re.DOTALL,
        )
        if not m:
            raise RuntimeError("SSR state not found in habr card page")
        state = json.loads(m.group(1))
        vac = state.get("vacancy") or {}
        company = state.get("company") or {}
        sal = vac.get("salary") or {}
        desc_raw = vac.get("description", "") or vac.get("bannerDescription", "")
        desc_text = re.sub(r"<[^>]+>", " ", desc_raw)[:500]

        return {
            "id": item["id"],
            "title": vac.get("title", item["title"]),
            "company": company.get("title", ""),
            "amount": sal.get("formatted") or None,
            "description": desc_text,
            "date": (vac.get("publishedDate") or {}).get("date", ""),
            "skills": [s.get("title", "") for s in (vac.get("skills") or [])[:10]],
            "url": item["url"],
        }
