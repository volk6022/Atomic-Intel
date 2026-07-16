from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Bootstrap/admin key — always resolves to a synthetic Principal without
    # touching Postgres (see src/api/auth.py). Real tenants come from the DB.
    API_KEY: str = "default_internal_key"
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # API Server
    PORT: int = 8000

    # --- Control-plane: tenants/keys (Postgres) ---
    DATABASE_URL: str = "postgresql+asyncpg://atomic:atomic@localhost:5432/atomic_intel"
    POSTGRES_USER: str = "atomic"
    POSTGRES_PASSWORD: str = "change_me"
    POSTGRES_DB: str = "atomic_intel"
    # How long a resolved tenant is cached in-process before the DB is re-hit.
    AUTH_CACHE_TTL_SECONDS: float = 30.0
    # Defaults used by the TG bot when issuing a new tenant (Ivan can override
    # per-tenant afterwards via /setquota, /setconcurrency).
    DEFAULT_TENANT_QUOTA_PER_HOUR: int = 500
    DEFAULT_TENANT_CONCURRENT_RESEARCH: int = 2

    # --- TG admin bot (src/bot/) ---
    BOT_TOKEN: str = ""
    ADMIN_TG_IDS: str = ""  # CSV of Telegram numeric user ids allowed to use the bot

    # Extraction Settings (e.g., Jina Reader LM)
    EXTRACTION_API_BASE: str = "http://localhost:1234/v1"
    EXTRACTION_API_KEY: str = "lm-studio"
    EXTRACTION_MODEL_NAME: str = "jina-reader-lm"

    # Orchestration Settings (reasoning/navigation)
    ORCHESTRATION_API_BASE: str = "https://api.openai.com/v1"
    ORCHESTRATION_API_KEY: str = "sk-..."
    ORCHESTRATION_MODEL_NAME: str = "gpt-4o"

    # Scraper Settings
    BROWSER_TIMEOUT: int = 30000  # 30 seconds
    SESSION_INACTIVITY_TIMEOUT: int = 600  # 10 minutes
    MAX_CONCURRENT_RESEARCH_TASKS: int = Field(default=5, ge=1, le=100)

    # Rate Limiting Settings
    # NOTE: no longer read by src/api/middleware/rate_limit.py (bug C-01 fix —
    # the middleware now enforces per-tenant quota_per_hour, not a per-target-
    # domain rule keyed on the API's own inbound Host header). Kept as a
    # reserved knob for a future *outbound* politeness limiter in the
    # scraping/action layer, which is a distinct concern from caller quota.
    RATE_LIMIT_YANDEX_PER_HOUR: int = 30
    # Fallback quota for the bootstrap admin key (see API_KEY above) and the
    # default ceiling the rate-limit middleware falls back to if a rule ever
    # can't resolve a tenant-specific number.
    RATE_LIMIT_DEFAULT_PER_HOUR: int = 1000

    # Monitoring / Catalog scrapers (promoted from experiment_monitoring/)
    # Most sources (fl/kwork/superjob/habr/zarplata) pass anti-bot via httpx-direct;
    # enable proxy rotation for the ones that need it (hh). See RotatingHTTPClient.
    MONITOR_USE_PROXY: bool = False
    MONITOR_HTTP_TIMEOUT: float = 25.0       # read/pool timeout for the httpx path
    MONITOR_MAX_PROXY_RETRIES: int = 12      # proxies to rotate through before failing

    # Scheduled monitor sweep (Phase 3)
    MONITOR_SOURCES: str = ""                # CSV of source keys; "" = all registered
    MONITOR_COLLECT_LIMIT: int = 40          # items per source per sweep
    MONITOR_INTERVAL_MINUTES: int = 15       # sweep cadence (cron */N when N < 60)
    # CSV of IT keywords; a collected item passes if its title/desc contains any.
    # "" = no filtering (keep every item).
    MONITOR_KEYWORDS: str = (
        "python,django,fastapi,flask,backend,ml,machine learning,data,parsing,парсинг,"
        "разработчик,программист,бот,bot,автоматизация,api,нейросет,ai"
    )
    MONITOR_SEEN_TTL_DAYS: int = 7           # sliding TTL on the per-source seen set

    # SearXNG SERP Backend
    # Подтверждено прогонами в serp_experiment/REPORT_searxng.md:
    # VPN на хосте + pool 20 socks5 + retries=2 → 95.3% success.
    # См. infra/searxng/ для docker-compose и settings.yml.
    SEARXNG_BASE_URL: str = "http://localhost:8080"
    SEARXNG_TIMEOUT: float = 30.0       # общий http-timeout клиента
    SEARXNG_MAX_RETRIES: int = 3        # +1 первая попытка = всего 4 attempts
    SEARXNG_RETRY_DELAY: float = 0.5
    SEARXNG_MIN_ORGANIC: int = 1        # минимум organic для счёта «успех» (иначе retry)

    # Research Agent (flat-loop, simple_agent_v2.1 port)
    # Defaults mirror the production v2.1 values from the batch run. Tunable via .env.
    RESEARCH_COMPACT_TRIGGER_TOKENS: int = 50_000   # auto-compaction trigger (отд. от mode token_budget)
    RESEARCH_MAX_COMPACTIONS: int = 3
    RESEARCH_SOFT_ELIDE_AFTER_TURNS: int = 4
    RESEARCH_REFRASER_EVERY_N_SERPS: int = 15
    RESEARCH_DOMAIN_FAIL_THRESHOLD: int = 3
    RESEARCH_LLM_TIMEOUT_S: float = 180.0
    RESEARCH_SCRAPE_BUDGET_CHARS: int = 3500
    RESEARCH_CRITIC_PASS_SCORE: float = 8.5
    RESEARCH_MAX_SUBMIT_REJECTS: int = 2
    RESEARCH_DEFAULT_LANGUAGE: str = "ru"
    RESEARCH_DEFAULT_SERP_K: int = 6
    # CSV of domains never auto-blocked even after repeated scrape failures (key infra).
    RESEARCH_DOMAINS_NEVER_BLOCK: str = (
        "yandex.ru,yandex.com,2gis.ru,hh.ru,spb.hh.ru,superjob.ru,vk.com,"
        "t.me,telegram.me,rusprofile.ru,fparf.ru,checko.ru,zoon.ru"
    )
    # Scrape-cost optimization (see optimize-scrape/FINDINGS.md + scale_test/).
    # Domains whose server-rendered HTML carries the content → fetch via httpx
    # (gzip, no browser) instead of Playwright. Verified at scale: 90-100% content
    # success, 15-40x fewer bytes. VK/2gis deliberately EXCLUDED (return stubs).
    RESEARCH_HTTPX_SSR_ALLOWLIST: str = (
        "t.me,telegram.me,hh.ru,zoon.ru,prodoctorov.ru,rusprofile.ru,"
        "rubrikator.org,orgzz.ru,spravker.ru"
    )
    # Per-domain scrape cap PER ORG run — stops the agent burrowing one site ×5-9.
    RESEARCH_SCRAPE_DOMAIN_VISIT_CAP: int = 3
    # In-browser resource blocking (abort image/media/font) on the Playwright path.
    RESEARCH_BROWSER_BLOCK_RESOURCES: bool = True
    # Hosts where resource-blocking backfires (anti-bot serves a heavy challenge) —
    # skip blocking for these social SPAs.
    RESEARCH_BROWSER_BLOCK_SKIP_DOMAINS: str = "vk.com,instagram.com,facebook.com,ok.ru"
    RESEARCH_PROMPTS_PATH: str = "src/actions/research/research_agent_prompts.yaml"

    # --- M3: LLM-availability gate + durable research store ---
    # Supervisor drain-loop cadence (how often the worker re-probes endpoints
    # that currently have tasks parked in `queued_waiting_llm`).
    LLM_HEALTH_POLL_INTERVAL_SECONDS: float = 30.0
    # Per-probe timeout — a hung/unresponsive LLM must not block the poller.
    LLM_HEALTH_PING_TIMEOUT_SECONDS: float = 5.0
    # Pre-flight checks (one per task, before the agent runs) share a single
    # probe per endpoint within this window instead of hitting the LLM once
    # per task when many tasks queue up behind the same endpoint.
    LLM_HEALTH_PROBE_CACHE_SECONDS: float = 15.0
    # Durable disk fallback for completed ResearchReports, written alongside
    # the 24h-TTL Redis copy so GET /research/status/{id} still resolves after
    # Redis evicts it. Relative to cwd (repo root locally, /app in Docker);
    # override to an absolute path (e.g. /data/research) when mounting a
    # shared volume between the api and worker containers.
    RESEARCH_STORE_DIR: str = "data/research"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
