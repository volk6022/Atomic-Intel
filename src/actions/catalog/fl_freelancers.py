"""fl.ru freelancer-catalog scraper (supply / competition side).

Async port of ``experiment_monitoring/experiment-fl/fl_freelancers_scrape.py``.
fl.ru is project-bidding (no fixed-gig catalog), so the competition analog is the
freelancer catalog. LIST: GET /freelancers/<profession>/page-<N>/ (SSR-HTML, 40/page).
PROFILE: GET /users/<login>/ → declared hourly/monthly rate. httpx-direct (DDoS-Guard
is passive); proxy is a fallback. Pure parsers copied verbatim.
"""

from __future__ import annotations

import html as htmllib
import re

from src.actions.catalog.http import catalog_request, throttle
from src.core.logging import get_logger
from src.domain.models.catalog import FreelancerProfile

logger = get_logger(__name__)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": CHROME_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

THROTTLE_BASE = 1.2
THROTTLE_JITTER = 0.8

_ROW_SPLIT = 'data-id="qa-content-tr"'


def _is_block(r) -> bool:
    if r.status_code in (403, 429, 503):
        return True
    low = r.text[:2000].lower()
    return "ddos-guard" in low and "challenge" in low


# --- pure parsers (verbatim) ------------------------------------------------
def _clean(s: str | None) -> str:
    if not s:
        return ""
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def parse_rows(html: str, profession: str) -> list[dict]:
    parts = html.split(_ROW_SPLIT)
    rows: list[dict] = []
    for chunk in parts[1:]:
        head = chunk[:200]
        if "cf-line" not in head:
            continue
        mat = re.search(r'(\d+),(\d+)\s*deal,(\d+)\s*reviews', chunk)
        if mat:
            uid, deals, reviews = mat.group(1), int(mat.group(2)), int(mat.group(3))
        else:
            um = re.search(r"el:\s*['\"](\d+)['\"]", chunk) or re.search(r'\buid(\d+)\b', chunk)
            uid, deals, reviews = (um.group(1) if um else None), None, None
        if not uid:
            continue
        login_m = re.search(r'/users/([A-Za-z0-9_.\-]+)/', chunk)
        login = login_m.group(1) if login_m else None
        is_pro = "limited-card" not in head
        name_m = re.search(r'cf-title-card-new[^>]*>([^<]+)<', chunk)
        name = _clean(name_m.group(1)) if name_m else None
        anonymized = (login is None) or (name == "Фрилансер")
        if anonymized:
            login = login or None
            name = None
        spec_slug = spec_text = None
        sp = re.search(r'data-id="qa-content-tr-td-cf-spec"[^>]*>(.*?)</(?:a|span)>', chunk, re.S)
        if sp:
            spec_text = _clean(sp.group(1)) or None
        sl = re.search(
            r'href="/freelancers/([a-z0-9\-]+)/"[^>]*data-id="qa-content-tr-td-cf-spec"',
            chunk, re.S)
        spec_slug = sl.group(1) if sl else None
        grp_m = re.search(r'>\s*([А-ЯЁ][А-Яа-яёЁ ,/\-]{2,40}):\s*<a', chunk)
        spec_group = _clean(grp_m.group(1)) if grp_m else None
        exp_m = re.search(r'Опыт:\s*(\d+)\s*(?:лет|год|года)', chunk)
        experience = int(exp_m.group(1)) if exp_m else None
        pf_m = re.search(r'>(\d+)\s*работ', chunk)
        portfolio = int(pf_m.group(1)) if pf_m else None
        is_verified = ("#reward" in chunk) or ("Верифицированный" in chunk)
        rows.append({
            "uid": uid, "login": login, "name": name, "anonymized": anonymized,
            "spec_group": spec_group, "spec_slug": spec_slug, "spec_text": spec_text,
            "experience_years": experience, "portfolio_works": portfolio,
            "reviews": reviews, "deals": deals,
            "is_pro": is_pro, "is_verified": is_verified,
            "profession": profession,
        })
    return rows


def catalog_pagination(html: str, profession: str) -> tuple[int, bool]:
    pages = [int(m) for m in re.findall(rf'/{re.escape(profession)}/page-(\d+)/', html)]
    return (max(pages) if pages else 1, "pagination-dots" in html)


def _rub(after: str) -> int | None:
    m = re.search(r'([\d\s]+)(?:&#8381;|₽)', after)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


class FLFreelancersAction:
    async def scrape_profession(self, profession: str, max_pages: int) -> tuple[list[dict], dict]:
        url1 = f"https://www.fl.ru/freelancers/{profession}/"
        try:
            r = await catalog_request("GET", url1, is_block=_is_block, use_proxy=False, headers=HEADERS)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fl profession %s page 1 failed: %s", profession, exc)
            return [], {"profession": profession, "error": str(exc)}
        max_page, dots = catalog_pagination(r.text, profession)
        est_pages = max_page + (1 if dots else 0)
        rows = parse_rows(r.text, profession)
        seen = {row["uid"] for row in rows}
        pages_to_get = min(max_pages, est_pages)
        for p in range(2, pages_to_get + 1):
            await throttle(THROTTLE_BASE, THROTTLE_JITTER)
            url = f"https://www.fl.ru/freelancers/{profession}/page-{p}/"
            try:
                rp = await catalog_request("GET", url, is_block=_is_block, use_proxy=False, headers=HEADERS)
            except Exception as exc:  # noqa: BLE001
                logger.warning("fl profession %s page %d failed: %s", profession, p, exc)
                break
            new = [x for x in parse_rows(rp.text, profession) if x["uid"] not in seen]
            seen.update(x["uid"] for x in new)
            rows.extend(new)
            if not new:
                break
        meta = {
            "profession": profession,
            "visible_max_page": max_page,
            "has_more": dots,
            "est_total_pages": est_pages,
            "est_total_freelancers": est_pages * 40,
            "scraped": len(rows),
            "pro_scraped": sum(1 for x in rows if x["is_pro"]),
        }
        return rows, meta

    async def fetch_profile_rate(self, login: str) -> dict | None:
        url = f"https://www.fl.ru/users/{login}/"
        try:
            r = await catalog_request("GET", url, is_block=_is_block, use_proxy=False, headers=HEADERS)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fl profile rate %s failed: %s", login, exc)
            return None
        html = r.text
        hourly = monthly = None
        i = html.find("Стоимость часа работы")
        if i != -1:
            hourly = _rub(html[i:i + 120])
        j = html.find("Стоимость месяца работы")
        if j != -1:
            monthly = _rub(html[j:j + 120])
        return {"login": login, "hourly_rate": hourly, "monthly_rate": monthly}

    async def execute(self, profession: str, max_pages: int = 5, profiles: int = 0) -> dict:
        rows, meta = await self.scrape_profession(profession, max_pages)
        rates: list[dict] = []
        if profiles:
            linkable = [x for x in rows if x.get("login")]
            ranked = sorted(linkable, key=lambda x: int(x.get("reviews") or 0), reverse=True)
            for x in ranked[:profiles]:
                await throttle(THROTTLE_BASE, THROTTLE_JITTER)
                pr = await self.fetch_profile_rate(x["login"])
                if pr:
                    pr["reviews"] = x.get("reviews")
                    pr["profession"] = profession
                    rates.append(pr)
        hourly = sorted(x["hourly_rate"] for x in rates if x.get("hourly_rate"))
        meta["rates_sampled"] = len(rates)
        meta["hourly_median"] = hourly[len(hourly) // 2] if hourly else None
        return {
            "freelancers": [FreelancerProfile(**x) for x in rows],
            "rates": rates,
            "meta": meta,
        }
