from typing import Any, Dict
from playwright.async_api import Page
from src.domain.registry.action_registry import action_registry
from src.domain.models.dsl import CommandType


@action_registry.register(CommandType.CLICK_COORD)
async def click_coord_action(page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
    x = params.get("x", 0)
    y = params.get("y", 0)
    viewport = page.viewport_size
    if viewport:
        await page.mouse.click(
            float(x) * viewport["width"], float(y) * viewport["height"]
        )
    else:
        await page.mouse.click(float(x), float(y))
    return {"status": "success"}


@action_registry.register(CommandType.TYPE)
async def type_action(page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
    selector = params.get("selector", "")
    text = params.get("text", "")
    await page.fill(selector, text)
    return {"status": "success"}
