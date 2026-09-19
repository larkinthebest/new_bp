import asyncio
import contextlib
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.ai import AI
from app.config import Settings
from app.errors import chat_error_message
from app.index import Index, Retriever
from app.ingestion import SUPPORTED, Ingestor
from app.models import ChatRequest, Metadata, SearchRequest
from app.storage import Storage

log = logging.getLogger(__name__)


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        storage = Storage(settings.data_dir / "workspace.sqlite3")
        await storage.initialize()
        ai, index = AI(settings), Index(settings)
        try:
            await index.initialize()
            app.state.storage, app.state.ai, app.state.index = storage, ai, index
            app.state.retriever = Retriever(settings, ai, index)
            app.state.chat_gate = asyncio.Semaphore(3)
            app.state.ingestor = Ingestor(settings, ai, index, storage)
            worker = asyncio.create_task(app.state.ingestor.worker())
            try:
                yield
            finally:
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
        finally:
            await ai.close()
            await index.close()

    app = FastAPI(title="Touchline", lifespan=lifespan)

    @app.middleware("http")
    async def access(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            # Same-origin mutations, including localhost; no wildcard CORS.
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
            token = request.cookies.get("touchline_token", "")
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
            if settings.app_token and request.url.path != "/api/session":
                if not any(hmac.compare_digest(v, settings.app_token) for v in [token, bearer]):
                    return JSONResponse({"detail": "An access token is required"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/session")
    async def session(request: Request):
        body = await request.json()
        token = body.get("token", "")
        if not isinstance(token, str) or not hmac.compare_digest(token, settings.app_token):
            raise HTTPException(401, "Invalid access token")
        response = JSONResponse({"ok": True})
        response.set_cookie(
            "touchline_token",
            token,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
        return response

    @app.get("/api/health")
    async def health():
        info = await app.state.index.client.get_collection(settings.qdrant_collection)
        return {
            "ok": True,
            "openai_configured": bool(settings.openai_api_key),
            "chat_provider": settings.chat_provider,
            "chat_configured": settings.chat_configured,
            "segments": info.points_count,
            "audio_events": settings.audio_events,
        }

    @app.get("/api/contents")
    async def contents():
        return await app.state.storage.run(
            "SELECT id,name,metadata,status,progress,error,segments,created_at FROM contents ORDER BY created_at DESC,rowid DESC",
            fetch=True,
        )

    @app.post("/api/contents", status_code=202)
    async def upload(file: Annotated[UploadFile, File()], metadata: Annotated[str, Form()] = "{}"):
        if not settings.openai_api_key:
            raise HTTPException(503, "Add OPENAI_API_KEY to .env and restart the server")
        try:
            meta = Metadata.model_validate_json(metadata)
        except ValidationError as exc:
            raise HTTPException(422, "Invalid source metadata") from exc
        name = (file.filename or "file").replace("\\", "/").split("/")[-1][:240]
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(415, "Unsupported file format")
        content_id = str(uuid4())
        folder = settings.data_dir / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        path = (folder / f"{content_id}{suffix}").resolve()
        total = 0
        try:
            with path.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, "The file exceeds the upload limit")
                    await asyncio.to_thread(output.write, chunk)
            if not total:
                raise HTTPException(422, "The file is empty")
            await app.state.storage.run(
                "INSERT INTO contents(id,name,path,metadata,progress) VALUES (?,?,?,?,'Queued')",
                (content_id, name, str(path), meta.model_dump_json()),
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return {"id": content_id, "status": "queued"}

    @app.post("/api/contents/{content_id}/retry")
    async def retry(content_id: UUID):
        row = await app.state.storage.content(str(content_id))
        if not row:
            raise HTTPException(404, "Source not found")
        if row["status"] != "failed":
            raise HTTPException(409, "Only failed jobs can be retried")
        await app.state.storage.run(
            "UPDATE contents SET status='queued',progress='Queued',error=NULL WHERE id=? AND status='failed'",
            (str(content_id),),
        )
        return {"status": "queued"}

    @app.delete("/api/contents/{content_id}", status_code=204)
    async def delete_content(content_id: UUID):
        try:
            removed = await app.state.ingestor.delete_content(str(content_id))
        except Exception as exc:
            log.error("content_deletion_failed type=%s", type(exc).__name__)
            raise HTTPException(
                503, "Deletion could not finish. Please retry deleting this source."
            ) from exc
        if not removed:
            raise HTTPException(404, "Source not found")

    @app.post("/api/contents/{content_id}/reindex")
    async def reindex(content_id: UUID):
        row = await app.state.storage.content(str(content_id))
        if not row:
            raise HTTPException(404, "Source not found")
        if row["status"] not in ("ready", "failed"):
            raise HTTPException(409, "Source is already processing")
        await app.state.storage.run(
            "UPDATE contents SET status='queued',progress='Queued for reanalysis',error=NULL WHERE id=? AND status IN ('ready','failed')",
            (str(content_id),),
        )
        return {"status": "queued"}

    @app.get("/api/contents/{content_id}/file")
    async def source_file(content_id: UUID):
        row = await app.state.storage.content(str(content_id))
        if not row:
            raise HTTPException(404, "Source not found")
        suffix = Path(row["path"]).suffix.lower()
        media_type = {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
        }.get(suffix)
        return FileResponse(
            row["path"],
            media_type=media_type or "application/octet-stream",
            filename=row["name"],
            content_disposition_type="inline" if media_type else "attachment",
        )

    @app.get("/api/segments/{segment_id}/neighbors")
    async def neighbors(segment_id: UUID, seconds: int = 30):
        if not 0 <= seconds <= 60:
            raise HTTPException(422, "seconds: 0–60")
        segment = await app.state.index.get(str(segment_id))
        if not segment:
            raise HTTPException(404, "Segment not found")
        return await app.state.index.neighbors(segment, seconds)

    @app.post("/api/search")
    async def search(body: SearchRequest):
        if not settings.openai_api_key:
            raise HTTPException(503, "OpenAI is not configured")
        async with app.state.chat_gate, asyncio.timeout(240):
            hits, plan = await app.state.retriever.retrieve(body)
        return {"hits": hits, "plan": plan}

    @app.get("/api/chats")
    async def chats():
        return await app.state.storage.run(
            "SELECT * FROM chats ORDER BY created_at DESC", fetch=True
        )

    @app.get("/api/chats/{chat_id}")
    async def chat(chat_id: UUID):
        return await app.state.storage.messages(str(chat_id))

    @app.delete("/api/chats/{chat_id}", status_code=204)
    async def delete_chat(chat_id: UUID):
        await app.state.storage.run("DELETE FROM messages WHERE chat_id=?", (str(chat_id),))
        await app.state.storage.run("DELETE FROM chats WHERE id=?", (str(chat_id),))

    @app.post("/api/chat")
    async def stream_chat(body: ChatRequest):
        if not settings.chat_configured:
            raise HTTPException(
                503,
                "Configure the answer provider in .env: CHAT_PROVIDER=gemini, GEMINI_API_KEY and GEMINI_MODEL; or select CHAT_PROVIDER=openai with OPENAI_API_KEY",
            )
        if not settings.openai_api_key:
            raise HTTPException(503, "Add OPENAI_API_KEY to .env and restart the server")
        if not body.query.strip():
            raise HTTPException(422, "Enter a question")
        if body.all_sources and body.content_ids:
            raise HTTPException(422, "Choose selected sources or all sources, not both")
        if body.content_ids:
            for content_id in body.content_ids:
                source = await app.state.storage.content(content_id)
                if not source:
                    raise HTTPException(
                        404, "A selected source was deleted. Select a source again."
                    )
                if source["status"] != "ready":
                    raise HTTPException(
                        409,
                        "The selected source is not ready. Wait for processing or retry the source.",
                    )
        elif not body.all_sources:
            latest = await app.state.storage.run(
                "SELECT id,status FROM contents ORDER BY created_at DESC,rowid DESC LIMIT 1",
                fetch=True,
            )
            if latest:
                if latest[0]["status"] != "ready":
                    raise HTTPException(
                        409,
                        "The newest source is not ready. Wait or explicitly select another source.",
                    )
                body.content_ids = [latest[0]["id"]]
            else:
                raise HTTPException(422, "Upload and select a source before asking a question.")
        chat_id = None
        history = [t.model_dump() for t in body.history]
        if not body.incognito:
            chat_id = body.chat_id
            if chat_id:
                exists = await app.state.storage.run(
                    "SELECT id FROM chats WHERE id=?", (chat_id,), True
                )
                if not exists:
                    raise HTTPException(404, "Chat not found")
                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in (await app.state.storage.messages(chat_id))[-12:]
                ]
            else:
                chat_id = await app.state.storage.create_chat(body.query)

        def event(kind, data):
            return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        async def generate():
            started = time.monotonic()
            yield event("chat", {"id": chat_id})
            yield event("status", {"text": "Finding relevant moments and checking the context…"})
            try:
                async with app.state.chat_gate, asyncio.timeout(300):
                    evidence, coverage = await app.state.retriever.prepare(body, history)
                    yield event("coverage", coverage.model_dump())
                    sources = [e.model_dump() for e in evidence]
                    yield event("sources", sources)
                    answer = ""
                    if not evidence:
                        answer = "There is not enough evidence in the selected sources to answer. Add a source or specify the match and moment."
                        yield event("delta", {"text": answer})
                    else:
                        async for token in app.state.ai.answer(
                            body.query, history, evidence, coverage=coverage
                        ):
                            answer += token
                            yield event("delta", {"text": token})
                    if chat_id:
                        await app.state.storage.save_turn(
                            chat_id, body.query, answer, sources, coverage.model_dump()
                        )
                    yield event("done", {"seconds": round(time.monotonic() - started, 2)})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("chat_failed type=%s", type(exc).__name__)
                yield event(
                    "error",
                    {"message": chat_error_message(exc, settings.chat_provider)},
                )

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )

    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
