from typing import Any, Dict
import base64
from playwright.async_api import Page
from src.domain.registry.action_registry import action_registry
from src.domain.models.dsl import CommandType


@action_registry.register(CommandType.SCREENSHOT)
async def screenshot_action(page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
    screenshot = await page.screenshot()
    return {"status": "success", "data": base64.b64encode(screenshot).decode()}
