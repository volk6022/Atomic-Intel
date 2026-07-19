from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from src.core.config import settings


class LLMFacade(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pass

    @abstractmethod
    async def extract(self, content: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        pass


# Lazy import to avoid circular dependency
def get_extraction_client() -> LLMFacade:
    from src.infrastructure.external_api.clients.openai_client import (
        OpenAICompatibleClient,
    )

    return OpenAICompatibleClient(
        base_url=settings.EXTRACTION_API_BASE,
        api_key=settings.EXTRACTION_API_KEY,
        model_name=settings.EXTRACTION_MODEL_NAME,
    )


def get_orchestration_client(
    tenant_llm_config: Optional[Dict[str, Any]] = None,
) -> LLMFacade:
    """Build the reasoning/navigation LLM client for a research run.

    BYO-LLM: ``tenant_llm_config`` is the tenant's ``llm_provider_config``
    (``{base_url, api_key, model}``), threaded in from the taskiq task payload
    (see ``src.infrastructure.queue.research_task``). A missing/partial config
    falls back to the global ``ORCHESTRATION_*`` settings.
    """
    from src.infrastructure.external_api.clients.openai_client import (
        OpenAICompatibleClient,
    )

    if tenant_llm_config:
        base_url = tenant_llm_config.get("base_url")
        api_key = tenant_llm_config.get("api_key")
        model = tenant_llm_config.get("model")
        if base_url and api_key and model:
            return OpenAICompatibleClient(
                base_url=base_url, api_key=api_key, model_name=model
            )

    # House (non-BYO) fallback: base URL may be overridden at runtime via the
    # bot's /sethousellm (e.g. a rotating tunnel URL); api_key/model stay env.
    from src.infrastructure.tasks.research_store import house_llm_base_url

    return OpenAICompatibleClient(
        base_url=house_llm_base_url(),
        api_key=settings.ORCHESTRATION_API_KEY,
        model_name=settings.ORCHESTRATION_MODEL_NAME,
    )
