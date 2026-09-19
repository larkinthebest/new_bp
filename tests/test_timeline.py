from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai import AI
from app.index import Retriever
from app.models import SearchRequest, TimelineReview, VideoObservation
from tests.conftest import FakeAI, make_segment, seed


async def test_hierarchical_review_covers_every_segment_and_keeps_original_citations(settings):
    import json

    ai = AI(settings)
    inputs = []

    async def review(**kwargs):
        part = json.loads(kwargs["input"])["segments"]
        inputs.extend(item["citation"] for item in part)
        return SimpleNamespace(
            status="completed",
            output_parsed=TimelineReview.model_validate(
                {
                    "findings": [
                        {
                            "description": "Observed score transition.",
                            "citations": [part[-1]["citation"]],
                        }
                    ]
                }
            ),
        )

    ai.client.responses.parse = AsyncMock(side_effect=review)
    evidence = [{"citation": i + 1, "transcript": "Pass shot save. " * 800} for i in range(12)]
    try:
        reviews = await ai.review_timeline("How were all goals scored?", evidence)
        assert len(reviews) > 1
        assert set(inputs) == set(range(1, 13))
        assert reviews[-1]["findings"][0]["citations"] == [12]
        ai.client.responses.parse = AsyncMock(
            return_value=SimpleNamespace(
                status="completed",
                output_parsed=TimelineReview.model_validate(
                    {"findings": [{"description": "Invalid source.", "citations": [999]}]}
                ),
            )
        )
        with pytest.raises(ValueError, match="unknown citation"):
            await ai.review_timeline("Final score?", evidence[:1])
    finally:
        await ai.close()


async def test_global_question_includes_ending_and_respects_selected_source(settings, index):
    segments = [make_segment(i=i, start=i * 12, text=f"Scene {i}") for i in range(24)]
    segments[-1].transcript = "Overtime winner. Final result 5–4."
    await seed(index, segments + [make_segment(content="another-match")])
    evidence, coverage = await Retriever(settings, FakeAI(), index).prepare(
        SearchRequest(query="how goals was scored in the game", content_ids=["one"], top_k=2)
    )
    assert coverage.complete and coverage.included_segments == 24
    assert all(e.segment.content_id == "one" for e in evidence)
    assert evidence[-1].segment.segment_index == 23
    assert [e.citation for e in evidence] == list(range(1, 25))


async def test_two_videos_do_not_mix_116_and_105_segments(settings, index):
    await seed(
        index,
        [make_segment(content="first", i=i, start=i * 6) for i in range(116)]
        + [make_segment(content="second", i=i, start=i * 6) for i in range(105)],
    )
    items, coverage = await Retriever(settings, FakeAI(), index).prepare(
        SearchRequest(query="final score", content_ids=["second"])
    )
    assert coverage.complete and coverage.scanned_segments == coverage.included_segments == 105
    assert {item.segment.content_id for item in items} == {"second"}


async def test_budget_exhaustion_preserves_ending_and_reports_partial(settings, index):
    settings.timeline_context_tokens = 4000
    await seed(index, [make_segment(i=i, start=i * 12, text="Evidence " * 30) for i in range(24)])
    evidence, coverage = await Retriever(settings, FakeAI(), index).prepare(
        SearchRequest(query="final score", content_ids=["one"])
    )
    assert not coverage.complete
    assert coverage.included_segments < coverage.scanned_segments
    assert evidence[-1].segment.segment_index == 23


async def test_timeline_scrolls_beyond_one_page(settings, index):
    await seed(index, [make_segment(i=i, start=i * 12) for i in range(115)])
    segments, complete = await index.timeline(["one"])
    assert complete and len(segments) == 115 and segments[-1].segment_index == 114
    _, complete = await index.timeline(["one"], limit=100)
    assert not complete


async def test_vision_uses_structured_observations_and_checks_frame_times(settings, tmp_path):
    ai = AI(settings)
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"test image")
    observation = VideoObservation(sport="ice hockey", description="A shot.", scores=[], events=[])
    ai.client.responses.parse = AsyncMock(
        return_value=SimpleNamespace(status="completed", output_parsed=observation)
    )
    try:
        assert await ai.vision([(1.0, frame)], {}) == observation
        assert ai.client.responses.parse.call_args.kwargs["text_format"] is VideoObservation
        observation = VideoObservation.model_validate(
            {
                "sport": "ice hockey",
                "description": "A shot.",
                "scores": [],
                "events": [
                    {
                        "file_time": 12,
                        "event_type": "shot",
                        "description": "A shot.",
                        "team": None,
                        "player": None,
                        "is_replay": None,
                        "certainty": "observed",
                    }
                ],
            }
        )
        ai.client.responses.parse.return_value.output_parsed = observation
        with pytest.raises(ValueError, match="unobserved timestamp"):
            await ai.vision([(1.0, frame)], {})
    finally:
        await ai.close()
