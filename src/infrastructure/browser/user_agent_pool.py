"""
User-Agent rotation pool.
T016: Implement User-Agent rotation pool.

This provides random User-Agent strings for each request.
"""

import random
from typing import Optional


class UserAgentPool:
    """Pool of User-Agent strings for rotation."""

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    ]

    def __init__(self, custom_agents: Optional[list[str]] = None):
        self._agents = custom_agents or self.USER_AGENTS

    def get_random_ua(self) -> str:
        """Get a random User-Agent string."""
        return random.choice(self._agents)

    def get_user_agent(self) -> str:
        """Get a random User-Agent string (alias for get_random_ua)."""
        return self.get_random_ua()

    def get_ua_for_platform(self, platform: str) -> str:
        """Get a User-Agent for specific platform (windows, mac, linux)."""
        platform_agents = {
            "windows": [ua for ua in self._agents if "Windows" in ua],
            "mac": [ua for ua in self._agents if "Mac OS X" in ua],
            "linux": [ua for ua in self._agents if "Linux" in ua],
        }
        agents = platform_agents.get(platform.lower(), self._agents)
        return random.choice(agents) if agents else self.get_random_ua()


user_agent_pool = UserAgentPool()
