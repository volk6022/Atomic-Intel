import pytest
from src.domain.utils.content_cleaner import html_to_markdown, html_to_text


class TestHtmlToMarkdown:
    def test_html_converts_to_markdown_basic(self):
        html = "<h1>Title</h1><p>Content</p>"
        result = html_to_markdown(html)
        assert "# Title" in result
        assert "Content" in result

    def test_html_strips_scripts_and_styles(self):
        html = "<script>alert('xss')</script><style>.hidden{display:none}</style><p>Visible</p>"
        result = html_to_markdown(html)
        assert "alert" not in result
        assert "display" not in result
        assert "Visible" in result

    def test_html_preserves_links(self):
        html = '<p>Visit <a href="https://example.com">our site</a> for more.</p>'
        result = html_to_markdown(html)
        assert "our site" in result
        assert "[our site](https://example.com)" in result

    def test_html_preserves_images(self):
        html = '<img src="https://example.com/image.png" alt="logo"/>'
        result = html_to_markdown(html)
        assert "![logo](https://example.com/image.png)" in result

    def test_text_format_returns_plain_text(self):
        html = "<h1>Heading</h1><p>Paragraph with <strong>bold</strong> text.</p>"
        result = html_to_text(html)
        assert "Heading" in result
        assert "Paragraph" in result
        assert "bold" in result
        assert "<h1>" not in result
        assert "<strong>" not in result
