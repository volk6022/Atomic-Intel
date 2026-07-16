"""
Unit test for content cleaner.
T028: Write failing unit test for content cleaner.

This test MUST fail before implementation (TDD requirement).
"""

import pytest
from unittest.mock import Mock, patch


@pytest.mark.asyncio
async def test_content_cleaner_module_exists():
    """Content cleaner module should exist in domain."""
    try:
        from src.domain.utils.content_cleaner import clean_html_content

        assert clean_html_content is not None
    except ImportError:
        pytest.fail("content_cleaner module does not exist")


@pytest.mark.asyncio
async def test_content_cleaner_removes_scripts():
    """Content cleaner should remove script tags."""
    from src.domain.utils.content_cleaner import clean_html_content

    html = "<html><script>alert('xss')</script><body>Hello World</body></html>"
    result = clean_html_content(html)
    assert "<script>" not in result
    assert "Hello World" in result


@pytest.mark.asyncio
async def test_content_cleaner_removes_styles():
    """Content cleaner should remove style tags."""
    from src.domain.utils.content_cleaner import clean_html_content

    html = "<html><style>.foo{display:none}</style><body>Content</body></html>"
    result = clean_html_content(html)
    assert "<style>" not in result
    assert "Content" in result


@pytest.mark.asyncio
async def test_content_cleaner_preserves_text():
    """Content cleaner should preserve meaningful text."""
    from src.domain.utils.content_cleaner import clean_html_content

    html = "<div><p>Welcome to our company.</p><p>We provide services.</p></div>"
    result = clean_html_content(html)
    assert "Welcome to our company" in result
    assert "We provide services" in result


@pytest.mark.asyncio
async def test_truncate_to_word_limit():
    """Content should be truncated to approximately 500 words."""
    from src.domain.utils.content_cleaner import truncate_content

    text = "word " * 600
    result = truncate_content(text, max_words=500)
    word_count = len(result.split())
    assert word_count <= 510


@pytest.mark.asyncio
async def test_truncate_preserves_sentences():
    """Truncation should try to preserve complete sentences."""
    from src.domain.utils.content_cleaner import truncate_content

    text = "First sentence. Second sentence. Third sentence."
    result = truncate_content(text, max_words=2)
    assert "First sentence" in result


@pytest.mark.asyncio
async def test_html_to_text_conversion():
    """HTML should be converted to plain text."""
    from src.domain.utils.content_cleaner import html_to_text

    html = "<h1>Title</h1><p>Paragraph with <strong>bold</strong> text.</p>"
    result = html_to_text(html)
    assert "Title" in result
    assert "Paragraph" in result
    assert "bold" in result
    assert "<h1>" not in result


@pytest.mark.asyncio
async def test_word_count_accurate():
    """Word count should be accurate after cleaning."""
    from src.domain.utils.content_cleaner import clean_html_content, count_words

    html = "<p>One two three four five</p>"
    cleaned = clean_html_content(html)
    count = count_words(cleaned)
    assert count == 5
