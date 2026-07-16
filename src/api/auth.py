"""API key -> tenant resolution.

Two resolution paths:
  1. Bootstrap admin key (``settings.API_KEY``, env-configured) — always
     resolves to a synthetic bootstrap ``Principal`` without touching
     Postgres. Keeps the service (and its test suite) runnable with zero DB
     setup, and gives Ivan an always-on key while the tenant table is empty.
  2. Any other presented key is sha256-hashed and looked up against
     ``api_keys.key_hash`` for an active key on an active tenant.

``resolve_principal`` is the single source of truth for both the FastAPI
dependency (``get_api_key``, used by routers) and the rate-limit middleware
(``src.api.middleware.rate_limit``), which cannot use ``Depends`` because it
runs before routing. A short in-process TTL cache keeps the DB off the hot
path; on DB error we fail closed (unknown-key rejection) rather than crash
the request.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from src.core.config import settings
from src.core.logging import get_logger
from src.domain.models.principal import LLMProviderConfig, Principal
from src.infrastructure.db.keys import hash_api_key
from src.infrastructure.db.session import session_scope
from src.infrastructure.db.tenant_repository import TenantRepository

logger = get_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_BOOTSTRAP_PRINCIPAL = Principal(
    tenant_id="bootstrap",
    name="bootstrap",
    quota_per_hour=settings.RATE_LIMIT_DEFAULT_PER_HOUR,
    concurrent_research=settings.MAX_CONCURRENT_RESEARCH_TASKS,
    llm_provider_config=None,
    is_bootstrap=True,
)

# key_hash -> (expires_at monotonic, Principal | None). None is cached too —
# a burst of requests with a bad key shouldn't each pay a DB round trip.
_cache: dict[str, tuple[float, Optional[Principal]]] = {}


def _cache_get(key_hash: str) -> tuple[bool, Optional[Principal]]:
    entry = _cache.get(key_hash)
    if entry is None:
        return False, None
    expires_at, principal = entry
    if expires_at < time.monotonic():
        _cache.pop(key_hash, None)
        return False, None
    return True, principal


def _cache_set(key_hash: str, principal: Optional[Principal]) -> None:
    _cache[key_hash] = (time.monotonic() + settings.AUTH_CACHE_TTL_SECONDS, principal)


async def _resolve_tenant_key(raw_key: str) -> Optional[Principal]:
    key_hash = hash_api_key(raw_key)
    hit, cached = _cache_get(key_hash)
    if hit:
        return cached

    try:
        async with session_scope() as session:
            resolved = await TenantRepository(session).resolve_by_key_hash(key_hash)
    except Exception as e:  # DB unreachable — fail closed, don't crash the request
        logger.error("tenant lookup failed (db unavailable): %s", e)
        return None

    principal: Optional[Principal] = None
    if resolved is not None:
        principal = Principal(
            tenant_id=resolved.tenant_id,
            name=resolved.name,
            quota_per_hour=resolved.quota_per_hour,
            concurrent_research=resolved.concurrent_research,
            llm_provider_config=LLMProviderConfig.from_dict(resolved.llm_provider_config),
            is_bootstrap=False,
        )
    _cache_set(key_hash, principal)
    return principal


async def resolve_principal(api_key: Optional[str]) -> Optional[Principal]:
    """Resolve a presented ``X-API-Key`` value to a ``Principal``, or ``None``
    if missing/unknown/inactive. Never raises — callers decide how to react.
    """
    if not api_key:
        return None
    if settings.API_KEY and api_key == settings.API_KEY:
        return _BOOTSTRAP_PRINCIPAL
    return await _resolve_tenant_key(api_key)


async def get_api_key(api_key: str = Security(api_key_header)) -> Principal:
    principal = await resolve_principal(api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    return principal
