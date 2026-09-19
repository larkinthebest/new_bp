import asyncio
from uuid import uuid4

import httpx
import pytest

from app.main import create_app
from tests.conftest import FakeAI, make_segment, seed


@pytest.fixture
async def workspace(settings, monkeypatch):
    monkeypatch.setattr("app.main.AI", FakeAI)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield app, client


async def source(app, settings, status="ready"):
    content_id = str(uuid4())
    folder = settings.data_dir / "uploads"
    folder.mkdir(exist_ok=True)
    path = folder / f"{content_id}.txt"
    path.write_text("Match evidence", encoding="utf-8")
    await app.state.storage.run(
        "INSERT INTO contents(id,name,path,metadata,status) VALUES (?,?,?,?,?)",
        (content_id, "Match.txt", str(path), "{}", status),
    )
    return content_id, path


@pytest.mark.parametrize("status", ["ready", "failed"])
async def test_delete_removes_files_vectors_and_saved_evidence(workspace, settings, status):
    app, client = workspace
    content_id, path = await source(app, settings, status)
    other_id, other_path = await source(app, settings)
    segment = make_segment(content=content_id)
    other = make_segment(content=other_id)
    await seed(app.state.index, [segment, other])
    cache = settings.data_dir / "checkpoints" / content_id / "fingerprint"
    cache.mkdir(parents=True)
    (cache / "vision.json").write_text("cached data", encoding="utf-8")
    sources = [
        {"citation": i, "segment": s.model_dump()} for i, s in enumerate([segment, other], 1)
    ]
    chat = await app.state.storage.create_chat("Match")
    await app.state.storage.save_turn(
        chat, "Question", "Answer [1] [2]", sources, {"complete": True}
    )

    assert (await client.delete(f"/api/contents/{content_id}")).status_code == 204
    assert not path.exists()
    assert not cache.parent.exists()
    assert other_path.exists()
    assert await app.state.storage.content(content_id) is None
    assert await app.state.index.get(segment.segment_id) is None
    assert await app.state.index.get(other.segment_id) is not None
    assert (await client.get(f"/api/contents/{content_id}/file")).status_code == 404
    assert (await client.get(f"/api/segments/{segment.segment_id}/neighbors")).status_code == 404
    saved = await app.state.storage.messages(chat)
    assert saved[1]["content"] == "Answer [1] [2]"
    assert saved[1]["sources"] == [sources[1]]
    assert saved[1]["coverage"] is None
    # An answer already streaming during deletion cannot save the evidence again.
    await app.state.storage.save_turn(chat, "Concurrent question", "Old answer", sources)
    assert (await app.state.storage.messages(chat))[-1]["sources"] == [sources[1]]
    assert (await client.delete(f"/api/contents/{content_id}")).status_code == 404


async def test_delete_cancels_processing_and_worker_continues(workspace, settings, monkeypatch):
    app, client = workspace
    started, cancelled, next_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    content_id, path = await source(app, settings)

    async def process(content):
        if content["id"] != content_id:
            next_started.set()
            return
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setattr(app.state.ingestor, "process", process)
    await app.state.storage.run("UPDATE contents SET status='queued' WHERE id=?", (content_id,))
    await asyncio.wait_for(started.wait(), 5)
    assert (await client.delete(f"/api/contents/{content_id}")).status_code == 204
    assert cancelled.is_set() and not path.exists()
    await source(app, settings, "queued")
    await asyncio.wait_for(next_started.wait(), 5)


async def test_delete_failure_is_retryable_and_never_requeues(workspace, settings, monkeypatch):
    app, client = workspace
    content_id, path = await source(app, settings)
    original = app.state.index.delete

    async def unavailable(*args):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(app.state.index, "delete", unavailable)
    assert (await client.delete(f"/api/contents/{content_id}")).status_code == 503
    assert path.exists()
    assert (await app.state.storage.content(content_id))["status"] == "deleting"
    assert (await client.post(f"/api/contents/{content_id}/reindex")).status_code == 409
    assert (await client.post(f"/api/contents/{content_id}/retry")).status_code == 409
    monkeypatch.setattr(app.state.index, "delete", original)
    assert (await client.delete(f"/api/contents/{content_id}")).status_code == 204


async def test_delete_rejects_paths_outside_uploads_and_unauthorized(workspace, settings):
    app, client = workspace
    content_id, path = await source(app, settings)
    outside = settings.data_dir / "keep.txt"
    outside.write_text("keep", encoding="utf-8")
    await app.state.storage.run("UPDATE contents SET path=? WHERE id=?", (str(outside), content_id))
    assert (await client.delete(f"/api/contents/{content_id}")).status_code == 503
    assert path.exists() and outside.exists()
    settings.app_token = "test-token"
    assert (await client.delete(f"/api/contents/{content_id}")).status_code == 401
    assert (await app.state.storage.content(content_id))["status"] == "ready"
