import json
import logging
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from src.infrastructure.external_api.facade import LLMFacade

logger = logging.getLogger(__name__)


class OpenAICompatibleClient(LLMFacade):
    def __init__(self, base_url: str, api_key: str, model_name: str):
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=httpx.Timeout(120.0, connect=10.0),
            max_retries=2,
        )
        self.model_name = model_name

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model_name, messages=messages
        )
        content = response.choices[0].message.content
        if content is None:
            return ""
        return content

    async def generate_structured(
        self,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Dict[str, Any],
        schema_name: str = "response",
        strict: bool = True,
    ) -> Dict[str, Any]:
        """Force valid JSON output conforming to ``schema`` via ``response_format``.

        Uses OpenAI's `json_schema` response format (supported by llama.cpp's
        llama-server build 9245+ and vLLM). The model's reply is guaranteed
        valid JSON per the schema — no regex parsing, no ``<result>`` prefill
        hacks, no fallback to ``extract_json``.

        On rare malformed output (provider bug, schema violation), raises
        ``ValueError`` so the caller can decide between retry and fallback.
        """
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    "strict": strict,
                },
            },
        )
        raw = response.choices[0].message.content or ""
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            # Reasoning models sometimes emit `<think>...</think>` before the
            # final JSON even under json_schema mode. Try to recover by
            # extracting the first balanced JSON object.
            from src.actions.research.llm_utils import extract_json

            parsed = extract_json(raw)
            if parsed is not None:
                return parsed
            logger.warning(
                "generate_structured got invalid JSON (schema=%s): %s",
                schema_name, raw[:300],
            )
            raise ValueError(
                f"LLM produced invalid JSON for schema {schema_name}: {e}"
            ) from e

    async def generate_with_tools(
        self,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        tools: List[Dict[str, Any]],
        tool_choice: Any = "required",
    ) -> Dict[str, Any]:
        """Call the LLM with tool-calling forced.

        Returns ``{"name": <tool_name>, "arguments": <dict>}``. Raises
        ``ValueError`` if the model fails to call any of the offered tools.

        ``tool_choice="required"`` forces the model to invoke exactly one tool
        from ``tools``; pass a dict like
        ``{"type": "function", "function": {"name": "x"}}`` to pin a specific
        one.
        """
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            raise ValueError(
                f"LLM did not invoke any tool (got content: {(message.content or '')[:200]!r})"
            )
        tc = tool_calls[0]
        raw_args = tc.function.arguments or "{}"
        try:
            arguments = json.loads(raw_args)
        except json.JSONDecodeError as e:
            from src.actions.research.llm_utils import extract_json

            parsed = extract_json(raw_args)
            if parsed is None:
                raise ValueError(
                    f"Tool call arguments were not valid JSON: {e} (raw={raw_args[:200]!r})"
                ) from e
            arguments = parsed
        return {"name": tc.function.name, "arguments": arguments}

    async def chat(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Any = "auto",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Multi-turn chat completion for the flat-loop research agent.

        Unlike ``generate_with_tools`` (single-shot, ``tool_choice="required"``),
        this preserves the full ``messages`` history and lets the model decide
        whether to call a tool or answer. Returns a plain dict the agent loop can
        re-serialise into the next assistant message:

            {
              "content": str,
              "tool_calls": [{"id", "name", "arguments" (raw JSON str)}, ...],
              "usage": {"prompt_tokens": int, "completion_tokens": int},
            }
        """
        kwargs: Dict[str, Any] = {"model": self.model_name, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if timeout is not None:
            kwargs["timeout"] = timeout

        response = await self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        tool_calls = [
            {
                "id": tc.id,
                "name": tc.function.name,
                "arguments": tc.function.arguments or "{}",
            }
            for tc in (getattr(message, "tool_calls", None) or [])
        ]
        usage = getattr(response, "usage", None)
        return {
            "content": message.content or "",
            "tool_calls": tool_calls,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            }
            if usage
            else {"prompt_tokens": 0, "completion_tokens": 0},
        }

    async def extract(self, content: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        # Simple extraction logic using the model
        prompt = f"Extract structured data from the following content based on this schema: {schema}\n\nContent:\n{content}"
        response_text = await self.generate(prompt)

        try:
            return json.loads(response_text)
        except Exception:
            return {"raw_response": response_text}
