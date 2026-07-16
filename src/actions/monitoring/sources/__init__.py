"""Per-source demand-side scrapers. Each module registers via @register_source.

Importing this package imports every source module, which triggers their
@register_source decorators and populates SOURCE_REGISTRY.
"""

from src.actions.monitoring.sources import (  # noqa: F401
    avito,
    fl,
    habr,
    hh,
    kwork,
    superjob,
    youdo,
    zarplata,
)
