"""Flat-loop research agent (generalized port of simple_agent_v2.1).

A single ``chat.completions`` loop with ``tool_choice="auto"`` and three tools:
``web_serp`` (SearXNG), ``web_scrape`` (Playwright via ``SiteEnrichAction``) and a
dynamic terminal ``submit`` tool. On submit, a critic LLM grades the result and
can reject it with feedback (force-accepted after N rejects).

Two output modes, selected by the caller:
  - ``output_schema is None``  → free-form ``submit_answer(answer, sources)``.
  - ``output_schema`` given     → ``submit_result(result, sources)`` where
    ``result`` is constrained to the caller's JSON Schema.

Everything domain-specific from the experiment (ANCHOR / ORG_CARD / yandex) is
gone. All numeric knobs come from ``src.core.config.settings`` and all prompt
text from ``research_agent_prompts.yaml`` (loaded via ``load_prompts``).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from src.actions.research.modes import (
    ITER_OVERRIDE_MAX,
    ITER_OVERRIDE_MIN,
    TOKEN_OVERRIDE_MAX,
    TOKEN_OVERRIDE_MIN,
    get_mode_preset,
)
from src.actions.research.tools import scrape_url, web_search
from src.core.config import settings
from src.infrastructure.external_api.facade import get_orchestration_client

logger = logging.getLogger(__name__)


# --- prompt loading ---------------------------------------------------------

_PROMPTS_CACHE: dict[str, Any] | None = None


def load_prompts() -> dict[str, Any]:
    """Load (and module-cache) the YAML prompt pack.

    Required keys: ``system``, ``critic_system``, ``refraser_system``,
    ``compact_system`` and ``templates.{first_user, first_user_schema,
    critic_user, refraser_user, compact_user, submit_reject}``.
    """
    global _PROMPTS_CACHE
    if _PROMPTS_CACHE is None:
        path = Path(settings.RESEARCH_PROMPTS_PATH)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Prompt pack at {path} is not a mapping")
        _PROMPTS_CACHE = data
    return _PROMPTS_CACHE


def _render(template: str, **kwargs: Any) -> str:
    """Substitute ``{key}`` tokens via str.replace (JSON braces stay safe)."""
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# --- text extraction --------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_PHONE_RE = re.compile(
    r"\+?\d[\s\-\(\)]*(?:\d[\s\-\(\)]*){8,13}\d"
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_SOCIAL_RE = re.compile(
    r"(?:vk\.com|t\.me|telegram\.me|instagram\.com|youtube\.com|linkedin\.com|"
    r"habr\.com|hh\.ru|superjob\.ru|2gis\.ru|yandex\.ru/maps|rusprofile\.ru|"
    r"facebook\.com|twitter\.com|x\.com|github\.com)\S{0,80}",
    re.IGNORECASE,
)


def html_to_text(html: str) -> str:
    """Best-effort strip of any residual markup + whitespace collapse."""
    body = re.sub(
        r"<script\b[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE
    )
    body = re.sub(
        r"<style\b[^>]*>.*?</style>", " ", body, flags=re.DOTALL | re.IGNORECASE
    )
    body = _TAG_RE.sub(" ", body)
    return _WS_RE.sub(" ", body).strip()


def _keywords(query: str, output_schema: dict | None) -> list[str]:
    """Salient terms to center scrape extracts on: query words + schema props."""
    seen: set[str] = set()
    kws: list[str] = []
    for w in re.findall(r"\w{4,}", query, flags=re.UNICODE):
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            kws.append(w)
    if isinstance(output_schema, dict):
        props = output_schema.get("properties")
        if isinstance(props, dict):
            for p in props:
                if isinstance(p, str) and p.lower() not in seen:
                    seen.add(p.lower())
                    kws.append(p)
    return kws[:20]


def goal_conditioned_extract(
    text: str, keywords: list[str], *, budget: int
) -> str:
    """Pull keyword mentions + contact patterns ±pad chars; fall back to head."""
    if not text:
        return ""
    spans: list[tuple[int, int]] = []

    def add(start: int, end: int, pad: int) -> None:
        spans.append((max(0, start - pad), min(len(text), end + pad)))

    for kw in keywords:
        if not kw:
            continue
        for m in re.finditer(re.escape(kw), text, flags=re.IGNORECASE):
            add(m.start(), m.end(), 400)
    for rx, pad in [(_PHONE_RE, 200), (_EMAIL_RE, 200), (_SOCIAL_RE, 100)]:
        for m in rx.finditer(text):
            add(m.start(), m.end(), pad)

    if not spans:
        return text[:budget]

    spans.sort()
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1] + 50:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    out_parts: list[str] = []
    total = 0
    for s, e in merged:
        chunk = text[s:e].strip()
        if not chunk:
            continue
        out_parts.append(chunk)
        total += len(chunk)
        if total >= budget:
            break
    return " || ".join(out_parts)[:budget]


# --- dynamic tools ----------------------------------------------------------

_SOURCES_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["url"],
        "properties": {
            "url": {"type": "string"},
            "what_it_provided": {"type": "string"},
        },
    },
}


def build_tools(output_schema: dict | None) -> tuple[list[dict], str]:
    """Return (tools, submit_tool_name) for the requested output mode."""
    tools: list[dict] = [
        {
            "type": "function",
            "function": {
                "name": "web_serp",
                "description": (
                    "SearXNG web search. Use short queries (≤5 words). The result "
                    "may carry _supervisor_hint (new angles) or _blocked_domains."
                ),
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "k": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_scrape",
                "description": (
                    "Fetch a URL; returns a relevance-filtered text extract "
                    "centered on your query terms + contact patterns."
                ),
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["url"],
                    "properties": {"url": {"type": "string"}},
                },
            },
        },
    ]

    if output_schema is None:
        submit_name = "submit_answer"
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": submit_name,
                    "description": (
                        "Terminal: submit your final answer as markdown plus the "
                        "sources you actually fetched. A critic LLM scores it; if too "
                        "low the submit is rejected with feedback. Address feedback, "
                        "do not restart."
                    ),
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["answer"],
                        "properties": {
                            "answer": {"type": "string"},
                            "sources": _SOURCES_SCHEMA,
                        },
                    },
                },
            }
        )
    else:
        submit_name = "submit_result"
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": submit_name,
                    "description": (
                        "Terminal: submit the final structured result conforming to "
                        "the provided schema, plus the sources you actually fetched. "
                        "Leave fields you have no evidence for empty/null — do not "
                        "invent. A critic LLM scores it before acceptance."
                    ),
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["result"],
                        "properties": {
                            "result": output_schema,
                            "sources": _SOURCES_SCHEMA,
                        },
                    },
                },
            }
        )
    return tools, submit_name


def sanitize_sources(sources: Any) -> list[dict]:
    """Keep only entries with a real http(s) URL; truncate descriptions."""
    clean: list[dict] = []
    for s in sources or []:
        if not isinstance(s, dict):
            continue
        url = (s.get("url") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        if "." not in urlparse(url).netloc:
            continue
        clean.append(
            {"url": url, "what_it_provided": str(s.get("what_it_provided") or "")[:300]}
        )
    return clean


# --- context hygiene --------------------------------------------------------

def _strip_meta(messages: list[dict]) -> list[dict]:
    return [
        {k: v for k, v in m.items() if not (isinstance(k, str) and k.startswith("_"))}
        for m in messages
    ]


def soft_elide(messages: list[dict], current_turn: int, after_turns: int) -> int:
    cutoff = current_turn - after_turns
    elided = 0
    for m in messages:
        if m.get("role") != "tool" or m.get("name") != "web_scrape":
            continue
        if m.get("_turn", 0) > cutoff or m.get("_elided"):
            continue
        content = m.get("content") or ""
        if len(content) <= 400:
            continue
        try:
            d = json.loads(content)
            url_hint = d.get("url", "")[:120] if isinstance(d, dict) else ""
        except Exception:
            url_hint = ""
        m["content"] = json.dumps(
            {
                "_elided": True,
                "url": url_hint,
                "note": (
                    f"scrape result elided (older than {after_turns} turns; "
                    "use the facts you already extracted)."
                ),
            },
            ensure_ascii=False,
        )
        m["_elided"] = True
        elided += 1
    return elided


# --- state ------------------------------------------------------------------

def _norm_query(q: str) -> str:
    """Normalize a SERP query for duplicate detection (case/punct/space-insensitive)."""
    return _WS_RE.sub(" ", re.sub(r"[^\w\s]", " ", q.lower(), flags=re.UNICODE)).strip()


@dataclass
class AgentState:
    serp_call_count: int = 0
    queries_history: list[str] = field(default_factory=list)
    serp_seen: set[str] = field(default_factory=set)
    visited_urls: set[str] = field(default_factory=set)
    domain_fail_count: dict[str, int] = field(default_factory=dict)
    domain_visit_count: dict[str, int] = field(default_factory=dict)
    compaction_count: int = 0
    submit_attempts: int = 0


# --- auxiliary LLM calls ----------------------------------------------------

async def _chat_text(
    client: Any,
    messages: list[dict],
    usage: dict,
    timeout: float,
    *,
    perf: list[dict] | None = None,
    kind: str = "aux",
    turn: Any = None,
) -> str:
    t0 = time.monotonic()
    try:
        resp = await client.chat(messages=messages, timeout=timeout)
    except Exception:
        # failed calls still cost wall time (API timeouts, internal retries)
        if perf is not None:
            perf.append({"kind": kind, "turn": turn, "error": True,
                         "s": round(time.monotonic() - t0, 2)})
        raise
    u = resp.get("usage") or {}
    pt = u.get("prompt_tokens", 0) or 0
    ct = u.get("completion_tokens", 0) or 0
    usage["prompt"] += pt
    usage["completion"] += ct
    if perf is not None:
        perf.append({"kind": kind, "turn": turn, "prompt": pt, "completion": ct,
                     "s": round(time.monotonic() - t0, 2)})
    return resp.get("content", "") or ""


def _first_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


async def critic_call(
    client: Any,
    *,
    prompts: dict,
    query: str,
    submission: str,
    queries_made: int,
    urls_visited: int,
    pass_score: float,
    usage: dict,
    timeout: float,
    perf: list[dict] | None = None,
    turn: Any = None,
) -> dict:
    system = _render(prompts["critic_system"], pass_score=pass_score)
    user = _render(
        prompts["templates"]["critic_user"],
        query=query,
        submission=submission,
        queries_made=queries_made,
        urls_visited=urls_visited,
    )
    try:
        content = await _chat_text(
            client,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            usage,
            timeout,
            perf=perf, kind="critic", turn=turn,
        )
    except Exception as e:  # fail open — don't block on critic outage
        return {
            "score": 10.0,
            "depth_score": 10.0,
            "missing": [],
            "wrong": [],
            "feedback": f"critic unreachable: {type(e).__name__}",
            "verdict": "pass",
        }
    p = _first_json(content)
    if not p:
        return {
            "score": 7.0,
            "depth_score": 7.0,
            "missing": [],
            "wrong": [],
            "feedback": "critic returned non-JSON; passing",
            "verdict": "pass",
        }
    try:
        score = float(p.get("score", 7.0))
        return {
            "score": score,
            "depth_score": float(p.get("depth_score", score)),
            "missing": [str(x)[:80] for x in (p.get("missing") or [])][:8],
            "wrong": [str(x)[:120] for x in (p.get("wrong") or [])][:5],
            "feedback": str(p.get("feedback", ""))[:300],
            "verdict": p.get("verdict", "pass"),
        }
    except Exception:
        return {
            "score": 7.0,
            "depth_score": 7.0,
            "missing": [],
            "wrong": [],
            "feedback": "critic parse fail; passing",
            "verdict": "pass",
        }


async def refraser_call(
    client: Any,
    *,
    prompts: dict,
    language: str,
    query: str,
    queries_history: list[str],
    visited_urls: set[str],
    usage: dict,
    timeout: float,
    missing_gaps: list[str] | None = None,
    perf: list[dict] | None = None,
    turn: Any = None,
) -> dict:
    system = _render(prompts["refraser_system"], language=language)
    domains = sorted({urlparse(u).netloc for u in visited_urls})[:20]
    gaps = [g for g in (missing_gaps or []) if g][:6]
    gaps_block = ", ".join(gaps) if gaps else "(none provided)"
    user = _render(
        prompts["templates"]["refraser_user"],
        query=query,
        queries_count=len(queries_history),
        queries_block="  - " + "\n  - ".join(queries_history[-12:]),
        domains=domains,
        gaps_block=gaps_block,
    )
    try:
        content = await _chat_text(
            client,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            usage,
            timeout,
            perf=perf, kind="refraser", turn=turn,
        )
    except Exception as e:
        return {"new_angles": [], "reason": f"refraser error: {type(e).__name__}"}
    p = _first_json(content)
    if not p:
        return {"new_angles": [], "reason": "no json"}
    angles = [str(a)[:80] for a in (p.get("new_angles") or []) if a][:3]
    return {"new_angles": angles, "reason": str(p.get("reason", ""))[:160]}


async def compact_context(
    client: Any,
    messages: list[dict],
    state: AgentState,
    *,
    prompts: dict,
    max_compactions: int,
    usage: dict,
    timeout: float,
    perf: list[dict] | None = None,
    turn: Any = None,
) -> list[dict]:
    blob_parts: list[str] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        content = m.get("content") or ""
        if role == "tool":
            blob_parts.append(f"[tool_result {m.get('name', '?')}]\n{str(content)[:2500]}")
        elif role == "assistant":
            tcs = m.get("tool_calls") or []
            if tcs:
                tc_sum = "; ".join(
                    f"{tc['function']['name']}({tc['function']['arguments'][:200]})"
                    for tc in tcs
                )
                blob_parts.append(f"[asst tool_calls] {tc_sum}")
            if content:
                blob_parts.append(f"[asst] {str(content)[:1200]}")
        elif role == "user":
            blob_parts.append(f"[user]\n{str(content)[:2500]}")
    blob = "\n\n".join(blob_parts)[:55000]

    system = prompts["compact_system"]
    user = _render(prompts["templates"]["compact_user"], blob=blob)
    try:
        digest = await _chat_text(
            client,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            usage,
            timeout,
            perf=perf, kind="compact", turn=turn,
        )
    except Exception:
        return messages

    state.compaction_count += 1
    remaining = max_compactions - state.compaction_count
    return [
        messages[0],
        messages[1],
        {
            "role": "assistant",
            "content": (
                f"[AUTO-COMPACTION #{state.compaction_count} — research digest, "
                f"{len(digest)} chars]\n\n{digest}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Context was auto-compacted. {remaining} compactions left. "
                "Focus on open_gaps from the digest and submit soon."
            ),
        },
    ]


# --- tool execution ---------------------------------------------------------

async def _run_web_serp(query: str, k: int, language: str) -> dict:
    try:
        results = await web_search(query, k, language=language)
    except Exception as e:
        return {"query": query, "error": str(e)[:200], "results": []}
    return {"query": query, "count": len(results), "results": results}


async def _run_web_scrape(
    url: str, keywords: list[str], budget: int
) -> dict:
    res = await scrape_url(url)
    if not res.get("success"):
        return {"url": url, "error": res.get("error", "scrape failed"), "text": "",
                "ok": False, "_perf": res.get("perf")}
    full = html_to_text(res.get("text") or "")
    extract = goal_conditioned_extract(full, keywords, budget=budget)
    return {
        "url": url,
        "text": extract,
        "length": len(full),
        "extract_chars": len(extract),
        "ok": True,
        "_perf": res.get("perf"),
    }


async def _forced_submit(
    client: Any,
    messages: list[dict],
    submit_name: str,
    output_schema: dict | None,
    usage: dict,
    timeout: float,
    perf: list[dict] | None = None,
) -> dict | None:
    """Last-resort submission when the loop ended without the model ever calling
    submit (it looped on searches). Pins the submit tool so the model must emit a
    final result from the gathered context. Returns parsed args, or None."""
    tools, _ = build_tools(output_schema)
    submit_tool = [t for t in tools if t["function"]["name"] == submit_name]
    force_msg = {
        "role": "user",
        "content": (
            f"You are out of turns. Call {submit_name} NOW using everything you have "
            "gathered above. Fill every field you have evidence for; leave unknown "
            "fields empty or null. Do not search or scrape further."
        ),
    }
    t0 = time.monotonic()
    try:
        resp = await client.chat(
            messages=_strip_meta(messages) + [force_msg],
            tools=submit_tool,
            tool_choice={"type": "function", "function": {"name": submit_name}},
            timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001
        if perf is not None:
            perf.append({"kind": "forced_submit", "turn": "post", "error": True,
                         "s": round(time.monotonic() - t0, 2)})
        logger.warning("forced submit failed: %r", e)
        return None
    u = resp.get("usage") or {}
    usage["prompt"] += u.get("prompt_tokens", 0) or 0
    usage["completion"] += u.get("completion_tokens", 0) or 0
    if perf is not None:
        perf.append({"kind": "forced_submit", "turn": "post",
                     "prompt": u.get("prompt_tokens", 0) or 0,
                     "completion": u.get("completion_tokens", 0) or 0,
                     "s": round(time.monotonic() - t0, 2)})
    for tc in resp.get("tool_calls") or []:
        if tc.get("name") == submit_name:
            try:
                parsed = json.loads(tc.get("arguments") or "{}")
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
    return None


# --- main entry point -------------------------------------------------------

async def run_research(
    query: str,
    *,
    mode: str = "balanced",
    language: str = "ru",
    output_schema: dict | None = None,
    max_turns: int | None = None,
    max_tokens: int | None = None,
    llm_provider_config: dict | None = None,
) -> dict:
    """Run the flat-loop research agent and return a ``ResearchReport``-shaped dict.

    ``llm_provider_config`` is the tenant's BYO-LLM config (``{base_url,
    api_key, model}``), if any — ``None`` runs on the global orchestration
    settings. See ``src.infrastructure.external_api.facade.get_orchestration_client``.
    """
    prompts = load_prompts()
    preset = get_mode_preset(mode)

    turns_cap = preset.max_turns
    if max_turns is not None:
        turns_cap = max(ITER_OVERRIDE_MIN, min(ITER_OVERRIDE_MAX, int(max_turns)))
    token_cap = preset.token_budget
    if max_tokens is not None:
        token_cap = max(TOKEN_OVERRIDE_MIN, min(TOKEN_OVERRIDE_MAX, int(max_tokens)))
    default_k = preset.search_k
    deadline = preset.deadline

    compact_trigger = settings.RESEARCH_COMPACT_TRIGGER_TOKENS
    max_compactions = settings.RESEARCH_MAX_COMPACTIONS
    elide_after = settings.RESEARCH_SOFT_ELIDE_AFTER_TURNS
    refraser_every = settings.RESEARCH_REFRASER_EVERY_N_SERPS
    fail_threshold = settings.RESEARCH_DOMAIN_FAIL_THRESHOLD
    domain_visit_cap = settings.RESEARCH_SCRAPE_DOMAIN_VISIT_CAP
    llm_timeout = settings.RESEARCH_LLM_TIMEOUT_S
    scrape_budget = settings.RESEARCH_SCRAPE_BUDGET_CHARS
    pass_score = settings.RESEARCH_CRITIC_PASS_SCORE
    max_rejects = settings.RESEARCH_MAX_SUBMIT_REJECTS
    never_block = {
        d.strip()
        for d in settings.RESEARCH_DOMAINS_NEVER_BLOCK.split(",")
        if d.strip()
    }

    client = get_orchestration_client(llm_provider_config)
    tools, submit_name = build_tools(output_schema)
    keywords = _keywords(query, output_schema)

    system_prompt = _render(prompts["system"], language=language)
    first_tmpl = prompts["templates"][
        "first_user_schema" if output_schema is not None else "first_user"
    ]
    first_user = _render(first_tmpl, query=query)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": first_user},
    ]

    state = AgentState()
    trace: list[dict] = []
    main_usage = {"prompt": 0, "completion": 0, "last_prompt": 0}
    aux_usage = {"prompt": 0, "completion": 0}
    tool_call_count: dict[str, int] = {}
    refraser_runs = 0
    turns_done = 0
    perf_llm: list[dict] = []   # per LLM call: kind, turn, prompt/completion tokens, s
    perf_tools: list[dict] = []  # per tool call: name, turn, s, ok, method, waste

    # accepted / last-proposed result holders
    accepted = False
    final_answer = ""
    final_structured: dict | None = None
    final_sources: list[dict] = []
    final_critic: dict | None = None
    last_answer = ""
    last_structured: dict | None = None
    last_sources: list[dict] = []
    last_critic: dict | None = None

    started = time.time()

    for turn in range(1, turns_cap + 1):
        if time.time() - started > deadline:
            trace.append({"turn": turn, "role": "note", "content": "deadline reached"})
            break

        elided = soft_elide(messages, turn, elide_after)
        if elided:
            trace.append({"turn": turn, "role": "soft_compact", "elided": elided})

        t_llm = time.monotonic()
        try:
            resp = await client.chat(
                messages=_strip_meta(messages),
                tools=tools,
                tool_choice="auto",
                timeout=llm_timeout,
            )
        except Exception as e:
            perf_llm.append({"kind": "main", "turn": turn, "error": True,
                             "s": round(time.monotonic() - t_llm, 2)})
            trace.append({"turn": turn, "role": "error", "content": f"main LLM failed: {e!r}"[:500]})
            break
        turns_done += 1

        u = resp.get("usage") or {}
        pt = u.get("prompt_tokens", 0) or 0
        ct = u.get("completion_tokens", 0) or 0
        main_usage["prompt"] += pt
        main_usage["completion"] += ct
        main_usage["last_prompt"] = pt
        perf_llm.append({"kind": "main", "turn": turn, "prompt": pt, "completion": ct,
                         "s": round(time.monotonic() - t_llm, 2)})

        tcs = resp.get("tool_calls") or []
        asst_rec: dict = {"role": "assistant", "content": resp.get("content", "") or ""}
        if tcs:
            asst_rec["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tcs
            ]
        messages.append(asst_rec)
        trace.append(
            {
                "turn": turn,
                "role": "assistant",
                "content": (resp.get("content", "") or "")[:400],
                "tool_calls": [
                    {"name": tc["name"], "args": tc["arguments"][:300]} for tc in tcs
                ],
            }
        )

        # Hard-compaction trigger (drop pending tool_calls, summarize, retry).
        if main_usage["last_prompt"] >= compact_trigger and state.compaction_count < max_compactions:
            trace.append({"turn": turn, "role": "compact_trigger", "last_prompt_tokens": main_usage["last_prompt"]})
            messages.pop()
            messages = await compact_context(
                client, messages, state,
                prompts=prompts, max_compactions=max_compactions,
                usage=aux_usage, timeout=llm_timeout,
                perf=perf_llm, turn=turn,
            )
            continue

        if not tcs:
            trace.append({"turn": turn, "role": "note", "content": "no tool call — stopping"})
            break

        for tc in tcs:
            name = tc["name"]
            tool_call_count[name] = tool_call_count.get(name, 0) + 1
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}

            if name == "web_serp":
                q = str(args.get("query", ""))
                k = int(args.get("k") or default_k)
                state.queries_history.append(q)
                state.serp_call_count += 1
                norm = _norm_query(q)
                if norm and norm in state.serp_seen:
                    # Anti-loop guard: identical search already executed. Don't
                    # re-run it — push toward scraping a found URL or submitting.
                    result = {
                        "query": q,
                        "duplicate": True,
                        "results": [],
                        "note": (
                            "You already ran this exact search. Do NOT repeat queries. "
                            "Either web_scrape one of the URLs you already found "
                            "(contacts live on the site, not in snippets), try a clearly "
                            f"different query, or call {submit_name} now with what you have."
                        ),
                        "recent_queries": state.queries_history[-8:],
                    }
                else:
                    if norm:
                        state.serp_seen.add(norm)
                    t_tool = time.monotonic()
                    result = await _run_web_serp(q, k, language)
                    perf_tools.append({
                        "name": "web_serp", "turn": turn,
                        "s": round(time.monotonic() - t_tool, 2),
                        "ok": "error" not in result,
                        "n_results": result.get("count", 0),
                    })

                    blocked = sorted(
                        d for d, c in state.domain_fail_count.items() if c >= fail_threshold
                    )
                    if blocked:
                        result["_blocked_domains"] = blocked

                    # Nudge toward scraping when over-searching: emails/phones live
                    # on the actual pages, not in SERP snippets.
                    scrapes = tool_call_count.get("web_scrape", 0)
                    if state.serp_call_count >= 4 and scrapes * 2 < state.serp_call_count:
                        result["_scrape_reminder"] = (
                            f"You've searched {state.serp_call_count}× but scraped only "
                            f"{scrapes} page(s). Emails and phone numbers live on the actual "
                            "site/contact pages — web_scrape the most promising URLs now."
                        )

                    if refraser_every and state.serp_call_count % refraser_every == 0:
                        refraser_runs += 1
                        ref = await refraser_call(
                            client, prompts=prompts, language=language, query=query,
                            queries_history=state.queries_history,
                            visited_urls=state.visited_urls,
                            usage=aux_usage, timeout=llm_timeout,
                            missing_gaps=(last_critic or {}).get("missing"),
                            perf=perf_llm, turn=turn,
                        )
                        if ref.get("new_angles"):
                            result["_supervisor_hint"] = ref
                            trace.append({"turn": turn, "role": "refraser", "angles": ref["new_angles"]})

            elif name == "web_scrape":
                url = str(args.get("url", ""))
                dom = urlparse(url).netloc
                if url in state.visited_urls:
                    # URL-dedup: don't pay to fetch the exact same page twice.
                    result = {
                        "url": url, "duplicate": True, "text": "",
                        "note": ("You already scraped this exact URL. Use what you have, "
                                 "or scrape a DIFFERENT page/source."),
                    }
                elif dom and state.domain_visit_count.get(dom, 0) >= domain_visit_cap:
                    # Per-domain cap: stop burrowing one site (×5-9 in old runs).
                    result = {
                        "url": url, "capped": True, "text": "",
                        "note": (f"Domain {dom} is exhausted ({domain_visit_cap} pages already "
                                 "scraped this run). Move to a different domain/source."),
                    }
                else:
                    state.visited_urls.add(url)
                    if dom:
                        state.domain_visit_count[dom] = state.domain_visit_count.get(dom, 0) + 1
                    t_tool = time.monotonic()
                    result = await _run_web_scrape(url, keywords, scrape_budget)
                    sperf = result.pop("_perf", None) or {}
                    perf_tools.append({
                        "name": "web_scrape", "turn": turn,
                        "s": round(time.monotonic() - t_tool, 2),
                        "ok": bool(result.get("ok")),
                        "host": dom,
                        "method": sperf.get("method"),
                        "attempts": sperf.get("attempts"),
                        "failed_s": sperf.get("failed_s"),
                        "proxy_waste_s": sperf.get("proxy_waste_s"),
                        "proxies": sperf.get("proxies"),
                    })
                    if not result.get("ok"):
                        if dom and dom not in never_block:
                            state.domain_fail_count[dom] = state.domain_fail_count.get(dom, 0) + 1

            elif name == submit_name:
                state.submit_attempts += 1
                if output_schema is None:
                    answer = str(args.get("answer") or "")
                    sources = sanitize_sources(args.get("sources"))
                    submission_str = (
                        answer + "\n\nSOURCES:\n" + json.dumps(sources, ensure_ascii=False)
                    )[:6000]
                    last_answer, last_sources = answer, sources
                else:
                    result_obj = args.get("result")
                    sources = sanitize_sources(args.get("sources"))
                    submission_str = json.dumps(
                        {"result": result_obj, "sources": sources}, ensure_ascii=False
                    )[:6000]
                    last_structured, last_sources = (
                        result_obj if isinstance(result_obj, dict) else None
                    ), sources

                critic = await critic_call(
                    client, prompts=prompts, query=query, submission=submission_str,
                    queries_made=len(state.queries_history),
                    urls_visited=len(state.visited_urls),
                    pass_score=pass_score, usage=aux_usage, timeout=llm_timeout,
                    perf=perf_llm, turn=turn,
                )
                last_critic = critic
                trace.append({
                    "turn": turn, "role": "critic",
                    "score": critic["score"], "depth_score": critic.get("depth_score"),
                    "verdict": critic["verdict"],
                    "missing": critic["missing"], "wrong": critic["wrong"],
                    "feedback": critic["feedback"],
                })

                force_accept = state.submit_attempts >= max_rejects + 1
                if critic["score"] >= pass_score or critic["verdict"] == "pass" or force_accept:
                    accepted = True
                    final_answer = last_answer
                    final_structured = last_structured
                    final_sources = sources
                    final_critic = critic
                    result = {
                        "submitted": True,
                        "critic_score": critic["score"],
                        "critic_verdict": (
                            "passed (force-accept)"
                            if force_accept and critic["score"] < pass_score
                            else "passed"
                        ),
                    }
                else:
                    ref = await refraser_call(
                        client, prompts=prompts, language=language, query=query,
                        queries_history=state.queries_history,
                        visited_urls=state.visited_urls,
                        usage=aux_usage, timeout=llm_timeout,
                        missing_gaps=critic["missing"],
                        perf=perf_llm, turn=turn,
                    )
                    refraser_runs += 1
                    result = {
                        "submitted": False,
                        "rejected_by_critic": True,
                        "critic_score": critic["score"],
                        "critic_feedback": critic["feedback"],
                        "missing": critic["missing"],
                        "wrong": critic["wrong"],
                        "suggested_new_angles": ref.get("new_angles", []),
                        "attempts_remaining_before_force": max(
                            0, max_rejects - state.submit_attempts + 1
                        ),
                        "instruction": _render(
                            prompts["templates"]["submit_reject"],
                            score=f"{critic['score']:.1f}",
                            pass_score=pass_score,
                            max_rejects=max_rejects,
                        ),
                    }
            else:
                result = {"error": f"unknown tool {name}"}

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": name,
                "content": json.dumps(result, ensure_ascii=False)[:8000],
                "_turn": turn,
            })

        if accepted:
            break

        # Post-tool compaction guard.
        if main_usage["last_prompt"] >= int(compact_trigger * 0.85) and state.compaction_count < max_compactions:
            trace.append({"turn": turn, "role": "compact_trigger_post", "last_prompt_tokens": main_usage["last_prompt"]})
            messages = await compact_context(
                client, messages, state,
                prompts=prompts, max_compactions=max_compactions,
                usage=aux_usage, timeout=llm_timeout,
                perf=perf_llm, turn=turn,
            )

        # Cost wall — force exit after the token cap.
        if main_usage["prompt"] + main_usage["completion"] >= token_cap:
            trace.append({"turn": turn, "role": "note", "content": "token cap reached"})
            break

    # Salvage: if the LLM never produced a submission (looped on searches until the
    # cap), force one final structured submission from the gathered context instead
    # of returning an empty card.
    schema_empty = output_schema is not None and last_structured is None
    free_empty = output_schema is None and not last_answer
    if not accepted and (schema_empty or free_empty):
        forced = await _forced_submit(
            client, messages, submit_name, output_schema, main_usage, llm_timeout,
            perf=perf_llm,
        )
        if forced is not None:
            state.submit_attempts += 1
            if output_schema is None:
                last_answer = str(forced.get("answer") or "")
                last_sources = sanitize_sources(forced.get("sources"))
            else:
                ro = forced.get("result")
                last_structured = ro if isinstance(ro, dict) else None
                last_sources = sanitize_sources(forced.get("sources"))
            trace.append({"turn": "post", "role": "forced_submit",
                          "ok": bool(last_structured) or bool(last_answer)})

    # Force-accept the last proposal if the loop ended without a clean pass.
    if not accepted:
        final_answer = last_answer
        final_structured = last_structured
        final_sources = last_sources
        final_critic = last_critic
        trace.append({"turn": "post", "role": "note", "content": "forced submit on exit"})

    total_elapsed = time.time() - started
    critic_events = [t for t in trace if t.get("role") == "critic"]

    def _llm_s(kind: str) -> float:
        return round(sum(r["s"] for r in perf_llm if r["kind"] == kind), 1)

    llm_total_s = round(sum(r["s"] for r in perf_llm), 1)
    serp_s = round(sum(r["s"] for r in perf_tools if r["name"] == "web_serp"), 1)
    scrape_s = round(sum(r["s"] for r in perf_tools if r["name"] == "web_scrape"), 1)
    scrape_failed_s = round(
        sum(r.get("failed_s") or 0 for r in perf_tools if r["name"] == "web_scrape"), 1
    )
    proxy_waste_s = round(
        sum(r.get("proxy_waste_s") or 0 for r in perf_tools if r["name"] == "web_scrape"), 1
    )
    accounted_s = round(llm_total_s + serp_s + scrape_s, 1)
    perf_totals = {
        "elapsed_s": round(total_elapsed, 1),
        "llm_s": llm_total_s,
        "llm_main_s": _llm_s("main"),
        "llm_critic_s": _llm_s("critic"),
        "llm_refraser_s": _llm_s("refraser"),
        "llm_compact_s": _llm_s("compact"),
        "llm_forced_submit_s": _llm_s("forced_submit"),
        "llm_failed_calls": sum(1 for r in perf_llm if r.get("error")),
        "llm_failed_s": round(sum(r["s"] for r in perf_llm if r.get("error")), 1),
        "serp_s": serp_s,
        "scrape_s": scrape_s,
        "scrape_failed_s": scrape_failed_s,
        "scrape_proxy_waste_s": proxy_waste_s,
        "accounted_s": accounted_s,
        "unaccounted_s": round(total_elapsed - accounted_s, 1),
    }

    return {
        "query": query,
        "mode": mode,
        "answer_markdown": final_answer or "",
        "structured_output": final_structured,
        "sources": final_sources,
        "critic": final_critic,
        "stats": {
            "turns": turns_done,
            "tool_calls": tool_call_count,
            "tokens": {
                "main": main_usage,
                "aux": aux_usage,
                "grand_total": (
                    main_usage["prompt"] + main_usage["completion"]
                    + aux_usage["prompt"] + aux_usage["completion"]
                ),
            },
            "elapsed_seconds": round(total_elapsed, 1),
            "mode_used": mode,
            "submit_attempts": state.submit_attempts,
            "compactions": state.compaction_count,
            "target_language": language,
            "had_output_schema": output_schema is not None,
            "perf": {
                "totals": perf_totals,
                "llm_calls": perf_llm,
                "tool_calls": perf_tools,
            },
        },
        "trace_summary": {
            "queries_history": state.queries_history,
            "visited_urls": sorted(state.visited_urls),
            "critic_events": critic_events,
            "refraser_runs": refraser_runs,
            "blocked_domains": sorted(
                d for d, c in state.domain_fail_count.items() if c >= fail_threshold
            ),
            "accepted": accepted,
        },
    }
