"""Async HTTP layer for the monitoring/catalog scrapers.

`RotatingHTTPClient` — an async httpx client with sequential proxy rotation,
generalised from the inlined rotation logic in ``src/actions/yandex_maps.py``
and the sync ``ProxyRotatingClient`` in ``experiment_monitoring/experiment-fl/
proxy_client.py``. ``detect_antibot`` classifies a response as CLEAN / DDoS-Guard /
Cloudflare / captcha so callers can decide whether to fall back to the browser.
"""

from src.infrastructure.http.antibot import AntibotVerdict, detect_antibot
from src.infrastructure.http.rotating_client import RotatingHTTPClient

__all__ = ["RotatingHTTPClient", "detect_antibot", "AntibotVerdict"]
