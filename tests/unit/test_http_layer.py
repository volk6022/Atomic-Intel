"""Unit tests for the async HTTP layer (antibot classification + proxy-URL build)."""

import httpx

from src.infrastructure.http import AntibotVerdict, detect_antibot
from src.infrastructure.http.rotating_client import build_proxy_url


def _resp(status=200, text="", headers=None):
    return httpx.Response(status_code=status, text=text, headers=headers or {})


def test_detect_antibot_clean():
    assert detect_antibot(_resp(200, "<html>" + "x" * 6000 + "</html>")) == AntibotVerdict.CLEAN


def test_detect_antibot_ddos_guard():
    r = _resp(200, "<html>DDoS-Guard challenge</html>", headers={"Server": "ddos-guard"})
    assert detect_antibot(r) == AntibotVerdict.DDOS_GUARD


def test_detect_antibot_cloudflare():
    r = _resp(503, "Just a moment... challenge-platform", headers={"Server": "cloudflare", "cf-ray": "abc"})
    assert detect_antibot(r) == AntibotVerdict.CLOUDFLARE


def test_detect_antibot_hard_block():
    assert detect_antibot(_resp(403, "forbidden")) == AntibotVerdict.BLOCKED


def test_build_proxy_url_with_auth():
    url = build_proxy_url({"server": "http://host:8080", "username": "u", "password": "p"})
    assert url == "http://u:p@host:8080"


def test_build_proxy_url_no_auth():
    assert build_proxy_url({"server": "http://host:8080"}) == "http://host:8080"
