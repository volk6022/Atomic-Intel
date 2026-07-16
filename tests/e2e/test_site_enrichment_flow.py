"""
E2E test for site enrichment flow.
T030: Write failing E2E test for enrichment flow.

This test MUST fail before implementation (TDD requirement).
"""

import pytest


def test_enrichment_endpoint_registered_in_app():
    """Enrichment endpoint should be registered in main app."""
    from src.api.main import app

    routes = [r.path for r in app.routes]
    assert any("/enrich" in r for r in routes), "Enrichment endpoint not registered"


def test_enrichment_router_exists():
    """Enrichment router should exist."""
    try:
        from src.api.routers.enrichment import router

        assert router is not None
    except ImportError:
        pytest.fail("Enrichment router does not exist")


def test_enrichment_action_exists():
    """Site enrich action should exist."""
    try:
        from src.actions.site_enricher import SiteEnrichAction

        action = SiteEnrichAction()
        assert hasattr(action, "execute")
    except ImportError:
        pytest.fail("SiteEnrichAction does not exist")


def test_enriched_content_model_exists():
    """EnrichedContent model should exist."""
    try:
        from src.domain.models.enriched_content import EnrichedContent

        content = EnrichedContent(
            url="https://example.com",
            text="Sample text content",
            word_count=3,
            truncated=False,
        )
        assert content.url == "https://example.com"
    except ImportError:
        pytest.fail("EnrichedContent model does not exist")


def test_enrichment_returns_clean_text():
    """Enrichment should return clean text, not raw HTML."""
    try:
        import httpx
        import asyncio

        async def check():
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "http://localhost:8000/api/v1/enrich",
                    headers={"X-API-Key": "default_internal_key"},
                    json={
                        "url": "https://example.com",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                text = data.get("text", "")
                assert "<html" not in text.lower()
                assert "<div" not in text.lower()
                return True

        result = asyncio.run(check())
        assert result, "Enrichment did not return clean text"
    except Exception as e:
        pytest.fail(f"Enrichment failed: {e}")


def test_content_cleaner_utility_exists():
    """Content cleaner utility should exist."""
    try:
        from src.domain.utils.content_cleaner import (
            clean_html_content,
            truncate_content,
            html_to_text,
        )

        assert clean_html_content is not None
        assert truncate_content is not None
        assert html_to_text is not None
    except ImportError:
        pytest.fail("Content cleaner utilities do not exist")


def test_truncate_content_under_500_words():
    """truncate_content must limit output to max_words."""
    from src.domain.utils.content_cleaner import truncate_content, count_words

    long_text = " ".join(["word"] * 600)
    truncated = truncate_content(long_text, max_words=500)
    word_count = count_words(truncated)

    assert word_count <= 500, f"Truncated text has {word_count} words, expected <= 500"
    assert len(truncated) < len(long_text), (
        "Truncated text should be shorter than original"
    )


def test_truncate_content_exactly_500_words():
    """truncate_content must handle exactly max_words correctly."""
    from src.domain.utils.content_cleaner import truncate_content, count_words

    exact_text = " ".join(["word"] * 500)
    truncated = truncate_content(exact_text, max_words=500)
    word_count = count_words(truncated)

    assert word_count == 500, (
        f"Text with exactly 500 words should remain at 500, got {word_count}"
    )


def test_truncate_content_adds_ellipsis():
    """truncate_content must add ellipsis when truncating mid-sentence."""
    from src.domain.utils.content_cleaner import truncate_content

    long_text = " ".join(["word"] * 550)
    truncated = truncate_content(long_text, max_words=500)

    assert truncated.endswith("...") or truncated.endswith(".."), (
        "Truncated text should end with ellipsis"
    )


def test_truncate_content_preserves_sentence_endings():
    """truncate_content must not cut mid-sentence if possible."""
    from src.domain.utils.content_cleaner import truncate_content, count_words

    long_text = "word " * 510 + "complete."
    truncated = truncate_content(long_text, max_words=500)
    word_count = count_words(truncated)

    assert word_count <= 500, f"Word count {word_count} exceeds max 500"
    assert truncated.strip().endswith("."), (
        "Should preserve sentence ending if possible"
    )


@pytest.mark.asyncio
async def test_html_stripped_from_output():
    """Enrichment response text must not contain raw HTML tags."""
    from unittest.mock import patch, AsyncMock
    from httpx import AsyncClient, ASGITransport
    from src.domain.models.enriched_content import EnrichedContent
    from src.api.main import app

    clean_content = EnrichedContent(
        url="https://example.com",
        text="We build software for clients worldwide.",
        word_count=7,
        truncated=False,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "src.actions.site_enricher.SiteEnrichAction.execute",
            new_callable=AsyncMock,
            return_value=clean_content,
        ):
            response = await client.post(
                "/api/v1/enrich",
                headers={"X-API-Key": "default_internal_key"},
                json={"url": "https://example.com"},
            )
    assert response.status_code == 200
    text = response.json()["text"]
    assert "<html" not in text.lower()
    assert "<div" not in text.lower()
    assert "<p>" not in text.lower()


@pytest.mark.asyncio
async def test_enriched_content_model_fields():
    """EnrichedContent model must have all required fields with correct types."""
    from src.domain.models.enriched_content import EnrichedContent

    content = EnrichedContent(
        url="https://example.com",
        text="Sample text content for testing",
        word_count=5,
        truncated=False,
    )

    assert isinstance(content.url, str), "url must be string"
    assert content.url.startswith("http"), "url must be valid URL"
    assert isinstance(content.text, str), "text must be string"
    assert isinstance(content.word_count, int), "word_count must be int"
    assert content.word_count >= 0, "word_count must be non-negative"
    assert isinstance(content.truncated, bool), "truncated must be bool"

    content_with_pages = EnrichedContent(
        url="https://example.com",
        text="Combined content",
        word_count=2,
        truncated=False,
        pages_crawled=["https://example.com", "https://example.com/about"],
    )
    assert isinstance(content_with_pages.pages_crawled, list), (
        "pages_crawled must be list"
    )
    assert len(content_with_pages.pages_crawled) >= 1, (
        "pages_crawled must have at least one page"
    )


def test_content_cleaner_removes_scripts():
    """clean_html_content must remove <script> tags."""
    from src.domain.utils.content_cleaner import clean_html_content

    html_with_script = (
        '<html><body><p>Hello</p><script>alert("xss");</script></body></html>'
    )
    cleaned = clean_html_content(html_with_script)

    assert "alert" not in cleaned, "Script content should be removed"
    assert "Hello" in cleaned, "Normal content should remain"


def test_content_cleaner_removes_styles():
    """clean_html_content must remove <style> tags."""
    from src.domain.utils.content_cleaner import clean_html_content

    html_with_style = "<html><head><style>.foo{color:red;}</style></head><body><p>Text</p></body></html>"
    cleaned = clean_html_content(html_with_style)

    assert ".foo" not in cleaned, "Style content should be removed"
    assert "Text" in cleaned, "Normal content should remain"


def test_html_to_text_preserves_structure():
    """html_to_text must convert HTML to readable text with structure."""
    from src.domain.utils.content_cleaner import html_to_text

    html = "<p>Paragraph one.</p><p>Paragraph two.</p>"
    text = html_to_text(html)

    assert "Paragraph one" in text, "First paragraph should be preserved"
    assert "Paragraph two" in text, "Second paragraph should be preserved"
    assert "<p>" not in text, "HTML tags should be removed"
