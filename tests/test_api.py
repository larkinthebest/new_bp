import httpx
import pytest

from app.main import create_app
from tests.conftest import FakeAI, make_segment, seed


@pytest.fixture
async def client(settings, monkeypatch):
    monkeypatch.setattr("app.main.AI", FakeAI)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await seed(app.state.index, [make_segment()])
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def test_incognito_sse_does_not_create_history(client):
    response = await client.post("/api/chat", json={"query": "Mbappé", "incognito": True})
    assert response.status_code == 200
    assert "event: sources" in response.text and "event: done" in response.text
    assert (await client.get("/api/chats")).json() == []
    assert response.headers["cache-control"] == "no-store"


async def test_normal_chat_persists_sources_and_continues(client):
    response = await client.post("/api/chat", json={"query": "Mbappé"})
    assert "event: done" in response.text
    chat = (await client.get("/api/chats")).json()[0]
    messages = (await client.get("/api/chats/" + chat["id"])).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["sources"][0]["citation"] == 1
    assert messages[1]["coverage"]["mode"] == "local"
    assert messages[1]["coverage"]["complete"] is False
    response = await client.post("/api/chat", json={"query": "И дальше?", "chat_id": chat["id"]})
    assert "event: done" in response.text
    assert len((await client.get("/api/chats/" + chat["id"])).json()) == 4


async def test_invalid_upload_and_origin(client):
    assert (
        await client.post("/api/contents", files={"file": ("bad.exe", b"content")})
    ).status_code == 415
    assert (
        await client.post("/api/contents", files={"file": ("empty.txt", b"")})
    ).status_code == 422
    assert (
        await client.post(
            "/api/chat", json={"query": "hi"}, headers={"Origin": "https://evil.example"}
        )
    ).status_code == 403


async def test_missing_chat_and_invalid_timestamp(client):
    assert (
        await client.post("/api/chat", json={"query": "hi", "chat_id": "missing"})
    ).status_code == 404
    segment = make_segment()
    assert (
        await client.get(f"/api/segments/{segment.segment_id}/neighbors?seconds=1000")
    ).status_code == 422


async def test_token_access(settings, monkeypatch):
    monkeypatch.setattr("app.main.AI", FakeAI)
    settings.app_token = "a-test-workspace-token"
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/api/chats")).status_code == 401
            assert (await client.post("/api/session", json={"token": "wrong"})).status_code == 401
            assert (
                await client.post("/api/session", json={"token": settings.app_token})
            ).status_code == 200
            assert (await client.get("/api/chats")).status_code == 200


async def test_failed_stream_does_not_persist_partial_answer(client, monkeypatch):
    async def fail(*args, **kwargs):
        yield "partial"
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(FakeAI, "answer", fail)
    response = await client.post("/api/chat", json={"query": "Mbappé"})
    assert "event: error" in response.text and "event: done" not in response.text
    chat = (await client.get("/api/chats")).json()[0]
    assert (await client.get("/api/chats/" + chat["id"])).json() == []
