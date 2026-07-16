"""SearchClient export — backed by SearXNG.

Старый GoogleSearchClient (Playwright-based) удалён: подтверждено прогонами в
serp_experiment/ что SearXNG-pipeline (VPN + pool 20 socks5 + retries=2) даёт
~95% success rate без CAPTCHA-проблем Google'а.

Этот модуль оставлен как тонкий re-export, чтобы существующие call-site'ы
(api/routers/stateless.py, actions/research/tools.py) импортировались по
прежнему пути.
"""
from src.infrastructure.external_api.searxng_client import (
    SearXngSearchClient,
    search_client,
)

# Backward-compatible alias.
SearchClient = SearXngSearchClient

__all__ = ["SearchClient", "SearXngSearchClient", "search_client"]
