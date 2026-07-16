from typing import Optional, List
from pathlib import Path
from urllib.parse import urlparse


class ProxyProvider:
    def __init__(self, proxy_file: str = "proxies.txt"):
        self.proxy_file = Path(proxy_file)
        self._proxies: List[str] = []
        self._idx = 0
        self._load_proxies()

    def _load_proxies(self):
        if self.proxy_file.is_file():
            with open(self.proxy_file, "r") as f:
                self._proxies = [line.strip() for line in f if line.strip()]

    def get_proxy(self) -> Optional[dict]:
        if not self._proxies:
            return None
        # Chromium does not support SOCKS5 proxy authentication — use HTTP only
        http_proxies = [p for p in self._proxies if p.startswith("http://")]
        pool = http_proxies if http_proxies else self._proxies
        raw = pool[self._idx % len(pool)]
        self._idx += 1
        parsed = urlparse(raw)
        result: dict = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username:
            result["username"] = parsed.username
        if parsed.password:
            result["password"] = parsed.password
        return result


proxy_provider = ProxyProvider()
