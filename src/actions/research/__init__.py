"""Research Agent module — flat-loop autonomous research agent."""

from src.actions.research.agent import load_prompts, run_research
from src.actions.research.modes import get_mode_preset

__all__ = [
    "run_research",
    "load_prompts",
    "get_mode_preset",
]
