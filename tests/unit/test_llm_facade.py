import pytest
from src.infrastructure.external_api.facade import LLMFacade


def test_llm_facade_base():
    with pytest.raises(TypeError):
        # Should fail because it's an abstract base class
        LLMFacade()
