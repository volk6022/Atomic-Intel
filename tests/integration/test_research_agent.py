"""Smoke test for the flat-loop research agent with a fully mocked LLM + tools.

Drives one serp → one scrape → one submit cycle and asserts the returned dict
parses into a ``ResearchReport``.
"""

import json

import pytest


class _FakeClient:
    """Stand-in for OpenAICompatibleClient.

    Main-loop calls (``tools`` set) walk a scripted sequence; auxiliary calls
    (critic/refraser/compact, no ``tools``) return a passing critic verdict.
    """

    def __init__(self, submit_name: str):
        self.submit_name = submit_name
        self._step = 0

    async def chat(self, *, messages, tools=None, tool_choice="auto", timeout=None):
        usage = {"prompt_tokens": 100, "completion_tokens": 20}
        if not tools:
            # auxiliary (critic / refraser / compact)
            return {
                "content": json.dumps(
                    {
                        "score": 9.0,
                        "missing": [],
                        "wrong": [],
                        "feedback": "good",
                        "verdict": "pass",
                    }
                ),
                "tool_calls": [],
                "usage": usage,
            }

        self._step += 1
        if self._step == 1:
            tc = {"id": "c1", "name": "web_serp", "arguments": json.dumps({"query": "searxng"})}
        elif self._step == 2:
            tc = {"id": "c2", "name": "web_scrape", "arguments": json.dumps({"url": "https://example.com"})}
        else:
            tc = {
                "id": "c3",
                "name": self.submit_name,
                "arguments": json.dumps(
                    {
                        "answer": "SearXNG is a privacy-respecting metasearch engine.",
                        "sources": [
                            {"url": "https://example.com", "what_it_provided": "overview"}
                        ],
                    }
                ),
            }
        return {"content": "", "tool_calls": [tc], "usage": usage}


@pytest.mark.asyncio
async def test_run_research_free_form_smoke(monkeypatch):
    from src.actions.research import agent
    from src.domain.models.research import ResearchReport

    fake = _FakeClient(submit_name="submit_answer")
    monkeypatch.setattr(agent, "get_orchestration_client", lambda: fake)

    async def fake_search(query, k=5, language=None):
        return [{"url": "https://example.com", "title": "SearXNG", "snippet": "metasearch"}]

    async def fake_scrape(url):
        return {
            "url": url,
            "text": "SearXNG is a free internet metasearch engine which aggregates results.",
            "word_count": 10,
            "success": True,
        }

    monkeypatch.setattr(agent, "web_search", fake_search)
    monkeypatch.setattr(agent, "scrape_url", fake_scrape)

    result = await agent.run_research("what is searxng", mode="speed", language="en")

    report = ResearchReport(**result)
    assert report.query == "what is searxng"
    assert report.answer_markdown
    assert report.structured_output is None
    assert report.sources and report.sources[0].url == "https://example.com"
    assert report.critic and report.critic["verdict"] == "pass"
    assert report.stats.submit_attempts == 1
    assert report.stats.had_output_schema is False


@pytest.mark.asyncio
async def test_run_research_schema_smoke(monkeypatch):
    from src.actions.research import agent
    from src.domain.models.research import ResearchReport

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
    }

    class _SchemaClient(_FakeClient):
        async def chat(self, *, messages, tools=None, tool_choice="auto", timeout=None):
            usage = {"prompt_tokens": 100, "completion_tokens": 20}
            if not tools:
                return {
                    "content": json.dumps({"score": 9.0, "verdict": "pass", "feedback": "ok"}),
                    "tool_calls": [],
                    "usage": usage,
                }
            self._step += 1
            if self._step == 1:
                tc = {"id": "c1", "name": "web_serp", "arguments": json.dumps({"query": "searxng"})}
            else:
                tc = {
                    "id": "c2",
                    "name": "submit_result",
                    "arguments": json.dumps(
                        {
                            "result": {"summary": "metasearch engine", "keywords": ["search"]},
                            "sources": [{"url": "https://example.com", "what_it_provided": "doc"}],
                        }
                    ),
                }
            return {"content": "", "tool_calls": [tc], "usage": usage}

    fake = _SchemaClient(submit_name="submit_result")
    monkeypatch.setattr(agent, "get_orchestration_client", lambda: fake)

    async def fake_search(query, k=5, language=None):
        return [{"url": "https://example.com", "title": "SearXNG", "snippet": "metasearch"}]

    async def fake_scrape(url):
        return {"url": url, "text": "doc", "word_count": 1, "success": True}

    monkeypatch.setattr(agent, "web_search", fake_search)
    monkeypatch.setattr(agent, "scrape_url", fake_scrape)

    result = await agent.run_research(
        "describe searxng", mode="speed", language="en", output_schema=schema
    )

    report = ResearchReport(**result)
    assert report.structured_output == {"summary": "metasearch engine", "keywords": ["search"]}
    assert report.answer_markdown == ""
    assert report.stats.had_output_schema is True
