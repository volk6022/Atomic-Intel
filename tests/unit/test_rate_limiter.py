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
async def test_middleware_no_longer_uses_domain_rules():
    """C-01 fix: quota is per-tenant now, not a per-domain rule list.

    The middleware used to key its token bucket on the API's own inbound Host
    header via a `*.yandex.*` / `*` rule table (bug C-01 — this never rate
    limited callers correctly, since the Host header is the API's own domain,
    never a scrape target). It now resolves the caller's tenant and enforces
    that tenant's `quota_per_hour`; there is no domain-pattern rule list left.
    """
    from src.api.middleware.rate_limit import RateLimitMiddleware

    middleware = RateLimitMiddleware(app=Mock())
    assert not hasattr(middleware, "rules")
    assert hasattr(middleware, "_enabled")
