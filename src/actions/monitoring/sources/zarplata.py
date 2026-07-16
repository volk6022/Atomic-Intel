"""zarplata.ru — httpx, embedded HH/Redux vacancies (listing + detail).

zarplata.ru runs on hh.ru infrastructure, so the same ``vacancyId`` Redux state is
embedded. Parsers ported verbatim from ``monitor_proto.py`` (ZARPLATA.RU section,
with bug-fix #1: anchor field search to the chunk after each vacancyId occurrence).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from src.actions.monitoring import register_source
from src.actions.monitoring.base import BASE_HEADERS, BaseSourceScraper
from src.domain.models.monitoring import MonitorItem

_ZP_URL = "https://www.zarplata.ru/vacancies/search/?text=python&order_by=publication_time"


def _zp_extract_vacancies(html: str) -> list[dict]:
    results: dict[str, dict] = {}
    for m in re.finditer(r'"vacancyId"\s*:\s*(\d+)', html):
        vid = m.group(1)
        if vid in results:
            continue
        pos = m.start()
        chunk = html[pos: pos + 1500]

        name_m = re.search(r'"name"\s*:\s*"([^"]+)"', chunk)
        company_m = re.search(r'"visibleName"\s*:\s*"([^"]+)"', chunk)
        sal_from_m = re.search(r'"from"\s*:\s*(\d+)', chunk)
        sal_to_m = re.search(r'"to"\s*:\s*(\d+)', chunk)
        cur_m = re.search(r'"currencyCode"\s*:\s*"([^"]+)"', chunk)
        pub_m = re.search(r'"publicationTime"[^{]*"@timestamp"\s*:\s*(\d+)', html[pos: pos + 600])

        sal_parts = []
        if sal_from_m:
            sal_parts.append(f"от {sal_from_m.group(1)}")
        if sal_to_m:
            sal_parts.append(f"до {sal_to_m.group(1)}")
        if cur_m:
            sal_parts.append(cur_m.group(1))
        salary = " ".join(sal_parts) if sal_parts else None

        pub_dt = ""
        if pub_m:
            try:
                pub_dt = datetime.fromtimestamp(
                    int(pub_m.group(1)) / 1000, tz=timezone.utc
                ).isoformat()
            except Exception:
                pub_dt = pub_m.group(1)

        results[vid] = {
            "id": vid,
            "title": name_m.group(1) if name_m else "",
            "company": company_m.group(1) if company_m else "",
            "salary": salary,
            "date": pub_dt,
            "url": f"https://www.zarplata.ru/vacancy/{vid}",
        }
    return list(results.values())


@register_source
class ZarplataScraper(BaseSourceScraper):
    source = "zarplata"
    headers = BASE_HEADERS

    async def collect(self, limit: int = 30) -> list[MonitorItem]:
        html = await self.fetch_text(_ZP_URL)
        raw = _zp_extract_vacancies(html)
        if not raw:
            raise RuntimeError("No vacancyId found in zarplata.ru HTML")

        return [
            MonitorItem(
                source="zarplata",
                id=v["id"],
                title=v["title"],
                url=v["url"],
                amount=v.get("salary"),
                date=v.get("date", ""),
                extra={"company": v.get("company", "")},
            )
            for v in raw[:limit]
        ]

    async def detail(self, item: dict) -> dict:
        html = await self.fetch_text(item["url"], headers=BASE_HEADERS)
        result: dict = {"id": item["id"], "url": item["url"]}

        vid_m = re.search(r'"vacancyId"\s*:\s*' + re.escape(item["id"]), html)
        if not vid_m:
            vid_m = re.search(r'"vacancyId"\s*:\s*\d+', html)
        if vid_m:
            pos = vid_m.start()
            chunk = html[pos: pos + 2000]
        else:
            pos = 0
            chunk = html

        name_m = re.search(r'"name"\s*:\s*"([^"]+)"', chunk)
        company_m = re.search(r'"visibleName"\s*:\s*"([^"]+)"', chunk)
        sal_from_m = re.search(r'"from"\s*:\s*(\d+)', chunk)
        sal_to_m = re.search(r'"to"\s*:\s*(\d+)', chunk)
        cur_m = re.search(r'"currencyCode"\s*:\s*"([^"]+)"', chunk)

        result["title"] = name_m.group(1) if name_m else item["title"]
        result["company"] = company_m.group(1) if company_m else ""

        sal_parts = []
        if sal_from_m:
            sal_parts.append(f"от {sal_from_m.group(1)}")
        if sal_to_m:
            sal_parts.append(f"до {sal_to_m.group(1)}")
        if cur_m:
            sal_parts.append(cur_m.group(1))
        result["amount"] = " ".join(sal_parts) if sal_parts else item.get("amount")

        desc_text = ""
        ld_scripts = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        for s in ld_scripts:
            try:
                d = json.loads(s)
                if d.get("@type") == "JobPosting" and d.get("description"):
                    desc_text = re.sub(r"<[^>]+>", " ", d["description"])
                    desc_text = re.sub(r"\s{2,}", " ", desc_text).strip()
                    break
            except Exception:
                pass
        if not desc_text:
            desc_chunk = html[pos: pos + 50000] if vid_m else html
            desc_m = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.){20,})"', desc_chunk)
            if desc_m:
                try:
                    desc_text = json.loads(f'"{desc_m.group(1)}"')
                except Exception:
                    desc_text = desc_m.group(1)
        if desc_text:
            result["description"] = desc_text[:500]

        return result
