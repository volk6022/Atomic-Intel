import asyncio
from typing import Optional, Dict
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from src.infrastructure.browser.stealth_pool import stealth_pool
from src.infrastructure.browser.user_agent_pool import user_agent_pool


class BrowserPoolManager:
    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._browser_headless: Optional[bool] = None
        self._lock = asyncio.Lock()

    def available_contexts(self) -> int:
        """Return count of available browser contexts."""
        return 1 if self._browser else 0

    async def get_browser(
        self, proxy: Optional[str] = None, headless: bool = True
    ) -> Browser:
        async with self._lock:
            if self._browser is None or self._browser_headless != headless:
                if self._browser:
                    await self._browser.close()
                if self._playwright:
                    await self._playwright.stop()

                self._playwright = await async_playwright().start()

                # Give the event loop a chance to process
                await asyncio.sleep(0)

                launch_options = {"headless": headless}

                if proxy:
                    launch_options["proxy"] = proxy if isinstance(proxy, dict) else {"server": proxy}

                self._browser = await self._playwright.chromium.launch(**launch_options)
                self._browser_headless = headless
            return self._browser

    async def create_context(
        self,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        stealth: bool = True,
        headless: bool = True,
        viewport: Optional[Dict[str, int]] = None,
        **kwargs,
    ) -> BrowserContext:
        if stealth:
            if not user_agent:
                user_agent = user_agent_pool.get_user_agent()

            extra = {}
            if proxy:
                extra["proxy"] = proxy if isinstance(proxy, dict) else {"server": proxy}

            return await stealth_pool.create_context(user_agent=user_agent, **extra)

        # Get browser with fresh event loop yield
        await asyncio.sleep(0)
        browser = await self.get_browser(proxy=proxy, headless=headless)

        # Another yield before creating context
        await asyncio.sleep(0)

        context_options = {}

        if user_agent:
            context_options["user_agent"] = user_agent

        if proxy:
            context_options["proxy"] = proxy if isinstance(proxy, dict) else {"server": proxy}

        if viewport:
            context_options["viewport"] = viewport

        context_options.update(kwargs)

        return await browser.new_context(**context_options)

    async def close(self):
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None


pool_manager = BrowserPoolManager()
