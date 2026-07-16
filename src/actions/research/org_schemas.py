"""Type-specific org-card JSON schemas (Workstream A + C).

The research service stays general — the *caller* supplies `output_schema`. This
module builds that schema per organization: a shared BASE plus archetype-specific
`deep_dive` fields and, for archetypes where it's findable, a `legal_entity` block
(ИНН/ОГРН/оборот — Workstream C).

The 517-backup analysis showed flat schemas waste effort (tech_stack empty for
pekarnyas) and miss depth (no place to record a law firm's practice areas). Giving
each type a tailored slot is what makes the agent *chase* the right internal facts.
"""

from __future__ import annotations

import copy

from src.actions.research.org_taxonomy import (
    classify_archetype,
    is_tech,
    wants_legal_entity,
)


def _str_array() -> dict:
    return {"type": "array", "items": {"type": "string"}}


# Shared base — the fields every org card carries.
BASE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "what_they_do": {"type": "string"},
        "scale_indicators": _str_array(),
        "vacancies": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "platform": {"type": "string",
                                 "enum": ["hh.ru", "superjob.ru", "career_page", "other"]},
                },
            },
        },
        "social": {
            "type": "object", "additionalProperties": False,
            "properties": {k: _str_array() for k in
                           ("vk", "telegram", "instagram", "youtube", "linkedin", "habr")},
        },
        "contacts": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "phones": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"number": {"type": "string"},
                                   "context": {"type": "string"}}}},
                "emails": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"address": {"type": "string"},
                                   "context": {"type": "string"}}}},
                "websites": _str_array(),
            },
        },
        "yandex_maps": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "rating": {"type": "number"},
                "reviews_count": {"type": "integer"},
                "reviews_sample": _str_array(),
                "hours": {"type": "string"},
            },
        },
        "problems_signals": _str_array(),
        "sources": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"url": {"type": "string"},
                               "what_it_provided": {"type": "string"}},
            },
        },
    },
}

# Archetype-specific deep-dive properties (merged into a `deep_dive` object).
DEEP_DIVE: dict[str, dict] = {
    "law": {
        "practice_areas": _str_array(),
        "notable_cases": _str_array(),
        "bar_association": {"type": "string"},
        "lawyers_count": {"type": "string"},
    },
    "med": {
        "specializations": _str_array(),
        "n_doctors": {"type": "string"},
        "n_centers": {"type": "string"},
        "dms_partners": _str_array(),
        "licenses": _str_array(),
        "equipment": _str_array(),
    },
    "food_retail": {
        "cuisine": {"type": "string"},
        "avg_check": {"type": "string"},
        "seating_capacity": {"type": "string"},
        "delivery_aggregators": _str_array(),
        "competitors_nearby": _str_array(),
    },
    "shop": {
        "assortment_focus": _str_array(),
        "key_brands": _str_array(),
        "corporate_offers": {"type": "string"},
        "competitors_nearby": _str_array(),
    },
    "auto": {
        "services": _str_array(),
        "car_brands_served": _str_array(),
        "corporate_fleet_offer": {"type": "string"},
    },
    "repair": {
        "services": _str_array(),
        "turnaround": {"type": "string"},
        "corporate_contracts": {"type": "string"},
    },
    "beauty": {
        "services": _str_array(),
        "masters_count": {"type": "string"},
        "premium_segment": {"type": "string"},
    },
    "fitness": {
        "club_format": {"type": "string"},
        "membership_types": _str_array(),
        "group_classes": _str_array(),
    },
    "finance": {
        "services": _str_array(),
        "licenses": _str_array(),
        "client_segments": _str_array(),
    },
    "realty": {
        "segments": _str_array(),
        "agents_count": {"type": "string"},
    },
    "print": {
        "services": _str_array(),
        "equipment": _str_array(),
        "corporate_orders": {"type": "string"},
    },
    "edu": {
        "programs": _str_array(),
        "age_groups": _str_array(),
    },
}

# Workstream C: legal entity / registry block (rusprofile/checko/list-org).
LEGAL_ENTITY_BLOCK: dict = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "inn": {"type": "string"},
        "ogrn": {"type": "string"},
        "registered_name": {"type": "string"},
        "founded_year": {"type": "string"},
        "employee_count": {"type": "string"},
        "revenue": {"type": "string"},
    },
}


def build_schema(categories: list[str] | None, *, branch_count: int = 1) -> dict:
    """Construct the per-org output schema: base + type deep-dive + legal entity."""
    schema = copy.deepcopy(BASE_SCHEMA)
    archetype = classify_archetype(categories)

    if is_tech(categories):
        schema["properties"]["tech_stack"] = _str_array()

    dd = DEEP_DIVE.get(archetype)
    if dd:
        schema["properties"]["deep_dive"] = {
            "type": "object", "additionalProperties": False,
            "properties": copy.deepcopy(dd),
        }

    if wants_legal_entity(archetype):
        schema["properties"]["legal_entity"] = copy.deepcopy(LEGAL_ENTITY_BLOCK)

    return schema
