import json
from pathlib import Path

import pytest

from evaluation.metrics import retrieval_metrics


def test_metrics_known_ranks():
    result = retrieval_metrics(["x", "b", "a"], {"a": 3, "b": 1}, 3)
    assert result["precision@k"] == pytest.approx(2 / 3)
    assert result["recall@k"] == 1
    assert result["mrr"] == 0.5
    assert 0 < result["ndcg@k"] < 1
    assert result["hit_rate@k"] == 1


def test_metrics_empty_and_duplicates():
    assert retrieval_metrics([], {"a": 1}, 5)["recall@k"] == 0
    assert retrieval_metrics(["a", "a"], {"a": 1, "b": 1}, 2)["recall@k"] == 0.5


def test_dataset_references_exist_and_splits_disjoint():
    root = Path(__file__).parent.parent / "evaluation"
    corpus = json.loads((root / "corpus.json").read_text(encoding="utf-8"))
    keys = {(s["content_id"], s["segment_index"]) for s in corpus}
    cases = [
        json.loads(line)
        for line in (root / "sports.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len({c["category"] for c in cases}) >= 10
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case["reference"]
        for r in case["relevant"]:
            assert (r["content_id"], r["index"]) in keys
