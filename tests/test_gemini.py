import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI

from app.ai import AI
from app.scoring import score_anchors
from tests.test_scoring import evidence


@asynccontextmanager
async def gemini(settings, handler):
    settings.chat_provider = "gemini"
    settings.gemini_api_key = "gemini-test-key"
    ai = AI(settings)
    assert ai.answer_client is not ai.client
    assert ai.answer_client.api_key == "gemini-test-key"
    assert ai.client.api_key == "test-only"
    endpoint = str(ai.answer_client.base_url)
    assert endpoint == "https://generativelanguage.googleapis.com/v1beta/openai/"
    await ai.answer_client.close()
    ai.answer_client = AsyncOpenAI(
        api_key=settings.gemini_api_key,
        base_url=endpoint,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        yield ai
    finally:
        await ai.close()


def completion(content):
    return {
        "id": "test",
        "object": "chat.completion",
        "created": 0,
        "model": "gemini-2.5-flash",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }


async def test_gemini_stream_uses_google_endpoint_and_keeps_evidence(settings):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert (
            str(request.url)
            == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        )
        assert request.headers["authorization"] == "Bearer gemini-test-key"
        events = []
        for text, reason in [("Answer [1]", None), (None, "stop")]:
            chunk = {
                "id": "test",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": settings.gemini_model,
                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": reason}],
            }
            events.append("data: " + json.dumps(chunk) + "\n\n")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join(events) + "data: [DONE]\n\n",
        )

    async with gemini(settings, handler) as ai:
        answer = "".join([t async for t in ai.answer("Question", [], evidence([(0, 0)]))])
        assert answer == "Answer [1]"
        assert requests[0]["model"] == settings.gemini_model
        assert requests[0]["stream"] is True
        assert "store" not in requests[0]
        payload = json.loads(requests[0]["messages"][1]["content"])
        assert payload["question"] == "Question"
        assert len(payload["evidence"]) == 1


@pytest.mark.parametrize("citation", [1, 99])
async def test_gemini_structured_goals_validate_citations(settings, citation):
    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        assert "goal_1" in body["response_format"]["json_schema"]["schema"]["properties"]
        return httpx.Response(
            200,
            json=completion(
                json.dumps(
                    {
                        "goal_1": {
                            "scorer": None,
                            "mechanism": "A rebound was scored.",
                            "citations": [citation],
                        }
                    }
                )
            ),
        )

    async with gemini(settings, handler) as ai:
        items = evidence([(0, 0), (1, 0)], final=True)
        if citation == 99:
            with pytest.raises(ValueError, match="unknown citation"):
                await ai.explain_goals("How were goals scored?", items, score_anchors(items))
        else:
            result = await ai.explain_goals("How were goals scored?", items, score_anchors(items))
            assert "A rebound was scored." in result and "1–0" in result


@pytest.mark.parametrize(
    "reason,text,refusal",
    [
        ("length", "Partial", None),
        (None, "Partial", None),
        ("stop", None, None),
        ("stop", None, "refused"),
    ],
)
async def test_gemini_rejects_incomplete_or_refused_stream_and_closes(
    settings, reason, text, refusal
):
    async with gemini(settings, lambda r: httpx.Response(500)) as ai:

        class Stream:
            closed = False

            def __aiter__(self):
                async def events():
                    yield SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content=text, refusal=refusal),
                                finish_reason=reason,
                            )
                        ]
                    )

                return events()

            async def close(self):
                self.closed = True

        stream = Stream()
        ai.answer_client.chat.completions.create = AsyncMock(return_value=stream)
        with pytest.raises(ValueError):
            _ = [t async for t in ai.answer("Question", [], [])]
        assert stream.closed


async def test_missing_gemini_key_does_not_fall_back_to_openai(settings):
    settings.chat_provider = "gemini"
    settings.gemini_api_key = ""
    ai = AI(settings)
    try:
        assert not settings.chat_configured
        assert ai.answer_client is None
        with pytest.raises(ValueError, match="not configured"):
            _ = [t async for t in ai.answer("Question", [], [])]
    finally:
        await ai.close()


async def test_jersey_question_is_not_replaced_by_generic_goal_explanations(settings):
    from app.models import Coverage

    async with gemini(settings, lambda r: httpx.Response(500)) as ai:

        async def stream(payload):
            assert "номерами" in json.loads(payload)["question"]
            yield "Numbers are not confirmed [1]."

        ai.stream_gemini = stream
        ai.explain_goals = AsyncMock(side_effect=AssertionError("Wrong answer format"))
        result = [
            text
            async for text in ai.answer(
                "Под какими номерами игроки забили голы?",
                [],
                evidence([(0, 0), (1, 0)], final=True),
                Coverage(
                    mode="whole_match",
                    scanned_segments=2,
                    included_segments=2,
                    complete=True,
                    content_ids=["one"],
                    note="Test",
                ),
            )
        ]
        assert result == ["Numbers are not confirmed [1]."]
        ai.explain_goals.assert_not_awaited()
