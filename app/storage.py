import asyncio
import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class Storage:
    """One local workspace. Short WAL transactions, durable ingestion queue."""

    def __init__(self, path: Path):
        self.path = path

    def _run(self, sql, args=(), fetch=False):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.row_factory = sqlite3.Row
            cursor = db.execute(sql, args)
            return [dict(r) for r in cursor.fetchall()] if fetch else None

    async def run(self, sql, args=(), fetch=False):
        return await asyncio.to_thread(self._run, sql, args, fetch)

    async def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await self.run("PRAGMA journal_mode=WAL")
        await self.run("""CREATE TABLE IF NOT EXISTS contents (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL,
            metadata TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            progress TEXT NOT NULL DEFAULT 'Queued', error TEXT,
            segments INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        await self.run("""CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY, title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        await self.run("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]')""")
        columns = await self.run("PRAGMA table_info(messages)", fetch=True)
        if not any(c["name"] == "coverage" for c in columns):
            await self.run("ALTER TABLE messages ADD COLUMN coverage TEXT")
        await self.run(
            "UPDATE contents SET status='queued', progress='Resuming' WHERE status='running'"
        )

    async def content(self, content_id):
        rows = await self.run("SELECT * FROM contents WHERE id=?", (content_id,), True)
        return rows[0] if rows else None

    async def create_chat(self, title):
        chat_id = str(uuid4())
        await self.run("INSERT INTO chats(id,title) VALUES (?,?)", (chat_id, title[:80]))
        return chat_id

    async def messages(self, chat_id):
        rows = await self.run(
            "SELECT * FROM messages WHERE chat_id=? ORDER BY id", (chat_id,), True
        )
        for row in rows:
            row["sources"] = json.loads(row["sources"])
            row["coverage"] = json.loads(row["coverage"]) if row.get("coverage") else None
        return rows

    async def message(self, chat_id, role, content, sources=None):
        await self.run(
            "INSERT INTO messages(chat_id,role,content,sources) VALUES (?,?,?,?)",
            (chat_id, role, content, json.dumps(sources or [], ensure_ascii=False)),
        )

    async def save_turn(self, chat_id, question, answer, sources, coverage=None):
        def commit():
            with sqlite3.connect(self.path, timeout=30) as db:
                db.executemany(
                    "INSERT INTO messages(chat_id,role,content,sources,coverage) VALUES (?,?,?,?,?)",
                    [
                        (chat_id, "user", question, "[]", None),
                        (
                            chat_id,
                            "assistant",
                            answer,
                            json.dumps(sources, ensure_ascii=False),
                            json.dumps(coverage) if coverage else None,
                        ),
                    ],
                )

        await asyncio.to_thread(commit)
