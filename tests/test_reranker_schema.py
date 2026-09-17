import pytest
from pydantic import ValidationError

from app.ai import AI


async def test_reranker_schema_requires_every_candidate_and_preserves_ids():
    ai = object.__new__(AI)

    async def structured(schema, instruction, data):
        assert set(schema.model_json_schema()["required"]) == {"candidate_0", "candidate_1"}
        assert "segment_id" not in data["candidates"]["candidate_0"]
        with pytest.raises(ValidationError):
            schema.model_validate({"candidate_0": 0.9})
        return schema.model_validate({"candidate_1": 0.2, "candidate_0": 0.9})

    ai.structured = structured
    result = await ai.rank(
        "goals",
        "visual",
        [
            {"segment_id": "original-id-a", "evidence": "first", "neighbors": []},
            {"segment_id": "original-id-b", "evidence": "second", "neighbors": []},
        ],
    )
    assert [(r.segment_id, r.relevance) for r in result.items] == [
        ("original-id-a", 0.9),
        ("original-id-b", 0.2),
    ]
