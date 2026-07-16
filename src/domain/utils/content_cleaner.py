import html as html_module
import re


_NOISE_BLOCK_TAGS = (
    "head", "script", "style", "noscript", "iframe",
    "nav", "header", "footer", "aside", "form", "svg",
)


def _strip_noise_blocks(content: str) -> str:
    for tag in _NOISE_BLOCK_TAGS:
        content = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}>",
            "",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    return content


def clean_html_content(html: str) -> str:
    """Strip scripts/styles/comments/nav-like chrome and remaining tags; collapse whitespace.

    Returns plain text — structure is lost. Use html_to_text() to keep paragraph breaks
    or html_to_markdown() to keep full structure.
    """
    content = _strip_noise_blocks(html)
    content = re.sub(r"<[^>]+>", "", content)
    content = re.sub(r"\s+", " ", content)
    return html_module.unescape(content).strip()


def html_to_markdown(html: str) -> str:
    from markdownify import markdownify, ATX

    cleaned = _strip_noise_blocks(html)
    return markdownify(cleaned, heading_style=ATX)


def html_to_text(html: str) -> str:
    """Convert HTML to plain text preserving paragraph/heading/list line breaks."""
    content = _strip_noise_blocks(html)
    content = re.sub(r"<br\s*/?>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</p\s*>", "\n\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</div\s*>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</li\s*>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</h[1-6]\s*>", "\n\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</tr\s*>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"<[^>]+>", "", content)
    content = re.sub(r"[ \t]+", " ", content)
    content = re.sub(r"\n[ \t]+", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return html_module.unescape(content).strip()


def count_words(text: str) -> int:
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def truncate_content(text: str, max_words: int = 500) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text

    truncated_words = words[:max_words]
    while truncated_words and truncated_words[-1] in {".", "!", "?", ",", ";", ":"}:
        truncated_words.pop()

    result = " ".join(truncated_words)
    if truncated_words and result[-1] not in {".", "!", "?"}:
        result += "..."
    else:
        result += ".."

    return result
