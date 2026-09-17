import asyncio
import json
from pathlib import Path

import pytest

from app.ingestion import Ingestor
from app.models import Metadata, VideoObservation
from app.storage import Storage
from tests.conftest import FakeAI


async def test_media_aligns_speech_and_visual_on_one_timeline(settings, index, monkeypatch):
    store = Storage(settings.data_dir / "media.sqlite")
    await store.initialize()
    await store.run(
        "INSERT INTO contents(id,name,path,metadata) VALUES (?,?,?,?)",
        ("match", "test.mp4", "test.mp4", "{}"),
    )
    settings.segment_seconds = 12
    source = settings.data_dir / "test.mp4"
    source.write_bytes(b"video")
    active = set()
    overlap = []
    model_calls = []

    class MediaAI(FakeAI):
        async def transcribe(self, path, offset):
            model_calls.append("asr")
            active.add("asr")
            await asyncio.sleep(0.03)
            overlap.append("vision" in active)
            return [{"start": 10, "end": 14, "text": "crosses boundary"}]

        async def vision(self, frames, metadata):
            model_calls.append("vision")
            active.add("vision")
            await asyncio.sleep(0.03)
            assert len(frames) >= 12
            assert all(p.exists() for _, p in frames)
            return VideoObservation(
                sport="ice hockey", description=f"visual at {frames[0][0]}", scores=[], events=[]
            )

    async def fake_command(*args, **kwargs):
        if "-show_format" in args:
            return json.dumps(
                {
                    "format": {"duration": "24"},
                    "streams": [{"codec_type": "audio"}, {"codec_type": "video"}],
                }
            ).encode()
        if "%04d" in str(args[-1]):
            for n in range(1, 14):
                Path(str(args[-1]).replace("%04d", f"{n:04d}")).write_bytes(b"frame")
        else:
            Path(args[-1]).write_bytes(b"fake-media")
        return b""

    monkeypatch.setattr("app.ingestion.command", fake_command)
    ingestor = Ingestor(settings, MediaAI(), index, store)
    segments = await ingestor.media(
        {"id": "match", "name": "test.mp4", "path": str(source)}, Metadata()
    )
    assert len(segments) == 2
    assert [(s.start_time, s.end_time) for s in segments] == [(0, 12), (12, 24)]
    assert all(s.transcript == "crosses boundary" and s.visual_description for s in segments)
    assert len({s.segment_id for s in segments}) == 2
    assert overlap == [True]
    first_calls = model_calls.copy()
    resumed = await ingestor.media(
        {"id": "match", "name": "test.mp4", "path": str(source)}, Metadata()
    )
    assert resumed == segments
    assert model_calls == first_calls  # Successful paid stages are not repeated on retry.


async def test_media_duration_is_bounded(settings, index, monkeypatch):
    async def fake_command(*args, **kwargs):
        return json.dumps({"format": {"duration": "999999"}, "streams": []}).encode()

    monkeypatch.setattr("app.ingestion.command", fake_command)
    with pytest.raises(ValueError, match="Длительность"):
        await Ingestor(settings, FakeAI(), index, None).media({"path": "test.mp4"}, Metadata())
