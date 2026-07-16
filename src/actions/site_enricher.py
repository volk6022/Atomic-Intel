import asyncio
import random
from typing import Optional, List
from urllib.parse import urljoin, urlparse

from src.domain.models.enriched_content import EnrichedContent
from src.domain.utils.content_cleaner import (
    clean_html_content,
    html_to_text,
    count_words,
    truncate_content,
)
from src.infrastructure.browser.user_agent_pool import UserAgentPool
from src.infrastructure.browser.pool_manager import pool_manager
from src.infrastructure.browser.proxy_provider import proxy_provider
from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)

# Heavy resource types to abort: they carry no text and dominate page weight
# (-40-95% bytes on directory/org pages, verified in optimize-scrape/FINDINGS.md).
_BLOCK_RESOURCE_TYPES = {"image", "media", "font"}


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _block_skip_domains() -> set[str]:
    return {
        d.strip().lower()
        for d in settings.RESEARCH_BROWSER_BLOCK_SKIP_DOMAINS.split(",")
        if d.strip()
    }


class SiteEnrichAction:
    def __init__(self):
        self.pool_manager = pool_manager
        self.user_agent_pool = UserAgentPool()
        self.max_words = 500

    async def execute(
        self,
        url: str,
        crawl_about: bool = False,
        crawl_services: bool = False,
    ) -> EnrichedContent:
        proxy = proxy_provider.get_proxy() or None
        # exposed for callers (scrape_url perf telemetry: per-port attribution)
        self.last_proxy = proxy["server"] if proxy else None
        user_agent = self.user_agent_pool.get_user_agent()
        logger.info(
            "Starting site enrichment for: %s (proxy=%s)",
            url, self.last_proxy,
        )

        context = await self.pool_manager.create_context(
            user_agent=user_agent,
            stealth=True,
            proxy=proxy,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
        )

        pages_crawled = [url]
        all_content_parts = []

        try:
            # Resource-blocking: abort images/media/fonts to cut page weight. Skip
            # social SPAs (vk/instagram/...), where aborting trips anti-bot and the
            # page reloads HEAVIER (verified: vk 0.1→3 MB) than leaving it alone.
            host = _host(url)
            block = (
                settings.RESEARCH_BROWSER_BLOCK_RESOURCES
                and not any(host == d or host.endswith("." + d) for d in _block_skip_domains())
            )
            if block:
                async def _route(route, request):
                    if request.resource_type in _BLOCK_RESOURCE_TYPES:
                        try:
                            await route.abort()
                        except Exception:
                            pass
                    else:
                        try:
                            await route.continue_()
                        except Exception:
                            pass
                await context.route("**/*", _route)

            page = await context.new_page()

            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(random.uniform(0.5, 1.5))

            main_content = await self._extract_main_content(page)
            if main_content:
                all_content_parts.append(main_content)

            if crawl_about:
                about_url = await self._find_about_page(page, url)
                if about_url and about_url != url:
                    try:
                        await page.goto(
                            about_url, wait_until="domcontentloaded", timeout=10000
                        )
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        about_content = await self._extract_main_content(page)
                        if about_content:
                            all_content_parts.append(about_content)
                            pages_crawled.append(about_url)
                    except Exception as e:
                        logger.debug(f"Failed to crawl about page: {e}")

            if crawl_services:
                services_url = await self._find_services_page(page, url)
                if services_url and services_url not in pages_crawled:
                    try:
                        await page.goto(
                            services_url, wait_until="domcontentloaded", timeout=10000
                        )
                        await asyncio.sleep(random.uniform(0.3, 0.8))
                        services_content = await self._extract_main_content(page)
                        if services_content:
                            all_content_parts.append(services_content)
                            pages_crawled.append(services_url)
                    except Exception as e:
                        logger.debug(f"Failed to crawl services page: {e}")

            combined_text = "\n\n".join(all_content_parts)
            was_truncated = len(combined_text.split()) > self.max_words
            truncated_text = truncate_content(combined_text, max_words=self.max_words)
            word_count = count_words(truncated_text)

            logger.info(f"Extracted {word_count} words from {len(pages_crawled)} pages")

            return EnrichedContent(
                url=url,
                text=truncated_text,
                word_count=word_count,
                truncated=was_truncated,
                pages_crawled=pages_crawled if len(pages_crawled) > 1 else None,
            )

        except Exception as e:
            logger.error(f"Site enrichment failed: {e}")
            raise
        finally:
            await context.close()

    async def _extract_main_content(self, page) -> Optional[str]:
        try:
            html = await page.content()
            cleaned = clean_html_content(html)
            text = html_to_text(cleaned)
            text = self._clean_whitespace(text)
            return text if text else None
        except Exception as e:
            logger.debug(f"Failed to extract main content: {e}")
            return None

    def _clean_whitespace(self, text: str) -> str:
        lines = text.split("\n")
        cleaned_lines = [line.strip() for line in lines if line.strip()]
        return "\n".join(cleaned_lines)

    async def _find_about_page(self, page, base_url: str) -> Optional[str]:
        about_keywords = [
            "about",
            "about-us",
            "o-nas",
            "company",
            "history",
            "who-we-are",
        ]
        return await self._find_page_by_keywords(page, base_url, about_keywords)

    async def _find_services_page(self, page, base_url: str) -> Optional[str]:
        services_keywords = [
            "services",
            "what-we-do",
            "solutions",
            "products",
            "uslugi",
            "offer",
        ]
        return await self._find_page_by_keywords(page, base_url, services_keywords)

    async def _find_page_by_keywords(
        self, page, base_url: str, keywords: List[str]
    ) -> Optional[str]:
        try:
            links = await page.query_selector_all("a[href]")
            baseparsed = urlparse(base_url)
            base_domain = f"{baseparsed.scheme}://{baseparsed.netloc}"

            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href:
                        continue

                    if href.startswith("/"):
                        full_url = urljoin(base_domain, href)
                    elif href.startswith("http"):
                        full_url = href
                    else:
                        continue

                    link_text = await link.text_content()
                    link_text_lower = (link_text or "").lower()

                    for keyword in keywords:
                        if keyword.lower() in link_text_lower:
                            return full_url
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Failed to find page by keywords: {e}")

        return None
