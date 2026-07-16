import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from src.actions.navigation import goto_action, scroll_action
from src.domain.registry.action_registry import ActionRegistry
from src.domain.models.dsl import CommandType


@pytest.mark.asyncio
async def test_goto_action_returns_success():
    """goto_action must return status=success on valid navigation."""
    page = MagicMock()
    page.goto = AsyncMock()

    result = await goto_action(page, {"url": "https://example.com"})
    assert result["status"] == "success"
    page.goto.assert_called_once_with("https://example.com")


@pytest.mark.asyncio
async def test_goto_action_extracts_url_from_params():
    """goto_action must extract URL from params dict."""
    page = MagicMock()
    page.goto = AsyncMock()

    await goto_action(page, {"url": "https://test.com/path"})
    page.goto.assert_called_once_with("https://test.com/path")


@pytest.mark.asyncio
async def test_scroll_action_returns_success():
    """scroll_action must return status=success."""
    page = MagicMock()
    page.evaluate = AsyncMock()

    result = await scroll_action(page, {"direction": "down", "amount": 500})
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_scroll_action_defaults_to_down():
    """scroll_action must default to down direction."""
    page = MagicMock()
    page.evaluate = AsyncMock()

    await scroll_action(page, {})
    call_arg = page.evaluate.call_args[0][0]
    assert "window.scrollBy(0, 500)" in call_arg


def test_action_registry_register_and_get():
    """ActionRegistry must register and retrieve actions correctly."""
    registry = ActionRegistry()

    def mock_action(page, params):
        return {"status": "ok"}

    registry.register(CommandType.GOTO)(mock_action)

    retrieved = registry.get_action(CommandType.GOTO)
    assert retrieved is not None, "Registered action should be retrievable"
    assert retrieved == mock_action, "Retrieved action should match registered"


def test_action_registry_returns_none_for_unknown():
    """ActionRegistry must return None for unregistered command types."""
    registry = ActionRegistry()

    result = registry.get_action(CommandType.YANDEX_MAPS_EXTRACT)
    assert result is None, "Unknown command types should return None"


def test_action_registry_register_multiple_commands():
    """ActionRegistry must handle multiple command registrations."""
    registry = ActionRegistry()

    def mock_goto(page, params):
        return {"type": "goto"}

    def mock_click(page, params):
        return {"type": "click"}

    registry.register(CommandType.GOTO)(mock_goto)
    registry.register(CommandType.CLICK_COORD)(mock_click)

    goto_action = registry.get_action(CommandType.GOTO)
    click_action = registry.get_action(CommandType.CLICK_COORD)

    assert goto_action is not None, "GOTO action should be registered"
    assert click_action is not None, "CLICK_COORD action should be registered"
    assert goto_action != click_action, "Different actions should be distinct"


def test_command_type_enum_has_required_values():
    """CommandType enum must have all required command types."""
    required_types = [
        "GOTO",
        "CLICK_COORD",
        "CLICK_OMNI",
        "TYPE",
        "SCROLL",
        "SCREENSHOT",
        "EXTRACT_JINA",
        "YANDEX_MAPS_EXTRACT",
    ]

    for cmd_type in required_types:
        assert hasattr(CommandType, cmd_type), f"CommandType must have {cmd_type}"


def test_command_type_is_string_enum():
    """CommandType must be a string enum for serialization."""
    assert CommandType.GOTO == "goto", "CommandType values must be strings"
    assert isinstance(CommandType.YANDEX_MAPS_EXTRACT.value, str), (
        "Enum values must be strings"
    )


def test_action_registry_singleton_exists():
    """action_registry singleton must be importable."""
    from src.domain.registry.action_registry import action_registry

    assert action_registry is not None, "action_registry singleton must exist"
    assert isinstance(action_registry, ActionRegistry), (
        "Must be ActionRegistry instance"
    )


def test_goto_action_is_registered_in_registry():
    """goto_action must be registered in action_registry."""
    from src.domain.registry.action_registry import action_registry

    action = action_registry.get_action(CommandType.GOTO)
    assert action is not None, "GOTO action should be registered"


def test_scroll_action_is_registered_in_registry():
    """scroll_action must be registered in action_registry."""
    from src.domain.registry.action_registry import action_registry

    action = action_registry.get_action(CommandType.SCROLL)
    assert action is not None, "SCROLL action should be registered"
