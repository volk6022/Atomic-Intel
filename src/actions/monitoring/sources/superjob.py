"""superjob.ru — httpx, JSON-LD + window.APP_STATE (listing + detail).

Parsers ported verbatim from ``monitor_proto.py`` (SUPERJOB.RU section, with the
bug-fix comments preserved: APP_STATE.ids VACANCY_SEARCH_RESULT is the canonical
date-sorted order; JSON-LD ItemList position is relevance, not date).
"""

from __future__ import annotations

import json
import re

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BaseSourceScraper, CHROME_UA
from src.domain.models.monitoring import MonitorItem

_SJ_HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}
_SJ_URL = (
    "https://russia.superjob.ru/vacancy/search/"
    "?keywords=Python&sort_by=date_updated&order=desc&page=1"
)


def _sj_extract_from_html(html: str) -> list[dict]:
    results_by_id: dict[str, dict] = {}

    ld_scripts = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    ld_order: list[str] = []
    for s in ld_scripts:
        try:
            data = json.loads(s)
            if data.get("@type") == "ItemList":
                for item in data.get("itemListElement", []):
                    url = item.get("url", "")
                    m = re.search(r"/vakansii/(.+?)-(\d+)\.html$", url)
                    if m:
                        vid = m.group(2)
                        ld_order.append(vid)
                        results_by_id[vid] = {
                            "id": vid, "slug": m.group(1), "url": url,
                            "title": "", "company": "",
                            "salary_min": 0, "salary_max": 0,
                            "salary_agreement": False, "published_at": "",
                            "_source": "ld_json",
                        }
        except Exception:
            pass

    app_state_order: list[str] = []
    idx = html.find("window.APP_STATE=")
    if idx >= 0:
        raw = html[idx + len("window.APP_STATE="):]
        depth = 0
        end = 0
        for i, c in enumerate(raw):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            if depth == 0 and i > 0:
                end = i + 1
                break
        if end > 0:
            try:
                state = json.loads(raw[:end])
                app_state_order = [
                    str(v) for v in state.get("ids", {}).get("VACANCY_SEARCH_RESULT", [])
                ]
                entities = state.get("entities", {})
                for vid, vac_entity in entities.get("vacancyMainInfo", {}).items():
                    attrs = vac_entity.get("attributes", {})
                    if vid not in results_by_id:
                        results_by_id[vid] = {
                            "id": vid, "slug": "", "url": "",
                            "title": "", "company": "",
                            "salary_min": 0, "salary_max": 0,
                            "salary_agreement": False, "published_at": "",
                            "_source": "app_state",
                        }
                    results_by_id[vid]["title"] = attrs.get("profession", "")
                    results_by_id[vid]["published_at"] = (
                        attrs.get("updatedAt", "") or attrs.get("publishedAt", "")
                    )
                for vid, sal_e in entities.get("vacancySalary", {}).items():
                    if vid in results_by_id:
                        attrs = sal_e.get("attributes", {})
                        results_by_id[vid]["salary_min"] = attrs.get("minSalary", 0)
                        results_by_id[vid]["salary_max"] = attrs.get("maxSalary", 0)
                        results_by_id[vid]["salary_agreement"] = attrs.get("paymentAgreement", False)
                for vid, comp_e in entities.get("vacancyCompanyInfo", {}).items():
                    if vid in results_by_id:
                        results_by_id[vid]["company"] = comp_e.get("attributes", {}).get("name", "")
            except Exception:
                pass

    for vid, entry in results_by_id.items():
        if not entry.get("url"):
            slug = entry.get("slug", "")
            entry["url"] = (
                f"https://russia.superjob.ru/vakansii/{slug}-{vid}.html" if slug
                else f"https://russia.superjob.ru/vakansii/{vid}.html"
            )

    canonical_order = app_state_order if app_state_order else ld_order
    ordered = [results_by_id[vid] for vid in canonical_order if vid in results_by_id]
    seen = set(canonical_order)
    ordered += [v for vid, v in results_by_id.items() if vid not in seen]
    return ordered


