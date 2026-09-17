import asyncio
import json
import re

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from app.config import Settings
from app.lexical import sparse
from app.models import Hit, Segment


def condition(key, value):
    return qm.FieldCondition(key=key, match=qm.MatchValue(value=value))


class Index:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.name = settings.qdrant_collection
        self.client = client or (
            AsyncQdrantClient(
                url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=30
            )
            if settings.qdrant_url
            else AsyncQdrantClient(path=str(settings.data_dir / "qdrant"))
        )

    async def initialize(self):
        if not await self.client.collection_exists(self.name):
            await self.client.create_collection(
                self.name,
                vectors_config={
                    "semantic": qm.VectorParams(
                        size=self.settings.embedding_dimensions, distance=qm.Distance.COSINE
                    )
                },
                sparse_vectors_config={"lexical": qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
            )
        info = await self.client.get_collection(self.name)
        vectors = info.config.params.vectors
        lexical = info.config.params.sparse_vectors or {}
        if (
            not isinstance(vectors, dict)
            or "semantic" not in vectors
            or vectors["semantic"].size != self.settings.embedding_dimensions
            or vectors["semantic"].distance != qm.Distance.COSINE
            or "lexical" not in lexical
            or lexical["lexical"].modifier != qm.Modifier.IDF
        ):
            raise ValueError(
                "Несовместимая схема Qdrant: создайте новую collection и переиндексируйте"
            )
        # Prevent mixing same-dimensional embeddings from different models or revisions.
        records, _ = await self.client.scroll(self.name, limit=1, with_payload=True)
        if records and records[0].payload.get("index_version") != self.settings.index_version:
            raise ValueError("Версия индекса изменилась: используйте новую QDRANT_COLLECTION")
        if self.settings.qdrant_url:
            for key in ["content_id", "match_id", "state", "index_version", "teams", "players"]:
                await self.client.create_payload_index(self.name, key, qm.PayloadSchemaType.KEYWORD)
            for key in ["start_time", "end_time", "segment_index"]:
                await self.client.create_payload_index(self.name, key, qm.PayloadSchemaType.FLOAT)

    def filters(self, content_ids=None, match_id=None, extra=None):
        must = [
            condition("state", "ready"),
            condition("index_version", self.settings.index_version),
        ]
        if content_ids:
            must.append(qm.FieldCondition(key="content_id", match=qm.MatchAny(any=content_ids)))
        if match_id:
            must.append(condition("match_id", match_id))
        return qm.Filter(must=must + (extra or []))

    async def upsert(self, segments, vectors):
        points = [
            qm.PointStruct(
                id=s.segment_id,
                vector={"semantic": vector, "lexical": sparse(s.text())},
                payload=s.model_dump(),
            )
            for s, vector in zip(segments, vectors, strict=True)
        ]
        await self.client.upsert(self.name, points=points, wait=True)

    async def publish(self, content_id):
        await self.client.set_payload(
            self.name,
            payload={"state": "ready"},
            points=qm.Filter(must=[condition("content_id", content_id)]),
            wait=True,
        )

    async def delete(self, content_id):
        await self.client.delete(
            self.name,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(must=[condition("content_id", content_id)])
            ),
            wait=True,
        )

    async def search(self, vector, using, filters, limit):
        if isinstance(vector, qm.SparseVector) and not vector.indices:
            return []
        response = await self.client.query_points(
            self.name,
            query=vector,
            using=using,
            query_filter=filters,
            limit=limit,
            with_payload=True,
        )
        return [
            Hit(segment=Segment.model_validate(p.payload), score=p.score) for p in response.points
        ]

    async def neighbors(self, segment: Segment, seconds=30):
        if segment.start_time is not None:
            extra = [
                qm.FieldCondition(key="start_time", range=qm.Range(lte=segment.end_time + seconds)),
                qm.FieldCondition(
                    key="end_time", range=qm.Range(gte=max(0, segment.start_time - seconds))
                ),
            ]
        else:
            extra = [
                qm.FieldCondition(
                    key="segment_index",
                    range=qm.Range(
                        gte=max(0, segment.segment_index - 1), lte=segment.segment_index + 1
                    ),
                )
            ]
        records, _ = await self.client.scroll(
            self.name,
            scroll_filter=self.filters([segment.content_id], extra=extra),
            limit=100,
            with_payload=True,
        )
        return sorted(
            [Segment.model_validate(p.payload) for p in records], key=lambda s: s.segment_index
        )

    async def timeline(self, content_ids=None, match_id=None, limit=1200):
        segments, offset = [], None
        while len(segments) <= limit:
            records, offset = await self.client.scroll(
                self.name,
                scroll_filter=self.filters(content_ids, match_id),
                limit=min(100, limit + 1 - len(segments)),
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            segments.extend(Segment.model_validate(p.payload) for p in records)
            if offset is None:
                break
        complete = offset is None and len(segments) <= limit
        segments.sort(key=lambda s: (s.content_id, s.segment_index))
        return segments[:limit], complete

    async def get(self, segment_id):
        records = await self.client.retrieve(self.name, ids=[segment_id], with_payload=True)
        if not records or records[0].payload.get("state") != "ready":
            return None
        return Segment.model_validate(records[0].payload)

    async def close(self):
        await self.client.close()


def rrf(rankings: list[list[Hit]], k=60) -> list[Hit]:
    merged: dict[str, Hit] = {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            key = hit.segment.segment_id
            if key in seen:
                continue
            seen.add(key)
            if key not in merged:
                merged[key] = hit.model_copy(update={"score": 0.0})
            merged[key].score += 1 / (k + rank)
    return sorted(merged.values(), key=lambda h: (-h.score, h.segment.segment_id))


class Retriever:
    def __init__(self, settings, ai, index):
        self.settings, self.ai, self.index = settings, ai, index

    async def prepare(self, request, history=None):
        from app.models import Coverage, Evidence

        plan = await self.ai.plan(request.query, history or [])
        global_query = re.search(
            r"all.{0,20}goals|how.{0,20}goals|final score|who won|winner|whole match|"
            r"сколько.{0,15}гол|все.{0,15}гол|итогов.{0,15}сч|кто побед|весь матч",
            request.query,
            re.I,
        )
        if plan.scope != "whole_match" and not global_query:
            hits, plan = await self.retrieve(request, history, plan=plan)
            evidence = await self.context(hits, plan.neighbor_seconds)
            return evidence, Coverage(
                mode="local",
                scanned_segments=len(evidence),
                included_segments=len(evidence),
                complete=False,
                content_ids=list(dict.fromkeys(e.segment.content_id for e in evidence)),
                note="Relevant excerpts only; this is not a complete review of the video.",
            )
        segments, scanned_all = await self.index.timeline(
            request.content_ids, request.match_id, self.settings.timeline_max_segments
        )
        # Reserve each file's ending before spending the context budget on earlier scenes.
        endings = {
            s.segment_id
            for s in segments
            if s.segment_index
            >= max(x.segment_index for x in segments if x.content_id == s.content_id) - 9
        }
        priority = sorted(
            segments,
            key=lambda s: (
                s.segment_id not in endings,
                not any(e.event_type in ("goal", "game_end") for e in s.events),
                s.content_id,
                -s.segment_index if s.segment_id in endings else s.segment_index,
            ),
        )
        included, remaining = [], self.settings.timeline_context_tokens
        for segment in priority:
            item = Evidence(citation=1, segment=segment, kind="timeline", text=segment.text())
            size = (
                len(self.ai.encoding.encode(json.dumps(item.prompt_data(), ensure_ascii=False)))
                + 20
            )
            if size <= remaining:
                included.append(item)
                remaining -= size
        included.sort(key=lambda e: (e.segment.content_id, e.segment.segment_index))
        for n, item in enumerate(included, 1):
            item.citation = n
        complete = scanned_all and len(included) == len(segments)
        note = (
            "All indexed segments of the selected files, including the ending, are provided. "
            "Highlights may omit plays from the actual game."
            if complete
            else "Coverage is incomplete due to the segment or context limit. Do not claim an exhaustive goal count."
        )
        if any(s.ingestion_version == "legacy-v1" for s in segments):
            note += " Some sources use the older sparse frame sampling."
        return included, Coverage(
            mode="whole_match",
            scanned_segments=len(segments),
            included_segments=len(included),
            complete=complete,
            content_ids=list(dict.fromkeys(s.content_id for s in segments)),
            note=note,
        )

    async def retrieve(self, request, history=None, mode="reranked", plan=None):
        plan = plan or await self.ai.plan(request.query, history or [])
        queries = list(dict.fromkeys([request.query, plan.resolved_query] + plan.queries))[:6]
        vectors = await self.ai.embed(queries) if mode != "sparse" else [None] * len(queries)
        filters = self.index.filters(request.content_ids, request.match_id)
        calls = []
        for query, vector in zip(queries, vectors, strict=True):
            if mode != "sparse":
                calls.append(
                    self.index.search(vector, "semantic", filters, self.settings.retrieval_k)
                )
            if mode != "dense":
                calls.append(
                    self.index.search(sparse(query), "lexical", filters, self.settings.retrieval_k)
                )
        fused = rrf(await asyncio.gather(*calls))[: self.settings.candidate_k]
        if mode != "reranked" or not fused:
            return fused[: request.top_k], plan
        neighbors = await asyncio.gather(*(self.index.neighbors(h.segment, 15) for h in fused))
        candidates = [
            {
                "segment_id": h.segment.segment_id,
                "evidence": self.ai.clip(h.segment.text(), 1200),
                "neighbors": [
                    self.ai.clip(s.text(), 250)
                    for s in near
                    if s.segment_id != h.segment.segment_id
                ][:6],
            }
            for h, near in zip(fused, neighbors, strict=True)
        ]
        ranking = await self.ai.rank(plan.resolved_query, plan.focus, candidates)
        scores = {r.segment_id: r.relevance for r in ranking.items}
        expected = {h.segment.segment_id for h in fused}
        if set(scores) != expected or len(ranking.items) != len(expected):
            raise ValueError("Reranker вернул неполный или неизвестный набор сегментов")
        reranked = [
            h.model_copy(update={"score": scores[h.segment.segment_id]})
            for h in fused
            if scores[h.segment.segment_id] >= 0.25
        ]
        reranked.sort(key=lambda h: -h.score)
        return reranked[: request.top_k], plan

    async def context(self, hits, seconds):
        from app.models import Evidence

        groups = await asyncio.gather(*(self.index.neighbors(h.segment, seconds) for h in hits))
        # Reserve budget for matched segments before surrounding context.
        ordered = [(h.segment, "match") for h in hits]
        for group in groups:
            ordered.extend((s, "neighbor") for s in group)
        seen, evidence, remaining = set(), [], self.settings.context_tokens
        for segment, kind in ordered:
            if segment.segment_id in seen:
                continue
            seen.add(segment.segment_id)
            item = Evidence(
                citation=len(evidence) + 1, segment=segment, kind=kind, text=segment.text()
            )
            # Include metadata in the budget, not only the transcript.
            size = (
                len(self.ai.encoding.encode(json.dumps(item.prompt_data(), ensure_ascii=False)))
                + 20
            )
            if size > remaining:
                continue
            remaining -= size
            evidence.append(item)
        return evidence
