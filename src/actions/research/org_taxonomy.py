"""Deterministic business classification from Yandex categories.

Workstream A: the Yandex category is known *before* research, so we can pick a
type-specific schema and research targets up front (no LLM needed). Size tier is
seeded from branch_count and refined later from scale_indicators.

Archetypes are intentionally coarse — they steer which "internal kitchen" fields
are worth chasing (the 517-backup analysis showed depth needs differ sharply by
type: law→specialization, med→doctors/centers, food→check/aggregators, …).
"""

from __future__ import annotations

# Ordered: first archetype whose keyword hits the category string wins. More
# specific types are listed before generic ones (e.g. аптека before магазин).
ARCHETYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("law",        ("адвокат", "юрид", "нотари", "юрист", "правов")),
    ("finance",    ("бухгалт", "аудит", "финанс", "банк", "страхов", "налог")),
    ("med",        ("клиник", "стомат", "медцентр", "медицин", "ветеринар",
                    "поликлин", "диагностик", "лаборатор", "аптек")),
    ("beauty",     ("салон красот", "парикмах", "ногт", "космет", "барбер",
                    "маникюр", "spa", "спа", "эпиляц")),
    ("auto",       ("автосервис", "автомойк", "шиномонтаж", "автотехцентр",
                    "автосалон", "детейлинг", "развал")),
    ("fitness",    ("фитнес", "спортзал", "тренаж", "йога", "бассейн")),
    ("realty",     ("недвиж", "агентство недвиж", "риелт", "застройщик")),
    ("print",      ("типограф", "печать", "полиграф", "копир")),
    ("edu",        ("школа", "детский сад", "курс", "обучен", "репетит", "ясли")),
    ("repair",     ("ремонт", "химчистк", "ателье", "прачечн", "мастерск")),
    ("food_retail",("кафе", "ресторан", "бар", "суши", "кофейн", "столов",
                    "пекарн", "пиццер", "кондитер", "бистро", "паб")),
    ("shop",       ("магазин", "цветы", "продукт", "супермаркет", "бутик",
                    "торгов", "маркет")),
)

# Categories where a tech_stack field is meaningful (IT/digital orgs).
TECH_HINTS: tuple[str, ...] = (
    "it", "айти", "разработк", "программн", "софт", "software", "веб", "web",
    "digital", "диджитал", "интернет", "телеком", "хостинг", "стартап",
    "маркетинг", "реклам", "агентств", "студия", "дизайн", "сайт", "приложен",
    "data", "ai", "ml", "saas", "кибербез", "интегратор", "1с", "crm",
)

# Archetypes for which a legal entity (ИНН/ОГРН/оборот) is realistically findable
# and worth chasing in registries — Workstream C. Micro food/shop/beauty rarely
# expose a useful legal entity, so registry lookup is not pushed for them.
LEGAL_ENTITY_ARCHETYPES = frozenset({
    "law", "finance", "med", "realty", "print", "auto", "edu",
})


def _norm(categories: list[str] | None) -> str:
    return " ".join(str(c) for c in (categories or [])).lower()


def classify_archetype(categories: list[str] | None) -> str:
    cats = _norm(categories)
    for archetype, kws in ARCHETYPE_KEYWORDS:
        if any(k in cats for k in kws):
            return archetype
    return "other"


def is_tech(categories: list[str] | None) -> bool:
    cats = _norm(categories)
    return any(h in cats for h in TECH_HINTS)


def wants_legal_entity(archetype: str) -> bool:
    return archetype in LEGAL_ENTITY_ARCHETYPES


def classify_size(branch_count: int = 1,
                  scale_indicators: list[str] | None = None) -> str:
    """Coarse size tier. Seeded by branch_count, nudged by scale signals.

    micro (1 point) | small | mid | chain (multi-branch / network signals).
    """
    n = branch_count or 1
    text = " ".join(str(s) for s in (scale_indicators or [])).lower()
    chain_signal = any(w in text for w in (
        "сеть", "филиал", "точек", "франшиз", "по всей", "регион", "федеральн",
    ))
    if n >= 3 or chain_signal:
        return "chain"
    big = any(w in text for w in ("сотрудник", "штат", "оборот", "млн", "центр"))
    if n == 2 or big:
        return "mid"
    return "micro"
