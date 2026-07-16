"""Research mode presets for the flat-loop research agent.

A "mode" bundles the knobs that scale cost vs. thoroughness: how many agent
turns, how many SERP results per search, the wall-clock deadline and the hard
token cap. The agent reads these via ``get_mode_preset(mode)``.

(Global, non-mode knobs — compaction trigger, critic threshold, elision, etc.
— live in ``src/core/config.py`` ``Settings.RESEARCH_*`` and are read directly
by the agent.)
"""

from dataclasses import dataclass


@dataclass
class ModePreset:
    """Preset configuration for a research mode."""

    max_turns: int          # max flat-loop iterations (LLM turns)
    search_k: int           # default web_serp results per query
    scrape_concurrency: int
    token_budget: int       # hard cap on prompt tokens (max_tokens)
    deadline: float         # wall-clock budget in seconds


PRESETS: dict[str, ModePreset] = {
    "speed": ModePreset(
        max_turns=8,
        search_k=3,
        scrape_concurrency=2,
        token_budget=30_000,
        deadline=120.0,
    ),
    "balanced": ModePreset(
        max_turns=15,
        search_k=5,
        scrape_concurrency=3,
        token_budget=100_000,
        deadline=300.0,
    ),
    "quality": ModePreset(
        max_turns=25,
        search_k=8,
        scrape_concurrency=5,
        token_budget=1_000_000,
        deadline=1200.0,
    ),
}


# Override bounds for caller-supplied max_iters / max_tokens.
ITER_OVERRIDE_MIN = 1
ITER_OVERRIDE_MAX = 50
TOKEN_OVERRIDE_MIN = 1_000
TOKEN_OVERRIDE_MAX = 2_000_000


def get_mode_preset(mode: str) -> ModePreset:
    if mode not in PRESETS:
        raise ValueError(
            f"Invalid mode: {mode}. Must be one of: {list(PRESETS.keys())}"
        )
    return PRESETS[mode]
