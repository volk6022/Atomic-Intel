from typing import Any, Dict
from playwright.async_api import Page
from src.domain.registry.action_registry import action_registry
from src.domain.models.dsl import CommandType


@action_registry.register(CommandType.GOTO)
async def goto_action(page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
    url = params.get("url", "")
    await page.goto(url)
    return {"status": "success"}


@action_registry.register(CommandType.SCROLL)
async def scroll_action(page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
    direction = params.get("direction", "down")
    amount = params.get("amount", 500)
    await page.evaluate(
        f"window.scrollBy(0, {amount if direction == 'down' else -amount})"
    )
    return {"status": "success"}
