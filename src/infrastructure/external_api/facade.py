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


def get_orchestration_client() -> LLMFacade:
    from src.infrastructure.external_api.clients.openai_client import (
        OpenAICompatibleClient,
    )

    return OpenAICompatibleClient(
        base_url=settings.ORCHESTRATION_API_BASE,
        api_key=settings.ORCHESTRATION_API_KEY,
        model_name=settings.ORCHESTRATION_MODEL_NAME,
    )
