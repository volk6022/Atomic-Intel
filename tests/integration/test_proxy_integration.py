"""
Integration test for proxy integration.
T014: Write failing contract test for proxy integration.

This test MUST fail before implementation (TDD requirement).
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock


@pytest.mark.asyncio
async def test_proxy_provider_integrated_in_pool():
    """Proxy provider should be integrated in pool manager create_context."""
    try:
        from src.infrastructure.browser.pool_manager import BrowserPoolManager

        pm = BrowserPoolManager()

        with patch.object(pm, "get_browser") as mock_browser:
            mock_ctx = AsyncMock()
            mock_browser.return_value.new_context = AsyncMock(return_value=mock_ctx)

            await pm.create_context(proxy="http://test-proxy:8080")

            call_args = mock_browser.return_value.new_context.call_args
            assert call_args is not None
            assert "proxy" in str(call_args) or call_args.kwargs.get("proxy")
    except Exception as e:
        pytest.fail(f"Proxy integration not working: {e}")


@pytest.mark.asyncio
async def test_proxy_provider_reads_from_file():
    """Proxy provider should read proxies from file."""
    try:
        from src.infrastructure.browser.proxy_provider import ProxyProvider

        provider = ProxyProvider()
        assert hasattr(provider, "get_proxy"), "ProxyProvider missing get_proxy method"
    except ImportError:
        pytest.fail("ProxyProvider does not exist")


@pytest.mark.asyncio
async def test_pool_manager_stealth_mode_passes_proxy():
    """Pool manager in stealth mode should pass proxy to stealth pool."""
    from src.infrastructure.browser.pool_manager import BrowserPoolManager

    pm = BrowserPoolManager()

    with patch.object(pm, "get_browser") as mock_get_browser:
        mock_get_browser.return_value = AsyncMock()

        with patch(
            "src.infrastructure.browser.pool_manager.stealth_pool"
        ) as mock_stealth:
            mock_stealth.create_context = AsyncMock(return_value=AsyncMock())

            await pm.create_context(proxy="http://proxy:8080", stealth=True)

            mock_stealth.create_context.assert_called_once()
            call_kwargs = mock_stealth.create_context.call_args
            assert "proxy" in call_kwargs.kwargs or call_kwargs.kwargs.get(
                "extra", {}
            ).get("proxy"), (
                f"Proxy must be passed to stealth_pool.create_context, got: {call_kwargs}"
            )


@pytest.mark.asyncio
async def test_pool_manager_non_stealth_passes_proxy_to_context():
    """Pool manager in non-stealth mode should pass proxy to browser context."""
    from src.infrastructure.browser.pool_manager import BrowserPoolManager

    pm = BrowserPoolManager()

    mock_browser = AsyncMock()
    mock_ctx = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_ctx)

    with patch.object(pm, "get_browser", return_value=mock_browser):
        result = await pm.create_context(proxy="http://proxy:8080", stealth=False)

        mock_browser.new_context.assert_called_once()
        call_kwargs = mock_browser.new_context.call_args
        proxy_arg = call_kwargs.kwargs.get("proxy")
        assert proxy_arg is not None, (
            f"Proxy must be passed to new_context, got: {call_kwargs}"
        )
        assert isinstance(proxy_arg, dict), (
            f"Proxy must be dict, got: {type(proxy_arg)}"
        )
        assert "server" in proxy_arg, f"Proxy dict must have 'server' key: {proxy_arg}"


@pytest.mark.asyncio
async def test_pool_manager_get_browser_passes_proxy_to_launch():
    """Pool manager get_browser should pass proxy to chromium.launch."""
    from src.infrastructure.browser.pool_manager import BrowserPoolManager

    pm = BrowserPoolManager()
    pm._browser = None

    with patch("src.infrastructure.browser.pool_manager.async_playwright") as mock_pw:
        mock_playwright = AsyncMock()
        mock_browser = AsyncMock()
        mock_playwright.start.return_value.chromium.launch = AsyncMock(
            return_value=mock_browser
        )
        mock_pw.return_value = mock_playwright

        browser = await pm.get_browser(proxy="http://proxy:8080")

        mock_playwright.start.return_value.chromium.launch.assert_called_once()
        launch_kwargs = mock_playwright.start.return_value.chromium.launch.call_args
        proxy_arg = launch_kwargs.kwargs.get("proxy")
        assert proxy_arg is not None, (
            f"Proxy must be passed to launch, got: {launch_kwargs}"
        )
        assert isinstance(proxy_arg, dict), (
            f"Proxy must be dict, got: {type(proxy_arg)}"
        )


def test_proxy_file_loaded_in_compose():
    """docker-compose should mount proxies.txt if it exists."""
    import os
    import yaml

    if not os.path.exists("docker-compose.yml"):
        pytest.skip("docker-compose.yml not found")

    if not os.path.exists("proxies.txt"):
        pytest.skip("proxies.txt not found")

    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)

    services = compose.get("services", {})

    for name in ["api", "worker"]:
        if name in services:
            volumes = services[name].get("volumes", [])
            has_proxy = any("proxies.txt" in str(v) for v in volumes)
            assert has_proxy, f"Service {name} missing proxies.txt volume mount"


def test_proxy_provider_class_exists():
    """ProxyProvider class must exist with required methods."""
    try:
        from src.infrastructure.browser.proxy_provider import ProxyProvider

        assert hasattr(ProxyProvider, "get_proxy"), (
            "ProxyProvider must have get_proxy method"
        )
        assert hasattr(ProxyProvider, "_load_proxies"), (
            "ProxyProvider must have _load_proxies method"
        )
    except ImportError as e:
        pytest.fail(f"ProxyProvider class not found: {e}")


@pytest.mark.asyncio
async def test_proxy_provider_returns_proxy_or_empty():
    """ProxyProvider.get_proxy must return proxy string or empty dict."""
    from src.infrastructure.browser.proxy_provider import ProxyProvider

    provider = ProxyProvider()
    proxy = provider.get_proxy()

    is_valid = (
        proxy == {}
        or isinstance(proxy, str)
        and proxy.startswith("http")
        or isinstance(proxy, dict)
    )
    assert is_valid, (
        f"get_proxy must return proxy str, empty dict, or proxy dict, got: {proxy}"
    )
