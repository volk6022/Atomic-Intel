"""Demand-side monitoring scrapers.

``SOURCE_REGISTRY`` maps a source key ("hh", "fl", ...) to its scraper class.
Sources register themselves here (Phase 2); the router and the scheduled sweep
dispatch by key so they stay source-agnostic.
"""

from __future__ import annotations

from typing import Dict, Type

from src.actions.monitoring.base import BaseSourceScraper

SOURCE_REGISTRY: Dict[str, Type[BaseSourceScraper]] = {}


def register_source(cls: Type[BaseSourceScraper]) -> Type[BaseSourceScraper]:
    """Class decorator: register a source scraper under its ``source`` key."""
    if not cls.source:
        raise ValueError(f"{cls.__name__} must set a non-empty `source`")
    SOURCE_REGISTRY[cls.source] = cls
    return cls


def get_scraper(source: str) -> BaseSourceScraper:
    """Instantiate the scraper for ``source`` (KeyError if unknown)."""
    return SOURCE_REGISTRY[source]()


# Importing the sources package populates SOURCE_REGISTRY via @register_source.
from src.actions.monitoring import sources as _sources  # noqa: E402,F401

__all__ = ["SOURCE_REGISTRY", "register_source", "get_scraper", "BaseSourceScraper"]
