# CLAUDE.md — Atomic Intel (prod)

Карта кода для LLM-агентов и контрибьюторов. Это **публичный прод-репозиторий** с
урезанным функционалом. Полная dev-версия — приватный upstream
`Atomic-Scraper-Service`; прод генерируется из него механически (strip-скрипт, M1).

## Что это

FastAPI-сервис автоматизации: скрейпинг, обогащение данных (enrichment), мониторинг
страниц и **автономный research-агент** с tool-calling к LLM. Очередь — Taskiq поверх
Redis; браузер — Playwright (пул); поиск — SearXNG (`infra/searxng/`).

## Карта кода (`src/`)

```
src/
├── api/
│   ├── main.py            # FastAPI-энтрипоинт; условная регистрация роутеров
│   ├── auth.py            # X-API-Key gate  (M2: резолв ключа → тенант)
│   ├── middleware/        # rate_limit (token-bucket; M2: ключевать по api-key, не Host)
│   ├── routers/
│   │   ├── research.py    # [PUBLIC] POST /research/run, GET /research/status/{id}, /stream
│   │   ├── yandex_maps.py # [PUBLIC] управляемая вертикаль Яндекс.Карт
│   │   ├── enrichment.py  # [PUBLIC] обогащение карточек
│   │   ├── monitoring.py  # [PUBLIC] мониторинг страниц
│   │   ├── catalog.py     # [PUBLIC] каталог
│   │   ├── health.py      # [PUBLIC] /healthz
│   │   ├── sessions.py    # [DEV-ONLY] сырой DSL браузер-сессий → стрип в проде (M2)
│   │   └── stateless.py   # [DEV-ONLY] /scraper, /serper raw-URL (SSRF) → стрип (M2)
│   └── websockets/        # [DEV-ONLY] unauth WS → стрип в проде (M2)
├── actions/
│   ├── research/          # агент: agent.py (run_research), tools.py (web_search/scrape_url), http_fetch.py
│   ├── site_enricher.py   # SiteEnrichAction — ИСПОЛЬЗУЕТСЯ research, НЕ удалять
│   ├── yandex_maps.py     # _httpx_proxy / _mark_proxy_dead — пул прокси, НЕ удалять
│   ├── catalog/  monitoring/
├── core/                  # config.py (Settings), общие утилиты
├── domain/                # models/, registry/, utils/ — доменные схемы карточек
└── infrastructure/
    ├── browser/           # Playwright-пул, stealth
    ├── external_api/      # search_client.py (SearXNG) — НЕ удалять
    ├── http/              # httpx SSR-фетчеры
    ├── queue/             # Taskiq-таски (research_task и др.)
    ├── rate_limiter/      # token_bucket.py
    └── tasks/             # research_store.py (Redis 24h TTL; M3: durable на диск)
```

## Границы прод/дев (важно для агентов)

Публичный прод **не выставляет** сырые скрейпер-эндпоинты. Research-агент от них НЕ
зависит: `research/tools.py` вызывает только `web_search()` (→ SearXNG `search_client`)
и `scrape_url()` (→ `SiteEnrichAction` / `http_fetch`). Поэтому стрип роутеров
`sessions`/`stateless`/`websockets`/`mcp_server` **не ломает** research. Не возвращай
эти роутеры в прод без явного решения.

## Запуск (Docker)

```bash
cp .env.example .env      # заполнить ключи/эндпоинты
docker compose build && docker compose up -d
```

Внешние зависимости: Redis, SearXNG (`infra/searxng/`), LLM-эндпоинт (OpenAI-совместимый).
Кэпы прод-нагрузки: пул браузеров и `MAX_CONCURRENT_RESEARCH_TASKS` — держать низкими на 16 ГБ.

## Правила для агентов

1. Работаем в прод-клоне; фичи полного функционала — в приватном upstream, не здесь.
2. Секреты только через `.env` (в `.gitignore`); в код/конфиги не хардкодить.
3. Поток изменений: issue → branch → PR → ревью владельца (см. `contribute.md`).
