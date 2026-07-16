"""Data access for tenants + api_keys. No business rules beyond FK integrity —
quota/concurrency/BYO-LLM policy decisions live in the callers (auth
resolution, rate-limit middleware, the admin bot).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import ApiKeyModel, TenantModel


class TenantNotFoundError(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Tenant {name!r} not found")


@dataclass(frozen=True)
class ResolvedTenant:
    """Read-only projection of a tenant, keyed off one of its active api keys."""

    tenant_id: str
    name: str
    quota_per_hour: int
    concurrent_research: int
    llm_provider_config: Optional[dict[str, Any]]


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_by_key_hash(self, key_hash: str) -> Optional[ResolvedTenant]:
        """Active tenant for an active key hash, or None. The one query the
        auth hot path runs (result is short-TTL-cached by the caller)."""
        stmt = (
            select(TenantModel)
            .join(ApiKeyModel, ApiKeyModel.tenant_id == TenantModel.id)
            .where(
                ApiKeyModel.key_hash == key_hash,
                ApiKeyModel.active.is_(True),
                TenantModel.active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        tenant = result.scalar_one_or_none()
        if tenant is None:
            return None
        return ResolvedTenant(
            tenant_id=str(tenant.id),
            name=tenant.name,
            quota_per_hour=tenant.quota_per_hour,
            concurrent_research=tenant.concurrent_research,
            llm_provider_config=tenant.llm_provider_config,
        )

    async def create_tenant(
        self,
        name: str,
        *,
        quota_per_hour: int,
        concurrent_research: int,
    ) -> TenantModel:
        tenant = TenantModel(
            name=name,
            quota_per_hour=quota_per_hour,
            concurrent_research=concurrent_research,
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def issue_key(self, tenant_name: str, key_hash: str) -> ApiKeyModel:
        tenant = await self._get_tenant_by_name(tenant_name)
        api_key = ApiKeyModel(tenant_id=tenant.id, key_hash=key_hash)
        self._session.add(api_key)
        await self._session.flush()
        return api_key

    async def revoke_key(self, key_hash: str) -> bool:
        stmt = update(ApiKeyModel).where(ApiKeyModel.key_hash == key_hash).values(active=False)
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def revoke_all_keys_for_tenant(self, tenant_name: str) -> int:
        tenant = await self._get_tenant_by_name(tenant_name)
        stmt = (
            update(ApiKeyModel)
            .where(ApiKeyModel.tenant_id == tenant.id)
            .values(active=False)
        )
        result = await self._session.execute(stmt)
        return result.rowcount

    async def set_active(self, tenant_name: str, *, active: bool) -> TenantModel:
        tenant = await self._get_tenant_by_name(tenant_name)
        tenant.active = active
        await self._session.flush()
        return tenant

    async def set_quota(self, tenant_name: str, quota_per_hour: int) -> TenantModel:
        tenant = await self._get_tenant_by_name(tenant_name)
        tenant.quota_per_hour = quota_per_hour
        await self._session.flush()
        return tenant

    async def set_concurrent_research(
        self, tenant_name: str, concurrent_research: int
    ) -> TenantModel:
        tenant = await self._get_tenant_by_name(tenant_name)
        tenant.concurrent_research = concurrent_research
        await self._session.flush()
        return tenant

    async def set_llm_provider_config(
        self, tenant_name: str, config: Optional[dict[str, Any]]
    ) -> TenantModel:
        tenant = await self._get_tenant_by_name(tenant_name)
        tenant.llm_provider_config = config
        await self._session.flush()
        return tenant

    async def get_tenant(self, tenant_name: str) -> TenantModel:
        return await self._get_tenant_by_name(tenant_name)

    async def list_tenants(self) -> list[TenantModel]:
        result = await self._session.execute(select(TenantModel).order_by(TenantModel.name))
        return list(result.scalars().all())

    async def _get_tenant_by_name(self, name: str) -> TenantModel:
        result = await self._session.execute(
            select(TenantModel).where(TenantModel.name == name)
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise TenantNotFoundError(name)
        return tenant
