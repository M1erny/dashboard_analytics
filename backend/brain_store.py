import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MEMORY_TYPES = {"liked", "passed", "trend", "framework", "question"}
DEFAULT_DB_PATH = Path(__file__).with_name("brain.db")


class BrainStore:
    """SQLite persistence and unified full-text search for the Investment Brain."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None):
        configured_path = os.environ.get("BRAIN_DB_FILE")
        self.db_path = Path(db_path or configured_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL CHECK (type IN ('liked', 'passed', 'trend', 'framework', 'question')),
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'manual',
                    confidence REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL DEFAULT 'note',
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    author TEXT,
                    source_date TEXT,
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ideas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER,
                    kind TEXT NOT NULL DEFAULT 'principle',
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    confidence REAL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS theses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'watchlist',
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_type TEXT NOT NULL,
                    from_id INTEGER NOT NULL,
                    to_type TEXT NOT NULL,
                    to_id INTEGER NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS brain_index USING fts5(
                    entity_type UNINDEXED,
                    entity_id UNINDEXED,
                    title,
                    body,
                    tags,
                    tokenize='unicode61 remove_diacritics 2'
                );

                CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
                CREATE INDEX IF NOT EXISTS idx_sources_kind ON sources(kind);
                CREATE INDEX IF NOT EXISTS idx_ideas_kind ON ideas(kind);
                CREATE INDEX IF NOT EXISTS idx_theses_company ON theses(company);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _json_loads(value: str, fallback: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _clean_tags(tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        cleaned = []
        seen = set()
        for tag in tags:
            normalized = str(tag).strip().lower()
            if normalized and normalized not in seen:
                cleaned.append(normalized[:80])
                seen.add(normalized)
        return cleaned[:20]

    @staticmethod
    def _safe_fts_query(query: str | None) -> str | None:
        if not query:
            return None
        tokens = re.findall(r"[\w]+", query.lower(), flags=re.UNICODE)
        tokens = [token for token in tokens if len(token) > 1]
        if not tokens:
            return None
        return " OR ".join(f"{token}*" for token in tokens[:12])

    @staticmethod
    def _memory_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "title": row["title"],
            "body": row["body"],
            "tags": BrainStore._json_loads(row["tags"], []),
            "source": row["source"],
            "confidence": row["confidence"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _replace_index(
        self,
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: int,
        title: str,
        body: str,
        tags: list[str],
    ) -> None:
        conn.execute(
            "DELETE FROM brain_index WHERE entity_type = ? AND entity_id = ?",
            (entity_type, str(entity_id)),
        )
        conn.execute(
            """
            INSERT INTO brain_index(entity_type, entity_id, title, body, tags)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entity_type, str(entity_id), title, body, " ".join(tags)),
        )

    def add_memory(
        self,
        memory_type: str,
        title: str,
        body: str,
        tags: list[str] | None = None,
        source: str = "manual",
        confidence: float | None = None,
    ) -> dict[str, Any]:
        memory_type = memory_type.strip().lower()
        if memory_type not in MEMORY_TYPES:
            raise ValueError(f"Unsupported memory type: {memory_type}")

        title = title.strip()
        body = body.strip()
        if not title or not body:
            raise ValueError("title and body are required")

        clean_tags = self._clean_tags(tags)
        now = self._now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO memories(type, title, body, tags, source, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (memory_type, title, body, self._json_dumps(clean_tags), source, confidence, now, now),
            )
            memory_id = int(cur.lastrowid)
            self._replace_index(conn, "memory", memory_id, title, body, clean_tags)
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            return self._memory_from_row(row)

    def list_memories(
        self,
        query: str | None = None,
        memory_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        if memory_type:
            memory_type = memory_type.strip().lower()
            if memory_type not in MEMORY_TYPES:
                raise ValueError(f"Unsupported memory type: {memory_type}")

        fts_query = self._safe_fts_query(query)
        with self._lock, self._connect() as conn:
            params: list[Any] = []
            if fts_query:
                sql = """
                    SELECT DISTINCT m.*
                    FROM memories m
                    JOIN brain_index i
                      ON i.entity_type = 'memory'
                     AND i.entity_id = CAST(m.id AS TEXT)
                    WHERE brain_index MATCH ?
                """
                params.append(fts_query)
                if memory_type:
                    sql += " AND m.type = ?"
                    params.append(memory_type)
                sql += " ORDER BY m.created_at DESC LIMIT ?"
                params.append(limit)
            else:
                sql = "SELECT * FROM memories"
                if memory_type:
                    sql += " WHERE type = ?"
                    params.append(memory_type)
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

            return [self._memory_from_row(row) for row in conn.execute(sql, params).fetchall()]

    def delete_memory(self, memory_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.execute(
                "DELETE FROM brain_index WHERE entity_type = 'memory' AND entity_id = ?",
                (str(memory_id),),
            )
            return cur.rowcount > 0

    def add_source(
        self,
        kind: str,
        title: str,
        body: str,
        tags: list[str] | None = None,
        author: str | None = None,
        source_date: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        body = body.strip()
        if not title or not body:
            raise ValueError("title and body are required")

        clean_tags = self._clean_tags(tags)
        clean_metadata = metadata or {}
        now = self._now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO sources(kind, title, body, author, source_date, tags, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind.strip().lower() or "note",
                    title,
                    body,
                    author,
                    source_date,
                    self._json_dumps(clean_tags),
                    self._json_dumps(clean_metadata),
                    now,
                    now,
                ),
            )
            source_id = int(cur.lastrowid)
            self._replace_index(conn, "source", source_id, title, body, clean_tags)
            return {
                "id": source_id,
                "kind": kind,
                "title": title,
                "body": body,
                "author": author,
                "sourceDate": source_date,
                "tags": clean_tags,
                "metadata": clean_metadata,
                "createdAt": now,
                "updatedAt": now,
            }

    def search(self, query: str, limit: int = 50, entity_type: str | None = None) -> list[dict[str, Any]]:
        fts_query = self._safe_fts_query(query)
        if not fts_query:
            return []

        limit = max(1, min(int(limit), 200))
        params: list[Any] = [fts_query]
        sql = """
            SELECT entity_type, entity_id, title, body, tags, bm25(brain_index) AS rank
            FROM brain_index
            WHERE brain_index MATCH ?
        """
        if entity_type:
            sql += " AND entity_type = ?"
            params.append(entity_type)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        with self._lock, self._connect() as conn:
            return [
                {
                    "entityType": row["entity_type"],
                    "entityId": int(row["entity_id"]),
                    "title": row["title"],
                    "body": row["body"],
                    "tags": row["tags"].split() if row["tags"] else [],
                    "rank": row["rank"],
                }
                for row in conn.execute(sql, params).fetchall()
            ]

    def counts(self) -> dict[str, int]:
        with self._lock, self._connect() as conn:
            tables = ["memories", "sources", "ideas", "theses", "edges"]
            result = {
                table: int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])
                for table in tables
            }
            result["indexed"] = int(conn.execute("SELECT COUNT(*) AS c FROM brain_index").fetchone()["c"])
            return result
