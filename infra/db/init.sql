-- Atomic Intel control-plane schema: tenants + api_keys.
--
-- Mounted read-only into the postgres container's docker-entrypoint-initdb.d/
-- (see docker-compose.yml). Postgres only runs *.sql files found there on the
-- FIRST boot of a fresh data volume — this is a bootstrap script, not a
-- migration tool. There is no Alembic in this repo yet (deliberately not
-- introduced here — see M2 plan notes); if the schema needs to evolve after
-- go-live, add hand-written `ALTER TABLE` scripts here or introduce Alembic
-- at that point.
--
-- Design: one row per tenant carries its quota/concurrency/BYO-LLM config
-- directly (no separate "plan" table — not needed at this scale). `api_keys`
-- is a thin join table so a tenant can hold multiple keys (rotation) and a
-- revoked key does not require touching the tenant row.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 TEXT NOT NULL UNIQUE,
    active               BOOLEAN NOT NULL DEFAULT TRUE,
    -- Requests/hour enforced by src/api/middleware/rate_limit.py (keyed on
    -- this tenant's id, fixing bug C-01 which keyed on the API's own Host header).
    quota_per_hour       INTEGER NOT NULL DEFAULT 500,
    -- Concurrent /research/run tasks enforced by src/infrastructure/tasks/research_store.py.
    concurrent_research  INTEGER NOT NULL DEFAULT 2,
    -- BYO-LLM: {"base_url": ..., "api_key": ..., "model": ...}. NULL = fall
    -- back to the global ORCHESTRATION_* settings (see src/infrastructure/external_api/facade.py).
    llm_provider_config  JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- sha256(raw key), hex. Raw keys are never stored — only shown once at
    -- issuance time (TG bot /newkey response).
    key_hash      TEXT NOT NULL UNIQUE,
    tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_id ON api_keys (tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash_active ON api_keys (key_hash) WHERE active;
