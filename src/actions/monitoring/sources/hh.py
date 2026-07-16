"""hh.ru — Playwright+stealth headless (DDoS-Guard; httpx is blocked here).

The listing parser ``_hh_extract_from_json`` (verbatim from ``monitor_proto.py``,
verified 2026-06-17) reads the vacancy JSON embedded in the SSR HTML, so ``collect``
just needs rendered page HTML. ``detail`` uses the async page DOM API (a port of
``_hh_extract_vacancy_card``). hh skips the httpx path entirely — it always blocks —
and renders directly through the shared stealth browser pool.

search URL: professional_role=96 (backend dev) narrows to real Python/backend roles;
area=113 = all Russia.
"""

from __future__ import annotations

import asyncio
import re

from playwright.async_api import Page

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BaseSourceScraper
from src.core.config import settings
from src.domain.models.monitoring import MonitorItem
from src.infrastructure.browser.pool_manager import pool_manager
from src.infrastructure.browser.proxy_provider import proxy_provider

_HH_SEARCH_URL = (
    "https://hh.ru/search/vacancy"
    "?text=python&order_by=publication_time"
    "&professional_role=96&area=113"
)
_HH_SELECTORS = {
    "vacancy_title": "[data-qa='vacancy-title']",
    "vacancy_company": "[data-qa='vacancy-company-name']",
    "vacancy_salary": "[data-qa='vacancy-salary']",
    "vacancy_experience": "[data-qa='vacancy-experience']",
    "vacancy_description": "[data-qa='vacancy-description']",
    "vacancy_address": "[data-qa='vacancy-address-with-map']",
    "vacancy_skills_bloko": "[data-qa='bloko-tag__text']",
}


def _hh_extract_from_json(html: str) -> list[dict]:
    """Extract vacancies from the JSON blob embedded in hh SSR HTML (verbatim)."""
    results = []
    for m in re.finditer(r'"vacancyId":(\d+),"name":"([^"]+)"', html):
        vid = m.group(1)
        name = m.group(2).replace("&amp;", "&")
        pos = m.start()
        company = ""
        company_m = re.search(r'"visibleName":"([^"]+)"', html[pos: pos + 800])
        if company_m:
            company = company_m.group(1).replace("&amp;", "&")
        salary = ""
        comp_m = re.search(r'"compensation":\{(.*?)\}', html[pos: pos + 1200])
        if comp_m:
            comp_str = comp_m.group(1)
            if "noCompensation" not in comp_str and comp_str.strip():
                from_m = re.search(r'"from":(\d+)', comp_str)
                to_m = re.search(r'"to":(\d+)', comp_str)
                cur_m = re.search(r'"currencyCode":"([^"]+)"', comp_str)
                parts = []
                if from_m:
                    parts.append(f"от {from_m.group(1)}")
                if to_m:
                    parts.append(f"до {to_m.group(1)}")
                if cur_m:
                    parts.append(cur_m.group(1))
                salary = " ".join(parts)
        pub_m = re.search(
            r'"publicationTime":\{"@timestamp":\d+,"\$":"([^"]+)"',
            html[pos: pos + 600],
        )
        pub_time = pub_m.group(1) if pub_m else ""
        results.append({
            "id": vid,
            "title": name,
            "company": company,
            "salary": salary,
            "publication_time": pub_time,
            "link": f"https://hh.ru/vacancy/{vid}",
        })
    seen: set = set()
    deduped = []
    for r in results:
        if r["id"] not in seen:
            seen.add(r["id"])
            deduped.append(r)
    return deduped


async def _hh_extract_vacancy_card(page: Page) -> dict:
    """Async port of monitor_proto._hh_extract_vacancy_card."""
    result: dict = {}

    async def q(sel: str, fallback: str = "") -> str:
        try:
            el = await page.query_selector(sel)
            return (await el.inner_text()).strip() if el else fallback
        except Exception:
            return fallback

    result["title"] = (await q(_HH_SELECTORS["vacancy_title"])) or (await q("h1"))
    result["company"] = await q(_HH_SELECTORS["vacancy_company"])
    result["salary"] = await q(_HH_SELECTORS["vacancy_salary"])
    result["experience"] = await q(_HH_SELECTORS["vacancy_experience"])
    result["area"] = await q(_HH_SELECTORS["vacancy_address"])
    html = await page.content()
    pub_m = re.search(r"Вакансия опубликована <span>([^<]+)</span>", html)
    result["publication_date"] = pub_m.group(1).replace("&nbsp;", " ").strip() if pub_m else ""
    desc_el = await page.query_selector(_HH_SELECTORS["vacancy_description"])
    if desc_el:
        desc_text = (await desc_el.inner_text()).strip()
        result["description_preview"] = desc_text[:800]
    else:
        result["description_preview"] = ""
    skill_els = await page.query_selector_all(_HH_SELECTORS["vacancy_skills_bloko"])
    if skill_els:
        result["key_skills"] = [(await el.inner_text()).strip() for el in skill_els]
    else:
        ks_m = re.search(r'"keySkills":\[([^\]]+)\]', html)
        result["key_skills"] = re.findall(r'"([^"]+)"', ks_m.group(1)) if ks_m else []
    return result


@register_source
class HHScraper(BaseSourceScraper):
    source = "hh"

    async def collect(self, limit: int = 25) -> list[MonitorItem]:
        html = await self._browser_get(_HH_SEARCH_URL, wait_s=8)
        raw = _hh_extract_from_json(html)
        if not raw:
            raise RuntimeError("No vacancies extracted from hh.ru search page")
        return [
            MonitorItem(
                source="hh",
                id=v.get("id", ""),
                title=v.get("title", ""),
                url=v.get("link", f"https://hh.ru/vacancy/{v.get('id', '')}"),
                amount=v.get("salary") or None,
                date=v.get("publication_time", ""),
                extra={"company": v.get("company", "")},
            )
            for v in raw[:limit]
        ]

    async def detail(self, item: dict) -> dict:
        url = f"https://hh.ru/vacancy/{item['id']}"
        proxy = proxy_provider.get_proxy() if settings.MONITOR_USE_PROXY else None
        context = await pool_manager.create_context(stealth=True, proxy=proxy)
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.BROWSER_TIMEOUT)
            await asyncio.sleep(6)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            card = await _hh_extract_vacancy_card(page)
        finally:
            await context.close()

        return {
            "id": item["id"],
            "title": card.get("title", item["title"]),
            "company": card.get("company", ""),
            "amount": card.get("salary") or None,
            "description": card.get("description_preview", "")[:400],
            "experience": card.get("experience", ""),
            "skills": card.get("key_skills", []),
            "date": card.get("publication_date", ""),
            "url": url,
        }
