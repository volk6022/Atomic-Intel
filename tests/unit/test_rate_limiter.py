"""
Unit test for rate limiter.
T037: Write failing unit test for rate limiter.

This test MUST fail before implementation (TDD requirement).
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock


@pytest.mark.asyncio
async def test_rate_limiter_module_exists():
    """Rate limiter module should exist in infrastructure."""
    try:
        from src.infrastructure.rate_limiter.token_bucket import TokenBucketRateLimiter

        assert TokenBucketRateLimiter is not None
    except ImportError:
        pytest.fail("TokenBucketRateLimiter does not exist")


@pytest.mark.asyncio
async def test_rate_limit_rule_model_exists():
    """RateLimitRule model should exist."""
    try:
        from src.domain.models.rate_limit_rule import RateLimitRule

        rule = RateLimitRule(
            domain_pattern="*.yandex.*",
            requests_per_hour=30,
            enabled=True,
        )
        assert rule.domain_pattern == "*.yandex.*"
    except ImportError:
        pytest.fail("RateLimitRule model does not exist")


@pytest.mark.asyncio
async def test_rate_limit_rule_validation():
    """RateLimitRule should validate domain pattern and requests per hour."""
    from src.domain.models.rate_limit_rule import RateLimitRule

    with pytest.raises(Exception):
        RateLimitRule(domain_pattern="*", requests_per_hour=0, enabled=True)

    with pytest.raises(Exception):
        RateLimitRule(domain_pattern="*", requests_per_hour=10001, enabled=True)


@pytest.mark.asyncio
async def test_token_bucket_module_imports():
    """Token bucket rate limiter should be importable."""
    from src.infrastructure.rate_limiter.token_bucket import rate_limiter

    assert rate_limiter is not None
    assert hasattr(rate_limiter, "check_rate_limit")
    assert hasattr(rate_limiter, "consume")


@pytest.mark.asyncio
async def test_rate_limit_rule_matches_domain():
    """RateLimitRule should correctly match domains."""
    from src.domain.models.rate_limit_rule import RateLimitRule

    rule = RateLimitRule(
        domain_pattern="*.yandex.*", requests_per_hour=30, enabled=True
    )
    assert rule.matches_domain("maps.yandex.com") == True
    assert rule.matches_domain("something.yandex.ru") == True
    assert rule.matches_domain("google.com") == False


@pytest.mark.asyncio
async def test_rate_limit_rule_disabled():
    """Disabled rate limit rule should not match."""
    from src.domain.models.rate_limit_rule import RateLimitRule

    rule = RateLimitRule(
        domain_pattern="*.yandex.*", requests_per_hour=30, enabled=False
    )
    assert rule.matches_domain("yandex.ru") == False


@pytest.mark.asyncio
async def test_yandex_domain_matches_pattern():
    """Yandex domains should match *.yandex.* pattern."""
    from src.domain.models.rate_limit_rule import RateLimitRule

    rule = RateLimitRule(
        domain_pattern="*.yandex.*", requests_per_hour=30, enabled=True
    )
    assert rule.matches_domain("maps.yandex.com") == True
    assert rule.matches_domain("something.yandex.ru") == True
    assert rule.matches_domain("google.com") == False


@pytest.mark.asyncio
async def test_middleware_has_rate_limit_handler():
    """Rate limit middleware should have request handler."""
    try:
        from src.api.middleware.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=Mock())
        assert hasattr(middleware, "dispatch")
    except ImportError:
        pytest.fail("RateLimitMiddleware does not exist")


@pytest.mark.asyncio
async def test_middleware_initializes_with_rules():
    """Middleware should initialize with default rules."""
    from src.api.middleware.rate_limit import RateLimitMiddleware
    from src.core.config import settings

    middleware = RateLimitMiddleware(app=Mock())
    assert len(middleware.rules) > 0
    yandex_rule = next(
        (r for r in middleware.rules if r["pattern"] == "*.yandex.*"), None
    )
    assert yandex_rule is not None
    assert yandex_rule["requests_per_hour"] == settings.RATE_LIMIT_YANDEX_PER_HOUR
