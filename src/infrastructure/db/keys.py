"""API key generation/hashing shared by auth resolution and the admin bot.

Raw keys are never persisted — only their sha256 hex digest lives in
``api_keys.key_hash``. The raw value is shown to the admin exactly once, at
issuance time, in the bot's reply.
"""

from __future__ import annotations

import hashlib
import secrets

_KEY_PREFIX = "atk"


def generate_raw_key() -> str:
    """A new bearer key: ``atk_<43 url-safe chars>`` (256 bits of entropy)."""
    return f"{_KEY_PREFIX}_{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()