def _sj_extract_card(html: str, vacancy_id: str) -> dict:
    result: dict = {
        "id": vacancy_id, "title": "", "company": "",
        "salary_min": 0, "salary_max": 0, "salary_agreement": False,
        "currency": "RUB", "published_at": "", "town": "", "description": "",
    }
    ld_scripts = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    for s in ld_scripts:
        try:
            data = json.loads(s)
            if data.get("@type") == "JobPosting":
                result["title"] = data.get("title", "")
                result["published_at"] = data.get("datePosted", "")
                result["company"] = (data.get("hiringOrganization") or {}).get("name", "")
                result["town"] = (
                    (data.get("jobLocation") or {})
                    .get("address", {})
                    .get("addressLocality", "")
                )
                result["description"] = re.sub(r"<[^>]+>", " ", data.get("description", ""))[:500]
                sal = data.get("baseSalary") or {}
                val = sal.get("value") or {}
                result["salary_min"] = val.get("minValue", 0)
                result["salary_max"] = val.get("maxValue", 0)
        except Exception:
            pass

    if not result["salary_min"] and not result["salary_max"]:
        idx = html.find("window.APP_STATE=")
        if idx >= 0:
            raw = html[idx + len("window.APP_STATE="):]
            depth = 0
            end = 0
            for i, c in enumerate(raw):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                if depth == 0 and i > 0:
                    end = i + 1
                    break
            if end > 0:
                try:
                    state = json.loads(raw[:end])
                    entities = state.get("entities", {})
                    vac_main = entities.get("vacancyMainInfo", {})
                    vac_sal = entities.get("vacancySalary", {})
                    if vacancy_id in vac_main:
                        attrs = vac_main[vacancy_id].get("attributes", {})
                        result["salary_min"] = attrs.get("minSalary", 0) or 0
                        result["salary_max"] = attrs.get("maxSalary", 0) or 0
                        if not result["title"]:
                            result["title"] = attrs.get("profession", "")
                        if not result["published_at"]:
                            result["published_at"] = attrs.get("publishedAt", "")
                    if vacancy_id in vac_sal:
                        attrs = vac_sal[vacancy_id].get("attributes", {})
                        result["salary_min"] = attrs.get("minSalary", 0) or result["salary_min"]
                        result["salary_max"] = attrs.get("maxSalary", 0) or result["salary_max"]
                        result["salary_agreement"] = attrs.get("paymentAgreement", False)
                except Exception:
                    pass
    return result


def _sj_amount(sal_min, sal_max, agreement) -> str | None:
    sal_min = sal_min or 0
    sal_max = sal_max or 0
    if sal_min or sal_max:
        return (
            f"{sal_min}–{sal_max} RUB" if sal_min and sal_max
            else (f"от {sal_min}" if sal_min else f"до {sal_max}")
        )
    if agreement:
        return "по договорённости"
    return None


@register_source
class SuperjobScraper(BaseSourceScraper):
    source = "superjob"
    headers = _SJ_HEADERS

    async def collect(self, limit: int = 25) -> list[MonitorItem]:
        html = await self.fetch_text(_SJ_URL)
        raw = _sj_extract_from_html(html)
        if not raw:
            raise RuntimeError("No vacancies extracted from superjob.ru")

        items = []
        for v in raw[:limit]:
            items.append(MonitorItem(
                source="superjob",
                id=v.get("id", ""),
                title=v.get("title", ""),
                url=v.get("url", ""),
                amount=_sj_amount(v.get("salary_min"), v.get("salary_max"), v.get("salary_agreement")),
                date=v.get("published_at", ""),
                extra={"company": v.get("company", ""), "slug": v.get("slug", "")},
            ))
        return items

    async def detail(self, item: dict) -> dict:
        url = item["url"]
        if not url:
            slug = (item.get("extra") or item.get("_extra") or {}).get("slug", "")
            vid = item["id"]
            url = f"https://russia.superjob.ru/vakansii/{slug}-{vid}.html" if slug else \
                  f"https://russia.superjob.ru/vakansii/{vid}.html"
        html = await self.fetch_text(url)
        card = _sj_extract_card(html, item["id"])
        return {
            "id": item["id"],
            "title": card.get("title", item["title"]),
            "company": card.get("company", ""),
            "amount": _sj_amount(card.get("salary_min"), card.get("salary_max"), card.get("salary_agreement")),
            "description": card.get("description", "")[:400],
            "date": card.get("published_at", ""),
            "town": card.get("town", ""),
            "url": url,
        }
