"""Explicit live evaluation: python -m evaluation.run --live [--ragas]."""

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

from app.ai import AI, PROMPT_VERSION
from app.config import Settings
from app.index import Index, Retriever
from app.models import SearchRequest, Segment, segment_id
from evaluation.metrics import retrieval_metrics

ROOT = Path(__file__).parent


async def run(split="test"):
    settings = Settings()
    # Keep the synthetic benchmark isolated from real uploaded materials.
    settings.qdrant_collection += "_evaluation"
    settings.data_dir = settings.data_dir / "evaluation"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ai, index = AI(settings), Index(settings)
    ai.require_key()
    try:
        await index.initialize()
        raw = json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))
        segments = [
            Segment(
                **s,
                segment_id=segment_id(s["content_id"], s["segment_index"]),
                state="ready",
                index_version=settings.index_version,
            )
            for s in raw
        ]
        vectors = await ai.embed([s.text() for s in segments])
        await index.upsert(segments, vectors)
        cases = [
            json.loads(line)
            for line in (ROOT / "sports.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        cases = [case for case in cases if case["split"] == split]
        retriever = Retriever(settings, ai, index)
        results, answer_rows = [], []
        for case in cases:
            request = SearchRequest(query=case["question"], top_k=5)
            plan = await ai.plan(request.query, [])
            truth = {
                segment_id(item["content_id"], item["index"]): item["grade"]
                for item in case["relevant"]
            }
            for mode in ["dense", "sparse", "hybrid", "reranked"]:
                start = time.monotonic()
                hits, _ = await retriever.retrieve(request, mode=mode, plan=plan)
                results.append(
                    {
                        "id": case["id"],
                        "category": case["category"],
                        "mode": mode,
                        "seconds": time.monotonic() - start,
                        "retrieved": [h.segment.segment_id for h in hits],
                        **retrieval_metrics(
                            [h.segment.segment_id for h in hits], truth, request.top_k
                        ),
                    }
                )
                if mode == "reranked":
                    evidence = await retriever.context(hits, plan.neighbor_seconds)
                    answer = "".join(
                        [token async for token in ai.answer(request.query, [], evidence)]
                    )
                    answer_rows.append(
                        {
                            "user_input": request.query,
                            "response": answer,
                            "retrieved_contexts": [e.text for e in evidence],
                            "reference": case["reference"],
                        }
                    )
        summaries = {}
        for mode in ["dense", "sparse", "hybrid", "reranked"]:
            rows = [r for r in results if r["mode"] == mode]
            summaries[mode] = {
                key: statistics.mean(r[key] for r in rows)
                for key in ["precision@k", "recall@k", "mrr", "ndcg@k", "hit_rate@k", "seconds"]
            }
        output = ROOT / "results"
        output.mkdir(exist_ok=True)
        report = {
            "dataset": "synthetic-sports-v1",
            "split": split,
            "index_version": settings.index_version,
            "prompt_version": PROMPT_VERSION,
            "planner": settings.planner_model,
            "analyst": settings.chat_model,
            "summary": summaries,
            "rows": results,
        }
        (output / "retrieval.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output / "answers.json").write_text(
            json.dumps(answer_rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summaries, indent=2))
        return answer_rows
    finally:
        await ai.close()
        await index.close()


def ragas_evaluate(rows):
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    settings = Settings()
    llm = LangchainLLMWrapper(
        ChatOpenAI(
            model=settings.planner_model,
            api_key=settings.openai_api_key,
            timeout=90,
            max_retries=2,
            model_kwargs={"store": False},
        )
    )
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
    )
    result = evaluate(
        EvaluationDataset(samples=[SingleTurnSample(**r) for r in rows]),
        metrics=[
            Faithfulness(),
            ResponseRelevancy(),
            LLMContextPrecisionWithReference(),
            LLMContextRecall(),
        ],
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=True,
    )
    result.to_pandas().to_json(
        ROOT / "results" / "ragas.json", orient="records", force_ascii=False, indent=2
    )
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Authorize paid OpenAI evaluation calls"
    )
    parser.add_argument("--ragas", action="store_true")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required: evaluation makes billable model requests")
    rows = asyncio.run(run(args.split))
    if args.ragas:
        ragas_evaluate(rows)
