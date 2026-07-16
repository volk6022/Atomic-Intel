import asyncio
import sys
from fastapi import FastAPI
from contextlib import asynccontextmanager
from src.api.routers import (
    health,
    yandex_maps,
    enrichment,
    research,
    monitoring,
    catalog,
)
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.infrastructure.browser.pool_manager import pool_manager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await pool_manager.close()


# Public production build: raw scraping (stateless/sessions), the unauthenticated
# WebSocket handler and the MCP entrypoint are stripped; interactive docs and the
# OpenAPI schema are disabled so the surface is not self-describing.
app = FastAPI(
    title="Atomic Intel API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(RateLimitMiddleware)

app.include_router(health.router)
app.include_router(
    yandex_maps.router, prefix="/api/v1/yandex-maps", tags=["yandex-maps"]
)
app.include_router(enrichment.router, prefix="/api/v1", tags=["enrichment"])
app.include_router(research.router, prefix="/api/v1/research", tags=["research"])
app.include_router(monitoring.router, prefix="/api/v1/monitor", tags=["monitoring"])
app.include_router(catalog.router, prefix="/api/v1/catalog", tags=["catalog"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
