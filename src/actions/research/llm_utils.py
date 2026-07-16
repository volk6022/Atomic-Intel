"""LLM I/O helpers for the research agent.

The orchestration model `qwen3.5-9b-claude-4.6-opus-reasoning-distilled` is a
reasoning model that emits chain-of-thought inside `<think>...</think>` (or
`<thinking>...`) blocks before the final answer. Naive substring matching on
its raw output picks up keywords from the trace instead of the conclusion.

These helpers:
  - `strip_reasoning(text)`  — remove think/thinking blocks
  - `extract_json(text)`     — locate the first JSON object/array in a free-form
                                response (handles ```json fences and prefill).
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


_THINK_RE = re.compile(r"<think(?:ing)?\b[^>]*>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"<think(?:ing)?\b[^>]*>", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Return the model's final response with `<think>`/`<thinking>` blocks removed.

    Handles unclosed open tags too (some local servers truncate the trace).
    """
    if not text:
        return ""
    cleaned = _THINK_RE.sub("", text)
    # If a stray opening tag is left (no matching close), drop everything before
    # the last </think>-less section by stripping from the open tag onward to
    # the next double-newline.
    open_match = _OPEN_THINK_RE.search(cleaned)
    if open_match:
        # Server didn't close the trace — assume the real answer follows the
        # last newline-newline split.
        tail = cleaned[open_match.end():]
        parts = re.split(r"\n\s*\n", tail, maxsplit=1)
        cleaned = cleaned[:open_match.start()] + (parts[1] if len(parts) > 1 else "")
    return cleaned.strip()


def extract_json(text: str) -> Optional[Any]:
    """Pull the first JSON object/array out of an LLM response, after stripping
    reasoning blocks and code fences. Returns None when nothing parses.
    """
    if not text:
        return None
    body = strip_reasoning(text)

    for fence_match in _CODE_FENCE_RE.finditer(body):
        candidate = fence_match.group(1).strip()
        parsed = _try_load(candidate)
        if parsed is not None:
            return parsed

    # Scan for the first {...} / [...] balanced span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = body.find(opener)
        while start != -1:
            depth = 0
            for i in range(start, len(body)):
                c = body[i]
                if c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        parsed = _try_load(body[start:i + 1])
                        if parsed is not None:
                            return parsed
                        break
            next_start = body.find(opener, start + 1)
            if next_start == start:
                break
            start = next_start
    return None


def _try_load(blob: str) -> Optional[Any]:
    try:
        return json.loads(blob)
    except Exception:
        return None
