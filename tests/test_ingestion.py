import json

from app.ingestion import Ingestor, read_document, semantic_merge
from app.storage import Storage
from tests.conftest import FakeAI


def test_semantic_merge_keeps_page_boundaries_and_topic_changes():
    units = [(1, "first"), (1, "similar"), (1, "different"), (2, "next page")]
    assert semantic_merge(units, [[1, 0], [1, 0], [0, 1], [0, 1]]) == [
        (1, "first\n\nsimilar"),
        (1, "different"),
        (2, "next page"),
    ]


def test_html_does_not_index_scripts(tmp_path):
    path = tmp_path / "input.html"
    path.write_text("<h1>Match</h1><script>secret code</script><p>Result 2:1</p>", encoding="utf-8")
    text = " ".join(t for _, t in read_document(path))
    assert "secret" not in text and "Result 2:1" in text


async def test_batch_ingestion_idempotence_and_publication(settings, index):
    store = Storage(settings.data_dir / "test.sqlite")
    await store.initialize()
    path = settings.data_dir / "input.txt"
    path.write_text(
        "Mbappé scored.\n\nTeam won 2:1.\n\nPressing created the opportunity.", encoding="utf-8"
    )
    row = {"id": "content", "name": "input.txt", "path": str(path), "metadata": "{}"}
    await store.run(
        "INSERT INTO contents(id,name,path,metadata) VALUES (?,?,?,?)", tuple(row.values())
    )
    ai = FakeAI()
    ingestor = Ingestor(settings, ai, index, store)
    await ingestor.process(row)
    first = (await index.client.get_collection(index.name)).points_count
    assert first > 0
    assert len(ai.calls[0]) == 3
    assert (await store.content("content"))["status"] == "ready"
    await ingestor.process(row)
    assert (await index.client.get_collection(index.name)).points_count == first


async def test_queue_recovers_after_restart(settings):
    store = Storage(settings.data_dir / "test.sqlite")
    await store.initialize()
    await store.run(
        "INSERT INTO contents(id,name,path,metadata,status) VALUES (?,?,?,?,?)",
        ("one", "x.txt", "x", json.dumps({}), "running"),
    )
    await store.initialize()
    assert (await store.content("one"))["status"] == "queued"
