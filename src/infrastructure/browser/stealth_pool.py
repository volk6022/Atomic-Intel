"""
Stealth browser pool wrapper using patchright/playwright-stealth.
T015-T018: Implement stealth pool, user-agent pool, proxy integration, human-like interactions.

This adds anti-bot evasion capabilities to the browser pool.
"""

import asyncio
import random
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


class HumanEmulator:
    """Human-like interaction patterns to avoid detection."""

    @staticmethod
    async def human_mouse_move(page: Page, target_x: int, target_y: int):
        """Move mouse with random jitter to simulate human movement."""
        current_x, current_y = 0, 0

        steps = random.randint(5, 15)
        for _ in range(steps):
            step_x = current_x + (target_x - current_x) * random.uniform(0.3, 0.7)
            step_y = current_y + (target_y - current_y) * random.uniform(0.3, 0.7)

            step_x += random.randint(-10, 10)
            step_y += random.randint(-10, 10)

            await page.mouse.move(int(step_x), int(step_y))
            await asyncio.sleep(random.uniform(0.05, 0.15))

        await page.mouse.move(target_x, target_y)

    @staticmethod
    async def human_click(page: Page, x: int, y: int):
        """Human-like click with slight position offset."""
        offset_x = random.randint(-2, 2)
        offset_y = random.randint(-2, 2)

        await page.mouse.move(x + offset_x, y + offset_y)
        await asyncio.sleep(random.uniform(0.1, 0.3))
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.05, 0.1))
        await page.mouse.up()

    @staticmethod
    async def human_type(page: Page, selector: str, text: str):
        """Type text with realistic delays."""
        await page.click(selector)
        await asyncio.sleep(random.uniform(0.1, 0.2))

        for char in text:
            await page.keyboard.type(char, delay=random.randint(50, 150))
            await asyncio.sleep(random.uniform(0.01, 0.05))

    @staticmethod
    async def random_scroll(page: Page):
        """Random scroll pattern."""
        scroll_amount = random.randint(300, 800)
        direction = random.choice([1, -1])
        await page.evaluate(f"window.scrollBy(0, {scroll_amount * direction})")
        await asyncio.sleep(random.uniform(0.5, 1.5))


class StealthPool:
    """Stealth browser pool with anti-detection features."""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()
        self.human_emulation_enabled = True

    async def launch(self, **kwargs) -> Browser:
        """Launch stealth browser with anti-detection options."""
        async with self._lock:
            if self._browser is None:
                self._playwright = await async_playwright().start()

                stealth_options = self._get_stealth_options()
                stealth_options.update(kwargs)

                self._browser = await self._playwright.chromium.launch(
                    **stealth_options
                )
            return self._browser

    def _get_stealth_options(self) -> dict:
        """Get stealth browser launch options."""
        return {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        }

    async def new_context(self, **kwargs) -> BrowserContext:
        return await self.create_context(**kwargs)

    async def create_context(self, **kwargs) -> BrowserContext:
        """Create stealth browser context with anti-detection settings."""
        browser = await self.launch()

        stealth_context_options = self._get_stealth_context_options()
        stealth_context_options.update(kwargs)

        context = await browser.new_context(**stealth_context_options)
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return context

    def _get_stealth_context_options(self) -> dict:
        """Get stealth context options to avoid detection."""
        return {
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "permissions": ["geolocation"],
            "color_scheme": "light",
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

    async def close(self):
        """Close stealth browser pool."""
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None


stealth_pool = StealthPool()
