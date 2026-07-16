from typing import Optional


class RedisUnavailableError(Exception):
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = "REDIS_UNAVAILABLE"
        self.details = details or {}
