# SearXNG SERP Backend

Production-инстанс SearXNG для `Atomic-Scraper-Service`. Используется
клиентом `src/infrastructure/external_api/searxng_client.py` и проксируется
через `POST /serper` API endpoint + research-agent's `web_search` tool.

## Откуда взялась эта конфигурация

В `serp_experiment/` проведено 10 длинных прогонов (см.
`serp_experiment/REPORT_searxng.md`). Подтверждено:

| Конфигурация | Success rate |
|---|---:|
| **VPN + pool 20 socks5 + retries=2** (эта) | **95.3%** |
| VPN + single sticky 30min IP | 99.0% |
| Pool 20 + retries=2 БЕЗ VPN | 89.0% |
| Pool 20 БЕЗ retries и БЕЗ VPN | ~72% |

Pool из 20 выбран вместо single sticky потому что у sticky IP периодически
случаются «грязные» провалы — pool с retry размывает риск.

## Предусловие: VPN на хосте

**Без VPN success rate ~22%**: Google rate-limit'ит резидентные socks5
по abuse-флагам. VPN добавляет +73 п.п. — это решающий фактор, не cosmetic.

Поднимай свой обычный WireGuard / OpenVPN / коммерческий клиент **на хосте**,
не в Docker. Контейнер ходит наружу через `host.docker.internal:host-gateway`
→ socks5-proxy → VPN-туннель хоста.

## Запуск

```bash
# 1. Поднять VPN на хосте (любой клиент). Проверить:
curl -s https://api.ipify.org   # должен показать VPN-IP, не свой

# 2. Поднять SearXNG
cd infra/searxng
docker compose up -d

# 3. Smoke test
curl "http://localhost:8080/search?q=test&format=json" | jq '.results | length'
# → ожидаемо ≥5
```

## Интеграция в код

`src/core/config.py`:

```python
SEARXNG_BASE_URL: str = "http://localhost:8080"
SEARXNG_TIMEOUT: float = 30.0
SEARXNG_MAX_RETRIES: int = 2           # +1 первая = 3 attempts
SEARXNG_RETRY_DELAY: float = 0.5
SEARXNG_MIN_ORGANIC: int = 1
```

Все ручки оверрайдятся через `.env` (см. `pydantic-settings`).

Call-site'ы:
- `src/api/routers/stateless.py` — `POST /serper`
- `src/actions/research/tools.py` — `@tool web_search` для research-agent'а

Оба используют один и тот же singleton `search_client` из
`src/infrastructure/external_api/search_client.py` (re-export
`SearXngSearchClient`).

## Конфигурация SearXNG

`searxng/settings.yml` содержит:

- `outgoing.proxies.all://` — pool из 20 `socks5h://...@np.puls-proxy.com:11000-11009`
  (10 `cr.ru` + 10 `cr.pl`, sessttl.10 минут). SearXNG ротирует round-robin'ом.
- `outgoing.request_timeout: 8.0`, `max_request_timeout: 12.0`,
  `extra_proxy_timeout: 5` — выверено экспериментом.
- Выключены engines: `brave`, `startpage`, `karmasearch`, `karmasearch videos`,
  `ahmia`, `torch` — они не дают результатов и только тянут timeout.

Если нужно поменять proxy-провайдер — правишь `outgoing.proxies.all://`,
делаешь `docker compose restart searxng`.

## Что не входит в этот deployment

В `serp_experiment/repos/searxng-deploy/` есть дополнительные probe-инстансы
(`searxng-probe-1..4`) для proxy-router'а. Здесь они НЕ включены — это часть
research-эксперимента. Если когда-нибудь будем выкатывать proxy_router в
prod, переносим их отдельно.
