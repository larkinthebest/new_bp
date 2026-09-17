import hashlib

import pytest
from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.index import Index
from app.models import QueryPlan, Ranking, RankItem, Segment, segment_id


class Encoding:
    def encode(self, text):
        return list(text)


class FakeAI:
    """Test double only. Never selected by application configuration."""

    encoding = Encoding()

    def __init__(self, settings=None):
        self.calls = []
        self.settings = settings

    def require_key(self):
        pass

    def clip(self, text, limit):
        return text[:limit]

    async def embed(self, texts):
        self.calls.append(texts)
        return [self.vector(t) for t in texts]

    @staticmethod
    def vector(text):
        values = [0.0] * 256
        for word in text.casefold().split():
            values[hashlib.sha256(word.encode()).digest()[0]] += 1
        return values

    async def plan(self, query, history):
        return QueryPlan(
            resolved_query=query, queries=[query], focus="balanced", neighbor_seconds=30
        )

    async def rank(self, query, focus, candidates):
        return Ranking(
            items=[RankItem(segment_id=c["segment_id"], relevance=0.8) for c in candidates]
        )

    async def answer(self, query, history, evidence, coverage=None):
        yield "Наблюдение [1]. "
        yield "Данных о причине недостаточно."

    async def close(self):
        pass


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        embedding_dimensions=256,
        openai_api_key="test-only",
        qdrant_url="",
        app_token="",
    )


@pytest.fixture
async def index(settings):
    index = Index(settings, AsyncQdrantClient(":memory:"))
    await index.initialize()
    yield index
    await index.close()


def make_segment(content="one", i=0, start=0, text="Mbappé 63:18 счет 2:1", **kwargs):
    return Segment(
        content_id=content,
        segment_id=segment_id(content, i),
        segment_index=i,
        content_type="video",
        source="Test match",
        start_time=start,
        end_time=start + 12,
        transcript=text,
        **kwargs,
    )


async def seed(index, segments):
    for s in segments:
        s.index_version = index.settings.index_version
        s.state = "ready"
    await index.upsert(segments, await FakeAI().embed([s.text() for s in segments]))
