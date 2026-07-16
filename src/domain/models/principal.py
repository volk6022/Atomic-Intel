"""The resolved caller identity for a request.

Produced by ``src.api.auth.resolve_principal`` from an ``X-API-Key`` header —
either the env bootstrap key or a DB-backed tenant. Downstream code (research
router, rate-limit middleware, the taskiq worker) reads quota/concurrency/
BYO-LLM config off this object instead of re-deriving them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class LLMProviderConfig:
    """A tenant's bring-your-own LLM endpoint. All three fields are required —
    a partial config is treated as absent (see ``from_dict``)."""

    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> Optional["LLMProviderConfig"]:
        if not data:
            return None
        base_url = data.get("base_url")
        api_key = data.get("api_key")
        model = data.get("model")
        if not (base_url and api_key and model):
            return None
        return cls(base_url=base_url, api_key=api_key, model=model)

    def to_dict(self) -> dict[str, str]:
        return {"base_url": self.base_url, "api_key": self.api_key, "model": self.model}


@dataclass(frozen=True)
class Principal:
    """A resolved caller: a real tenant, or the synthetic bootstrap admin key."""

    tenant_id: str
    name: str
    quota_per_hour: int
    concurrent_research: int
    llm_provider_config: Optional[LLMProviderConfig] = None
    is_bootstrap: bool = False
