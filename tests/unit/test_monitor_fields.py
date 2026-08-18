"""Unit tests for the field extraction the monitor depends on.

These cover the three things that were silently broken or silently discarded
before: the fl.ru brief and budget (which live in LD+JSON, not in the class the
old parser looked for), the fl.ru competition stats behind a double-encoded
payload, and the kwork listing fields that were being thrown away.
"""

import base64
import json

from src.actions.monitoring import notify, scoring
from src.actions.monitoring.sources.fl import decode_offers_range, parse_product_ld
from src.actions.monitoring.sources.kwork import KworkScraper


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _offers_range_response(payload: dict) -> str:
    """Rebuild what fl.ru actually returns: JSON -> base64 -> JWT -> base64."""
    jwt = f"{_b64(b'{}')}.{_b64(json.dumps(payload).encode())}.{_b64(b'sig')}"
    return json.dumps({"result": _b64(jwt.encode()).rstrip("=")})


# ------------------------------------------------------------------- fl.ru
def test_offers_range_is_decoded_without_verifying_the_token():
    payload = {
        "freelancersCount": 4, "minCost": 1200, "maxCost": 25000,
        "minTime": 3, "maxTime": 5, "offersWithAttachCount": 2,
    }
    assert decode_offers_range(_offers_range_response(payload)) == payload


def test_offers_range_handles_the_contest_refusal():
    """Contests answer `auth_failed`; that is 'unknown', not 'zero competition'."""
    assert decode_offers_range('{"error": "auth_failed"}') == {}
    assert decode_offers_range("not json at all") == {}
    assert decode_offers_range({"result": "@@@ not base64 @@@"}) == {}


def test_product_ld_yields_brief_and_budget():
    html = """
    <script type="application/ld+json">{"@type":"WebSite"}</script>
    <script type="application/ld+json">
    {"@type":"Product","description":"Нужен парсер маркетплейса",
     "offers":{"price":"10000","priceCurrency":"RUB"},
     "aggregateRating":{"ratingValue":"4.8","reviewCount":"12"}}
    </script>
    """
    product = parse_product_ld(html)
    assert product["description"] == "Нужен парсер маркетплейса"
    assert product["offers"]["price"] == "10000"
    assert product["aggregateRating"]["reviewCount"] == "12"


def test_product_without_offers_is_not_a_parse_failure():
    """No `offers` block is fl.ru saying 'negotiable' — the item must survive."""
    html = '<script type="application/ld+json">{"@type":"Product","description":"x"}</script>'
    product = parse_product_ld(html)
    assert product["description"] == "x"
    assert "offers" not in product


# -------------------------------------------------------------------- kwork
def test_listing_keeps_the_full_brief_and_the_decision_fields():
    brief = "Ж" * 900  # longer than the 300 chars the old parser kept
    posting = {
        "id": 3237571,
        "name": "Нужен парсер маркетплейса",
        "description": brief,
        "priceLimit": 15000,
        "possiblePriceLimit": 60000,
        "kwork_count": 4,
        "views_dirty": 328,
        "date_create": "2026-08-17 10:00:00",
        "max_days": 7,
        "category_id": 41,
        "user": {"data": {"username": "client", "wants_count": 12}},
        "files": [{"name": "тз.pdf", "size": 1024}],
    }
    item = KworkScraper()._to_item("3237571", posting)

    assert item.extra["desc"] == brief, "the brief must not be truncated"
    assert item.amount == "15000"
    assert item.extra["possiblePriceLimit"] == 60000
    assert item.extra["kwork_count"] == 4
    assert item.extra["client"]["wants_count"] == 12
    assert item.extra["files"][0]["name"] == "тз.pdf"
    assert item.extra["category"] == "41"
    # /projects/<id> is a redirect stub; the notification must link to the page
    # a human can actually read.
    assert item.url.endswith("/view")


# ------------------------------------------------------------------ scoring
def test_amount_parsing_distinguishes_absent_from_zero():
    assert scoring.parse_amount("10000 RUB") == 10000
    assert scoring.parse_amount("Бюджет: 15 000 руб") == 15000
    assert scoring.parse_amount(15000) == 15000
    assert scoring.parse_amount(None) is None
    assert scoring.parse_amount("по договорённости") is None


def test_offers_count_reads_either_source_and_admits_ignorance():
    fl_item = {"offers_stats": {"freelancersCount": 4}}
    kwork_item = {"extra": {"kwork_count": 27}}
    assert scoring.offers_count(fl_item) == 4
    assert scoring.offers_count(kwork_item) == 27
    assert scoring.offers_count({"extra": {}}) is None


# ------------------------------------------------------------------- notify
def test_notification_carries_the_brief_verbatim_and_the_draft_apart():
    item = {
        "source": "kwork",
        "id": "1",
        "title": "Нужен парсер маркетплейса",
        "url": "https://kwork.ru/projects/1/view",
        "amount": "15000",
        "description": "Собрать товары и выгрузить в таблицу",
        "offers_stats": {"freelancersCount": 4, "minCost": 1200, "maxCost": 25000},
    }
    score = {
        "score": 78, "match_type": "listing", "matched_offer": "Парсер под ключ",
        "contour": "a", "reason": "совпадает с витриной", "gap": [],
    }
    text = notify.format_notification(item, score, draft="Здравствуйте, сделаю за 3 дня")

    assert item["url"] in text
    assert "Собрать товары и выгрузить в таблицу" in text
    assert "score 78" in text and "4 отклика" in text and "15 000 ₽" in text
    assert "Конкуренты просят: 1200–25000 ₽" in text
    # the draft sits in its own block so one tap copies it clean
    assert "<pre>Здравствуйте, сделаю за 3 дня</pre>" in text


def test_notification_stays_within_the_telegram_limit():
    item = {"source": "fl", "id": "1", "title": "t", "url": "u",
            "description": "я" * 9000, "amount": None}
    score = {"score": 50, "match_type": "skill", "matched_offer": "", "contour": "b",
             "reason": "", "gap": []}
    assert len(notify.format_notification(item, score, draft="д" * 500)) <= notify.TG_LIMIT
