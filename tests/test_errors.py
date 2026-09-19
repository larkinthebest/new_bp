from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, InternalServerError, RateLimitError

from app.errors import IngestionError, chat_error_message, ingestion_error_message
from app.ingestion import Ingestor
from tests.conftest import FakeAI


def response(status):
    return httpx.Response(
        status, request=httpx.Request("POST", "https://api.openai.com/v1/responses")
    )


def test_nested_media_failure_is_actionable():
    error = ExceptionGroup("tasks", [IngestionError("Missing media tools: FFmpeg, FFprobe.")])
    assert ingestion_error_message(error).startswith("Missing media tools")


def test_upstream_secrets_are_not_exposed():
    error = AuthenticationError("sensitive upstream body", response=response(401), body=None)
    message = ingestion_error_message(error)
    assert "API key" in message
    assert "sensitive" not in message


def test_quota_failure_is_distinguished_from_rate_limit():
    error = RateLimitError(
        "private details", response=response(429), body={"code": "insufficient_quota"}
    )
    assert "billing" in ingestion_error_message(error)


def test_chat_errors_identify_provider_without_leaking_response():
    request = httpx.Request(
        "POST", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    error = InternalServerError("secret", response=httpx.Response(503, request=request), body=None)
    message = chat_error_message(error, "gemini")
    assert "Gemini" in message and "503" in message and "secret" not in message
    assert "did not respond in time" in chat_error_message(
        APITimeoutError(request=request), "gemini"
    )
    error = AuthenticationError("secret", response=response(401), body=None)
    assert "OpenAI" in chat_error_message(error, "gemini")


async def test_missing_media_tools_fail_before_index_changes(settings, monkeypatch):
    monkeypatch.setattr("app.ingestion.shutil.which", lambda binary: None)
    index = AsyncMock()
    ingestor = Ingestor(settings, FakeAI(), index, None)
    with pytest.raises(IngestionError, match="FFmpeg, FFprobe"):
        await ingestor.process({"id": "test", "path": "match.mp4", "metadata": "{}"})
    index.delete.assert_not_called()
