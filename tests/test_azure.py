from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai import AI
from app.config import Settings


async def test_azure_answer_uses_separate_client_and_deployment(settings):
    settings.chat_provider = "azure"
    settings.azure_openai_api_key = "azure-test-key"
    settings.azure_openai_endpoint = "https://example.openai.azure.com"
    settings.azure_openai_deployment = "my-answer-deployment"
    ai = AI(settings)

    class Stream:
        def __aiter__(self):
            async def events():
                yield SimpleNamespace(type="response.output_text.delta", delta="Answer")
                yield SimpleNamespace(type="response.completed")

            return events()

        async def close(self):
            pass

    ai.answer_client.responses.create = AsyncMock(return_value=Stream())
    try:
        assert ai.answer_client is not ai.client
        assert ai.client.api_key == "test-only"
        assert ai.answer_client.api_key == "azure-test-key"
        assert str(ai.answer_client.base_url) == "https://example.openai.azure.com/openai/v1/"
        assert "".join([x async for x in ai.answer("Question", [], [])]) == "Answer"
        assert ai.answer_client.responses.create.call_args.kwargs["model"] == "my-answer-deployment"
    finally:
        await ai.close()


async def test_incomplete_azure_configuration_does_not_fall_back(settings):
    settings.chat_provider = "azure"
    ai = AI(settings)
    try:
        assert not settings.chat_configured
        with pytest.raises(ValueError, match="not configured"):
            _ = [x async for x in ai.answer("Question", [], [])]
    finally:
        await ai.close()


def test_portal_url_is_not_an_api_endpoint():
    with pytest.raises(ValueError, match="resource HTTPS endpoint"):
        Settings(_env_file=None, azure_openai_endpoint="https://ai.azure.com/nextgen/project")
