import pytest
from src.domain.utils.content_cleaner import clean_html_content, html_to_text


def test_clean_html_removes_scripts():
    html = "<script>alert('xss')</script><p>Content</p>"
    result = clean_html_content(html)
    assert "alert" not in result
    assert "Content" in result


def test_clean_html_removes_styles():
    html = "<style>.hidden {display:none}</style><p>Visible text</p>"
    result = clean_html_content(html)
    assert ".hidden" not in result
    assert "Visible text" in result


def test_clean_html_removes_comments():
    html = "<!-- hidden comment --><span>Actual content</span>"
    result = clean_html_content(html)
    assert "hidden comment" not in result
    assert "Actual content" in result


def test_html_to_text_preserves_line_breaks():
    html = "<p>First paragraph</p><p>Second paragraph</p>"
    result = html_to_text(html)
    assert "First paragraph" in result
    assert "Second paragraph" in result


def test_html_to_text_strips_all_tags():
    html = "<div><span><strong>Bold text</strong> and <em>italic</em></span></div>"
    result = html_to_text(html)
    assert "<" not in result
    assert ">" not in result
    assert "Bold text" in result
    assert "italic" in result
