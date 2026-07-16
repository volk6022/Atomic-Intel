---
created: 2026-07-16
status: draft
confidence_level: medium
---

# Atomic Intel — API Usage Guide

⚠️ **SKELETON ONLY** — This guide reflects the intended API surface for the public Atomic Intel service after the M2 control-plane lands. Sections marked `[TBD]` will be filled in after control-plane stability.

---

## Overview

**Atomic Intel** is an automated research and data enrichment service for lead generation and company intelligence. It provides:
- **Research agent**: autonomous LLM-driven web research with structured output
- **Yandex.Maps verticals**: stable parsing and enrichment of Russian business cards
- **Enrichment**: enhance company profiles with additional data
- **Monitoring**: track page changes and notify on updates
- **Catalog**: maintain curated company / lead databases

All endpoints require per-tenant API authentication and support bring-your-own LLM (BYO-LLM) per tenant.

---

## Table of Contents

1. [Authentication](#authentication)
2. [Architecture: Multi-Tenant & BYO-LLM](#architecture-multi-tenant--byo-llm)
3. [API Endpoints](#api-endpoints)
   - [Research Agent](#research-agent)
   - [Enrichment](#enrichment)
   - [Yandex.Maps](#yandexmaps)
   - [Monitoring](#monitoring)
   - [Catalog](#catalog)
   - [Health](#health)
4. [Rate Limits & Quotas](#rate-limits--quotas)
5. [Example Requests](#example-requests)

---

## Authentication

### Per-Tenant API Keys

All requests require the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-tenant-api-key" \
  https://api.atomic.example.com/research/run
```

**Key resolution:**
1. If the key matches the bootstrap key (admin), unlimited access (development only)
2. Otherwise, SHA256-hash the key and resolve against active tenants in the control plane
3. On DB error or unknown key, reject with `403 Forbidden`

**Key management:** [TBD] Control-plane admin UI for creating/rotating keys, setting quotas per tenant.

---

## Architecture: Multi-Tenant & BYO-LLM

### Multi-Tenancy

Each tenant (customer) has:
- **Dedicated quota**: research tasks/hour, concurrency limits
- **API key**: used to authenticate all requests
- **LLM provider config**: OpenAI, Anthropic, local endpoint, or Atomic-managed LLM
- **Isolation**: one tenant's research does not affect others

### Bring-Your-Own-LLM (BYO-LLM)

Instead of using Atomic's LLM, a tenant can supply their own:

```yaml
# Tenant config (control plane)
llm_provider_config:
  type: "openai"  # or "anthropic", "ollama", "vllm"
  api_key: "sk-..."
  model: "gpt-4-turbo"
  endpoint: "https://api.openai.com/v1"  # optional, for self-hosted
```

**Supported LLM providers:** [TBD] List of validated providers and configuration examples.

The research agent will use the tenant's LLM instead of Atomic's default. Costs are the tenant's responsibility.

---

## API Endpoints

### Research Agent

The autonomous research agent takes a query, searches the web via SearXNG, scrapes results, and returns structured findings via an LLM.

#### `POST /research/run`

Launch a research task. Returns a `task_id` for polling/streaming.

**Request:**
```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Find information about Acme Corp in Moscow",
    "mode": "standard",
    "max_sources": 10,
    "output_schema": {
      "type": "company_profile",
      "fields": ["name", "description", "employees", "revenue", "industries"]
    }
  }' \
  https://api.atomic.example.com/research/run
```

**Response (202 Accepted):**
```json
{
  "task_id": "research-abc123def456",
  "status": "queued",
  "created_at": "2026-07-16T10:00:00Z"
}
```

**Parameters:**
- `query` (string, required): Research question or company/person to find
- `mode` (string, default "standard"): `quick` (1–2 sources), `standard` (5–10), `deep` (10+)
- `max_sources` (int, default 10): Maximum sources to scrape
- `output_schema` (object, optional): Expected output structure (LLM will match this)
- `context` (string, optional): Extra context (e.g., "Focus on pricing and contact info")

**[TBD]** Full schema documentation and example schemas.

---

#### `GET /research/status/{task_id}`

Check status and retrieve results (once complete).

**Request:**
```bash
curl -H "X-API-Key: YOUR_KEY" \
  https://api.atomic.example.com/research/status/research-abc123def456
```

**Response (if in progress):**
```json
{
  "task_id": "research-abc123def456",
  "status": "running",
  "progress": 60,
  "started_at": "2026-07-16T10:00:00Z"
}
```

**Response (if complete):**
```json
{
  "task_id": "research-abc123def456",
  "status": "completed",
  "started_at": "2026-07-16T10:00:00Z",
  "completed_at": "2026-07-16T10:05:00Z",
  "result": {
    "name": "Acme Corp",
    "description": "Leading software company in Moscow specializing in...",
    "employees": "250–500",
    "revenue": "[UNVERIFIED]",
    "industries": ["software", "saas"],
    "sources": [
      {"url": "https://example.com", "snippet": "..."},
      {"url": "https://example2.com", "snippet": "..."}
    ]
  }
}
```

---

#### `GET /research/stream/{task_id}`

Server-Sent Events (SSE) stream for real-time progress updates.

**Request:**
```bash
curl -H "X-API-Key: YOUR_KEY" \
  https://api.atomic.example.com/research/stream/research-abc123def456
```

**Response (SSE stream):**
```
data: {"event":"started","timestamp":"2026-07-16T10:00:00Z"}

data: {"event":"search","query":"Acme Corp Moscow","results_found":87,"timestamp":"2026-07-16T10:00:05Z"}

data: {"event":"scrape","url":"https://example.com","extracted":true,"timestamp":"2026-07-16T10:00:10Z"}

data: {"event":"scrape","url":"https://example2.com","extracted":true,"timestamp":"2026-07-16T10:00:15Z"}

data: {"event":"completed","result":{...},"timestamp":"2026-07-16T10:05:00Z"}
```

---

### Enrichment

Enhance company profiles with additional data (scraped from public sources or integrated data providers).

#### `POST /enrichment/run`

[TBD] Enrichment request parameters, output fields, providers.

**Request skeleton:**
```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "company": {
      "name": "Acme Corp",
      "country": "RU",
      "city": "Moscow"
    },
    "fields_to_enrich": ["phone", "email", "website", "revenue", "employees"],
    "data_sources": ["yandex_maps", "website_scrape", "crunchbase"]
  }' \
  https://api.atomic.example.com/enrichment/run
```

**Response:** [TBD] Enriched company profile with confidence scores.

---

#### `GET /enrichment/status/{task_id}`

[TBD] Same pattern as research: poll for status and results.

---

### Yandex.Maps

Managed vertical for stable parsing of Yandex.Maps business cards (Russian companies, restaurants, services).

#### `POST /yandex-maps/search`

Search for businesses on Yandex.Maps by name, category, or location.

**Request skeleton:**
```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Кафе в Москве",
    "location": {"city": "Moscow", "radius_km": 5},
    "limit": 50
  }' \
  https://api.atomic.example.com/yandex-maps/search
```

**Response:** [TBD] List of business cards with contact info, category, ratings.

---

#### `GET /yandex-maps/{org_id}`

Fetch detailed card for a single organization (by Yandex.Maps ID).

**Request:** [TBD]

**Response:** [TBD] Full org profile: name, category, phone, website, hours, rating, photos, etc.

---

#### `POST /yandex-maps/enrich`

Enrich a company record with Yandex.Maps data (phone, website, category, coordinates).

**Request skeleton:**
```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "Acme Corp",
    "city": "Moscow"
  }' \
  https://api.atomic.example.com/yandex-maps/enrich
```

**Response:** [TBD] Matched org card + confidence.

---

### Monitoring

Track page changes and notify on updates.

#### `POST /monitoring/create`

Start monitoring a URL or set of URLs for changes.

**Request skeleton:**
```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://example.com", "https://example2.com"],
    "check_interval_hours": 24,
    "notification_url": "https://your-server.com/webhook",
    "monitor_xpath": [".contact-section", ".pricing-table"]
  }' \
  https://api.atomic.example.com/monitoring/create
```

**Response:** [TBD] Monitor ID + status.

---

#### `GET /monitoring/{monitor_id}`

Get monitor status and latest changes.

**Response:** [TBD] Last check time, diffs detected, notification history.

---

#### `POST /monitoring/{monitor_id}/stop`

Stop monitoring a URL.

---

### Catalog

Manage curated company / lead databases.

#### `POST /catalog/create`

Create a new catalog (named collection of leads/companies).

**Request skeleton:**
```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Cybersecurity Startups in Moscow",
    "description": "Leads from security conference 2026",
    "schema": {
      "type": "company",
      "fields": ["name", "website", "employees", "raising"]
    }
  }' \
  https://api.atomic.example.com/catalog/create
```

**Response:** [TBD] Catalog ID + metadata.

---

#### `POST /catalog/{catalog_id}/add`

Add records to a catalog.

**Request:** [TBD] CSV import or JSON array of records.

---

#### `GET /catalog/{catalog_id}`

Fetch catalog (paginated).

**Response:** [TBD] Catalog records + metadata.

---

### Health

#### `GET /healthz`

Basic health check (requires no auth).

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2026-07-16T10:00:00Z"
}
```

---

## Rate Limits & Quotas

### Per-Tenant Quotas

Each tenant has configurable limits (set in control plane):

| Metric | Default | Configurable |
|--------|---------|--------------|
| Research tasks / hour | 10 | Yes |
| Concurrent research | 2 | Yes |
| Enrichment tasks / hour | 20 | Yes |
| Yandex.Maps queries / hour | 50 | Yes |
| Monitoring monitors (active) | 10 | Yes |

**[TBD]** Control plane UI for tenant admins to view/adjust quotas.

### Rate-Limit Headers

Responses include quotas:

```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1626499200
```

If quota exceeded:

```
HTTP 429 Too Many Requests

{
  "error": "rate_limit_exceeded",
  "retry_after_seconds": 3600
}
```

---

## Example Requests

### Full Workflow: Research → Enrich → Monitor

**1. Launch a research task:**
```bash
TASK_ID=$(curl -s -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Artificial intelligence startups in Moscow founded 2024-2026",
    "mode": "standard"
  }' \
  https://api.atomic.example.com/research/run | jq -r '.task_id')

echo "Task ID: $TASK_ID"
```

**2. Poll for results (or use SSE stream):**
```bash
curl -H "X-API-Key: YOUR_KEY" \
  https://api.atomic.example.com/research/status/$TASK_ID
```

**3. Enrich results with Yandex.Maps:**
```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "ExampleAI",
    "city": "Moscow"
  }' \
  https://api.atomic.example.com/yandex-maps/enrich
```

**4. Create a catalog and store leads:**
```bash
CATALOG_ID=$(curl -s -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI Startups Research 2026-07",
    "schema": {"type": "company", "fields": ["name", "website", "contact"]}
  }' \
  https://api.atomic.example.com/catalog/create | jq -r '.catalog_id')

curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "records": [
      {"name": "ExampleAI", "website": "https://example.com", "contact": "hello@example.com"}
    ]
  }' \
  https://api.atomic.example.com/catalog/$CATALOG_ID/add
```

**5. Start monitoring their website:**
```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://example.com"],
    "check_interval_hours": 24,
    "notification_url": "https://your-server.com/webhook"
  }' \
  https://api.atomic.example.com/monitoring/create
```

---

## Configuration & Deployment

### Environment Variables (Service)

[TBD] Full config reference.

- `API_KEY`: Bootstrap key (admin, development only)
- `DATABASE_URL`: PostgreSQL connection
- `REDIS_URL`: Redis broker (Taskiq)
- `SEARXNG_ENDPOINT`: SearXNG instance
- `DEFAULT_LLM_PROVIDER`: Fallback LLM (if tenant has no BYO-LLM)
- `MAX_CONCURRENT_RESEARCH_TASKS`: Global concurrency (across all tenants)
- `RATE_LIMIT_DEFAULT_PER_HOUR`: Default quota per tenant

### External Dependencies

- **PostgreSQL**: Tenant registry, task metadata
- **Redis**: Taskiq broker, result cache (24h TTL)
- **SearXNG**: Web search engine (must be running)
- **LLM endpoint**: OpenAI, Anthropic, or self-hosted

---

## What's **NOT** in This Public API

The following endpoints exist in the **development/private build** but are **not exposed** in the public service:

- **Sessions API** (`/sessions`): Raw browser session DSL
- **Stateless Scraper** (`/scraper`, `/serper`): Raw URL scraping (SSRF risk)
- **WebSocket** (`/ws`): Real-time push (not multi-tenant safe)
- **MCP Server** (`/mcp`): Tool protocol (dev only)

These are stripped by the M2 control-plane build. Do not rely on them.

---

## Troubleshooting

### Common Errors

**`403 Forbidden`**: API key is invalid, unknown, or tenant is inactive.
- Check key spelling
- Verify key is active in control plane
- Request new key if expired

**`429 Too Many Requests`**: Rate limit exceeded.
- Check `X-RateLimit-Remaining` header
- Wait `Retry-After` seconds
- Request higher quota from Atomic

**`500 Internal Server Error`**: Service error.
- Check if SearXNG is reachable
- Check if Redis is running
- Check logs on service

---

## Support & Next Steps

[TBD] Support channels, SLA, escalation path.

- **Status page**: [URL]
- **Docs**: [URL]
- **Email support**: [support@atomic.example.com]
- **Slack community**: [URL]

