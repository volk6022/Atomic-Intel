import pytest
from src.infrastructure.external_api.facade import (
    get_extraction_client,
    get_orchestration_client,
)
from src.infrastructure.external_api.clients.openai_client import OpenAICompatibleClient
from src.core.config import settings


def test_clients_separation():
    extraction = get_extraction_client()
    orchestration = get_orchestration_client()

    assert isinstance(extraction, OpenAICompatibleClient)
    assert isinstance(orchestration, OpenAICompatibleClient)

    assert extraction.model_name == settings.EXTRACTION_MODEL_NAME
    assert orchestration.model_name == settings.ORCHESTRATION_MODEL_NAME

    assert str(extraction.client.base_url).rstrip(
        "/"
    ) == settings.EXTRACTION_API_BASE.rstrip("/")
    assert str(orchestration.client.base_url).rstrip(
        "/"
    ) == settings.ORCHESTRATION_API_BASE.rstrip("/")
