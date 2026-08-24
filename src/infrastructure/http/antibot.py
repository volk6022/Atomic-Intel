"""Anti-bot detection for the httpx path.

Ported from ``experiment_monitoring/experiment-fl/fl_httpx_test.py::detect_antibot``.
Inspects response headers + body for DDoS-Guard / Cloudflare / JS-challenge / captcha
signals and returns a coarse verdict. Callers (``BaseSourceScraper.fetch``) treat any
non-CLEAN verdict — or a hard block status — as a trigger to fall back to the browser.
"""

from __future__ import annotations

from enum import Enum

import httpx


class AntibotVerdict(str, Enum):
    CLEAN = "CLEAN"
    DDOS_GUARD = "DDOS-GUARD"
    CLOUDFLARE = "CLOUDFLARE"
    CHALLENGE = "CHALLENGE"       # generic JS challenge / captcha, vendor unknown
    BLOCKED = "BLOCKED"           # hard block status (403/429/503) with no clean body


# Statuses that mean "the origin refused us", not "no such page".
BLOCK_STATUSES = frozenset({403, 429, 503})


def detect_antibot(resp: httpx.Response) -> AntibotVerdict:
    """Classify an httpx response. CLEAN means the body is usable as-is."""
    headers = {k.lower(): v.lower() for k, v in resp.headers.items()}
    server = headers.get("server", "")
    set_cookie = headers.get("set-cookie", "")

    # Body is only cheaply available for text responses; guard against binary.
    try:
        body = resp.text.lower()
    except Exception:
        body = ""
    body_head = body[:20_000]  # challenge markers live near the top

    # --- DDoS-Guard ---------------------------------------------------------
    if (
        "ddos-guard" in server
        or "__ddg" in set_cookie
        or "ddos-guard" in body_head
    ):
        # DDoS-Guard fronts whole sites, so ``Server: ddos-guard`` and the __ddg
        # cookies ride on every response it proxies - including the ones that came
        # back perfectly fine. Flagging on the header alone sent fl.ru's every
        # detail page to a 6-10s browser render to re-fetch a 160KB page httpx had
        # already retrieved in 1.6s. The challenge itself is unmistakable: a short
        # body, a block status, or its own name in the visible markup.
        challenge_marker = "ddos-guard" in body[:4_000]
        if (
            resp.status_code in BLOCK_STATUSES
            or len(body) < 5_000
            or challenge_marker
        ):
            return AntibotVerdict.DDOS_GUARD

    # --- Cloudflare ---------------------------------------------------------
    if "cloudflare" in server or headers.get("cf-ray"):
        if (
            "cf-chl" in body_head
            or "challenge-platform" in body_head
            or "just a moment" in body_head
            or resp.status_code in BLOCK_STATUSES
        ):
            return AntibotVerdict.CLOUDFLARE

    # --- Generic challenge / captcha ---------------------------------------
    if "captcha" in body_head or "smartcaptcha" in body_head:
        return AntibotVerdict.CHALLENGE

    # --- Hard block with no usable body ------------------------------------
    if resp.status_code in BLOCK_STATUSES and len(body) < 5_000:
        return AntibotVerdict.BLOCKED

    return AntibotVerdict.CLEAN
