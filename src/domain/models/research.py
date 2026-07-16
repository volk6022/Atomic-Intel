"""Domain models for the Research Agent feature.

The output side (``ResearchReport`` / ``Source`` / ``ResearchStats``) mirrors the
flat-loop agent in ``src/actions/research/agent.py``. ``ResearchRequest`` is kept
generic — schemas and language are caller-supplied, the service stays domain-free.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


ResearchMode = Literal["speed", "balanced", "quality"]


class Source(BaseModel):
    """A source the agent actually fetched.

    ``url`` is a plain string (not ``HttpUrl``) on purpose — real-world URLs the
    agent scrapes are sometimes imperfect (trailing junk, IDN, ``yandex.ru/maps``
    fragments) and we do not want pydantic validation to drop an otherwise-valid
    citation.
    """

    url: str
    what_it_provided: str = ""


class ResearchStats(BaseModel):
    """Execution statistics for a research run."""

    turns: int = 0
    tool_calls: dict[str, int] = Field(default_factory=dict)
    tokens: dict[str, Any] = Field(default_factory=dict)
    elapsed_seconds: float = 0.0
    mode_used: str = "balanced"
    submit_attempts: int = 0
    compactions: int = 0
    target_language: Optional[str] = None
    had_output_schema: bool = False
    # Per-call perf telemetry (llm_calls / tool_calls / totals) from the agent.
    perf: Optional[dict[str, Any]] = None


class ResearchReport(BaseModel):
    """The final research report.

    Exactly one of ``answer_markdown`` (free-form mode) or ``structured_output``
    (schema mode) carries the payload; the other stays at its empty default.
    """

    query: str
    mode: str
    answer_markdown: str = ""
    structured_output: Optional[dict[str, Any]] = None
    sources: list[Source] = Field(default_factory=list)
    critic: Optional[dict[str, Any]] = None
    stats: ResearchStats
    # Compact slice of the internal trace for debugging UI.
    trace_summary: Optional[dict[str, Any]] = None


class ResearchRequest(BaseModel):
    """User request to start a research task.

    ``output_schema`` lets callers ask the agent to fill a domain-specific JSON
    Schema rather than produce free-form markdown. The ``/research`` endpoint
    stays generic — schemas live in the caller, not the service.

    ``language`` is a BCP-47-ish code propagated into:
        - the agent's prompts (write queries / answers in this language)
        - SearXNG's ``language`` parameter (biases SERP toward that language)
    """

    # Phase 6: caller can inject context (e.g. Yandex.Maps reviews snippets) into
    # the query — raised from 2000 → 8000 chars to fit a small review block.
    query: str = Field(..., min_length=3, max_length=8000)
    mode: ResearchMode = "balanced"
    max_iters: Optional[int] = Field(default=None, ge=1, le=50)
    max_tokens: Optional[int] = Field(default=None, ge=1000, le=2_000_000)
    output_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional JSON Schema for structured-output mode.",
    )
    language: str = Field(
        default="en",
        min_length=2,
        max_length=10,
        description="BCP-47 language code (e.g. 'ru', 'en'). Routed into prompts + SearXNG.",
    )


class ResearchTaskStatus(BaseModel):
    """Status response for a research task"""

    task_id: str
    status: Literal["pending", "running", "completed", "failed", "queued_waiting_llm"]
    progress: Optional[dict] = None
    result: Optional[ResearchReport] = None
    created_at: str
    updated_at: Optional[str] = None


class ResearchTaskCreateResponse(BaseModel):
    """Response when creating a new research task"""

    task_id: str
    status: str = "pending"
    message: str = "Research task queued"
