"""Normalised models for the demand-side monitor (job/order feeds).

`MonitorItem` mirrors the ``norm()`` schema proven in
``experiment_monitoring/prototype/monitor_proto.py``:
``{source, id, title, url, amount, date, _extra}``. Every source scraper emits
these so downstream (dedup store, keyword filter, API) is source-agnostic.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class MonitorItem(BaseModel):
    source: str                       # "hh" | "fl" | "kwork" | ...
    id: str
    title: str
    url: str
    amount: Optional[str] = None      # salary / budget, free-form (currencies vary)
    date: str = ""                    # publication/update time, source-native format
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_norm(cls, d: dict) -> "MonitorItem":
        """Build from the experiment ``norm()`` dict (which uses ``_extra``)."""
        return cls(
            source=d["source"],
            id=str(d.get("id", "")),
            title=d.get("title", ""),
            url=d.get("url", ""),
            amount=d.get("amount"),
            date=d.get("date", ""),
            extra=d.get("_extra") or d.get("extra") or {},
        )


class MonitorCollectRequest(BaseModel):
    # default 40: mornings can have several postings/minute, so a small page misses
    # fresh items. Each source returns up to `limit` from one fetched page (fewer if
    # the page holds fewer).
    limit: int = Field(default=40, ge=1, le=200)


class MonitorDetailRequest(BaseModel):
    # the item dict returned by /collect (needs at least id + url)
    item: dict[str, Any]


class MonitorCollectResponse(BaseModel):
    source: str
    total: int
    items: list[MonitorItem]


class MonitorDetailResponse(BaseModel):
    source: str
    item: dict[str, Any]              # detail shape varies per source; kept loose
