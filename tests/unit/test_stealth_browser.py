"""
Unit test for stealth browser.
T013: Write failing unit test for stealth browser.

This test MUST fail before implementation (TDD requirement).
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock


@pytest.mark.asyncio
async def test_stealth_pool_module_exists():
    """Stealth pool module should exist in infrastructure."""
    from src.infrastructure.browser import stealth_pool as mod

    assert mod is not None, "stealth_pool module must exist"
    assert hasattr(mod, "StealthPool"), "stealth_pool must export StealthPool class"


@pytest.mark.asyncio
async def test_stealth_pool_has_launch_method():
    """Stealth pool should have launch method."""
    from src.infrastructure.browser.stealth_pool import StealthPool

    pool = StealthPool()
    assert hasattr(pool, "launch"), "StealthPool missing launch method"
    assert callable(pool.launch), "launch must be callable"


@pytest.mark.asyncio
async def test_stealth_pool_sets_stealth_options():
    """Stealth pool should set stealth browser options."""
    from src.infrastructure.browser.stealth_pool import StealthPool

    pool = StealthPool()

    options = pool._get_stealth_options()
    assert "args" in options, "Stealth options must include args"
    assert any("AutomationControlled" in arg for arg in options["args"]), (
        "Stealth options must disable AutomationControlled flag"
    )
    assert options.get("headless") is True, "Default should be headless mode"
    assert "--no-sandbox" in options["args"], "Should include no-sandbox for stability"


@pytest.mark.asyncio
async def test_stealth_pool_human_emulation_enabled():
    """Stealth pool should have human_emulation_enabled flag."""
    from src.infrastructure.browser.stealth_pool import StealthPool

    pool = StealthPool()
    assert hasattr(pool, "human_emulation_enabled"), (
        "StealthPool must have human_emulation_enabled attribute"
    )
    assert pool.human_emulation_enabled is True, (
        "Human emulation should be enabled by default"
    )


@pytest.mark.asyncio
async def test_stealth_context_options_includes_viewport():
    """Stealth pool context options must include viewport settings."""
    from src.infrastructure.browser.stealth_pool import StealthPool

    pool = StealthPool()
    context_options = pool._get_stealth_context_options()

    assert "viewport" in context_options, "Context options must include viewport"
    assert "width" in context_options["viewport"], "Viewport must have width"
    assert "height" in context_options["viewport"], "Viewport must have height"
    assert context_options["viewport"]["width"] > 0, "Viewport width must be positive"
    assert context_options["viewport"]["height"] > 0, "Viewport height must be positive"


@pytest.mark.asyncio
async def test_stealth_context_options_includes_locale():
    """Stealth pool context options must include locale settings."""
    from src.infrastructure.browser.stealth_pool import StealthPool

    pool = StealthPool()
    context_options = pool._get_stealth_context_options()

    assert "locale" in context_options, "Context options must include locale"
    assert context_options["locale"] == "en-US", "Default locale should be en-US"


@pytest.mark.asyncio
async def test_user_agent_pool_module_exists():
    """User agent pool module should exist."""
    from src.infrastructure.browser import user_agent_pool as mod

    assert mod is not None, "user_agent_pool module must exist"
    assert hasattr(mod, "UserAgentPool"), (
        "user_agent_pool must export UserAgentPool class"
    )


@pytest.mark.asyncio
async def test_user_agent_pool_has_get_random_ua_method():
    """User agent pool should have get_random_ua method."""
    from src.infrastructure.browser.user_agent_pool import UserAgentPool

    pool = UserAgentPool()
    assert hasattr(pool, "get_random_ua"), "UserAgentPool missing get_random_ua method"
    assert callable(pool.get_random_ua), "get_random_ua must be callable"


@pytest.mark.asyncio
async def test_user_agent_pool_returns_valid_ua_string():
    """User agent pool must return valid Mozilla-based UA strings."""
    from src.infrastructure.browser.user_agent_pool import UserAgentPool

    pool = UserAgentPool()
    ua = pool.get_user_agent()

    assert isinstance(ua, str), "get_user_agent must return string"
    assert len(ua) > 20, "UA string must be substantial"
    assert "Mozilla" in ua or "Chrome" in ua or "Firefox" in ua, (
        "UA should be Mozilla-based browser string"
    )


@pytest.mark.asyncio
async def test_user_agent_pool_has_multiple_agents():
    """User agent pool must have multiple agents for rotation."""
    from src.infrastructure.browser.user_agent_pool import UserAgentPool

    pool = UserAgentPool()
    agents = pool._agents

    assert len(agents) >= 5, f"Should have at least 5 agents, got {len(agents)}"
    assert len(set(agents)) == len(agents), "Agents must be unique"


@pytest.mark.asyncio
async def test_user_agent_pool_platform_filter():
    """User agent pool must filter by platform correctly."""
    from src.infrastructure.browser.user_agent_pool import UserAgentPool

    pool = UserAgentPool()

    windows_ua = pool.get_ua_for_platform("windows")
    assert "Windows" in windows_ua or "Win64" in windows_ua, (
        "Windows platform filter should return Windows UA"
    )

    mac_ua = pool.get_ua_for_platform("mac")
    assert "Mac OS X" in mac_ua or "Macintosh" in mac_ua, (
        "Mac platform filter should return Mac UA"
    )

    linux_ua = pool.get_ua_for_platform("linux")
    assert "Linux" in linux_ua or "X11" in linux_ua, (
        "Linux platform filter should return Linux UA"
    )


@pytest.mark.asyncio
async def test_human_emulator_exists():
    """HumanEmulator class must exist for human-like interaction patterns."""
    from src.infrastructure.browser.stealth_pool import HumanEmulator

    assert hasattr(HumanEmulator, "human_mouse_move"), (
        "HumanEmulator must have human_mouse_move method"
    )
    assert hasattr(HumanEmulator, "human_click"), (
        "HumanEmulator must have human_click method"
    )
    assert hasattr(HumanEmulator, "human_type"), (
        "HumanEmulator must have human_type method"
    )
    assert hasattr(HumanEmulator, "random_scroll"), (
        "HumanEmulator must have random_scroll method"
    )


@pytest.mark.asyncio
async def test_stealth_pool_close_method():
    """Stealth pool must have close method for cleanup."""
    from src.infrastructure.browser.stealth_pool import StealthPool

    pool = StealthPool()
    assert hasattr(pool, "close"), "StealthPool must have close method"
    assert callable(pool.close), "close must be callable"


@pytest.mark.asyncio
async def test_stealth_pool_create_context_method():
    """Stealth pool must have create_context method."""
    from src.infrastructure.browser.stealth_pool import StealthPool

    pool = StealthPool()
    assert hasattr(pool, "create_context"), (
        "StealthPool must have create_context method"
    )
    assert callable(pool.create_context), "create_context must be callable"
