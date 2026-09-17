import pytest
from pydantic import ValidationError

from app.index import Retriever, rrf
from app.lexical import sparse, tokens
from app.models import Hit, SearchRequest
from tests.conftest import FakeAI, make_segment, seed


def test_unicode_lexical_exact_features():
    assert tokens("Mbappé 63:18 2:1 №9") == ["mbappe", "63:18", "2:1", "9"]
    assert sparse("№9").indices == sparse("#9").indices == sparse("9").indices
    assert sparse("Mbappé").indices == sparse("MBAPPE").indices
    assert sparse("2:1").indices != sparse("1:2").indices
    assert sparse("a b").indices == sparse("a b").indices


def test_rrf_ignores_incompatible_raw_scores_and_deduplicates():
    a = Hit(segment=make_segment(), score=10000)
    b = Hit(segment=make_segment(i=1), score=0.01)
    result = rrf([[a, b], [b, a, a]])
    assert len(result) == 2
    assert result[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert result[1].score == pytest.approx(result[0].score)


async def test_named_vectors_and_sparse_filters(index):
    await seed(
        index,
        [
            make_segment(content="one", text="Mbappé 63:18"),
            make_segment(content="other", text="Mbappé 63:18"),
        ],
    )
    hits = await index.search(sparse("Mbappé"), "lexical", index.filters(["one"]), 10)
    assert len(hits) == 1
    assert hits[0].segment.content_id == "one"
    record = (
        await index.client.retrieve(index.name, [hits[0].segment.segment_id], with_vectors=True)
    )[0]
    assert set(record.vector) == {"semantic", "lexical"}


async def test_staged_segments_are_not_searchable(index):
    segment = make_segment(index_version=index.settings.index_version)
    await index.upsert([segment], await FakeAI().embed([segment.text()]))
    assert await index.search(sparse("Mbappé"), "lexical", index.filters(), 10) == []
    await index.publish(segment.content_id)
    assert len(await index.search(sparse("Mbappé"), "lexical", index.filters(), 10)) == 1


async def test_neighbors_time_overlap_and_content_isolation(index):
    segments = [make_segment(i=i, start=i * 12) for i in range(9)]
    await seed(index, segments + [make_segment(content="other", start=40)])
    near = await index.neighbors(segments[4], seconds=15)
    assert {s.segment_index for s in near} == {2, 3, 4, 5, 6}
    assert all(s.content_id == "one" for s in near)


async def test_match_filter_preserved_through_expanded_queries(index, settings):
    await seed(
        index, [make_segment(match_id="match-a"), make_segment(content="two", match_id="match-b")]
    )
    retriever = Retriever(settings, FakeAI(), index)
    hits, plan = await retriever.retrieve(SearchRequest(query="Mbappé", match_id="match-a"))
    assert hits and all(h.segment.match_id == "match-a" for h in hits)
    evidence = await retriever.context(hits, plan.neighbor_seconds)
    assert evidence and all(e.segment.match_id == "match-a" for e in evidence)
    assert len({e.segment.segment_id for e in evidence}) == len(evidence)


async def test_sparse_baseline_does_not_embed(index, settings):
    ai = FakeAI()
    await seed(index, [make_segment()])
    hits, _ = await Retriever(settings, ai, index).retrieve(
        SearchRequest(query="Mbappé"), mode="sparse"
    )
    assert hits
    assert ai.calls == []


async def test_reranker_rejects_unknown_ids(index, settings):
    from app.models import Ranking, RankItem

    class BadAI(FakeAI):
        async def rank(self, *args):
            return Ranking(items=[RankItem(segment_id="unknown", relevance=1)])

    await seed(index, [make_segment()])
    with pytest.raises(ValueError, match="Reranker"):
        await Retriever(settings, BadAI(), index).retrieve(SearchRequest(query="goal"))


async def test_embedding_version_mismatch_fails_closed(index):
    await seed(index, [make_segment()])
    index.settings.embedding_model = "different-model"
    with pytest.raises(ValueError, match="Версия индекса"):
        await index.initialize()


def test_timestamp_validation():
    with pytest.raises(ValidationError):
        make_segment().model_copy().model_validate({**make_segment().model_dump(), "end_time": -1})
