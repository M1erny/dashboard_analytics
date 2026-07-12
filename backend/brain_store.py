import json
import math
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
        self.database_label = str(self.db_path)
        self.storage_label = "sqlite"
        self.search_label = "sqlite_fts5"
        self.vector_search_label = "sqlite_cosine_after_embedding_backfill"
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

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    summary TEXT,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    page_start INTEGER,
                    page_end INTEGER,
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    content_hash TEXT NOT NULL,
                    embedding_model TEXT,
                    embedding TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_id, content_hash),
                    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
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

                CREATE TABLE IF NOT EXISTS brain_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
                CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
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

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "body": row["body"],
            "author": row["author"],
            "sourceDate": row["source_date"],
            "tags": BrainStore._json_loads(row["tags"], []),
            "metadata": BrainStore._json_loads(row["metadata"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _chunk_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "sourceId": row["source_id"],
            "ordinal": row["ordinal"],
            "title": row["title"],
            "body": row["body"],
            "summary": row["summary"],
            "tokenCount": row["token_count"],
            "pageStart": row["page_start"],
            "pageEnd": row["page_end"],
            "tags": BrainStore._json_loads(row["tags"], []),
            "metadata": BrainStore._json_loads(row["metadata"], {}),
            "contentHash": row["content_hash"],
            "embeddingModel": row["embedding_model"],
            "hasEmbedding": bool(row["embedding"]),
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
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            return self._source_from_row(row)

    def upsert_file_source(
        self,
        *,
        title: str,
        body: str,
        tags: list[str] | None = None,
        author: str | None = None,
        source_date: str | None = None,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        title = title.strip()
        body = body.strip()
        if not title or not body:
            raise ValueError("title and body are required")

        clean_metadata = metadata or {}
        file_identity = str(clean_metadata.get("fileIdentity") or "").strip()
        file_hash = str(clean_metadata.get("fileHash") or "").strip()
        if not file_identity or not file_hash:
            raise ValueError("metadata.fileIdentity and metadata.fileHash are required")

        clean_tags = self._clean_tags(tags)
        now = self._now()
        with self._lock, self._connect() as conn:
            existing = None
            for row in conn.execute("SELECT * FROM sources WHERE kind = 'file'").fetchall():
                row_metadata = self._json_loads(row["metadata"], {})
                if row_metadata.get("fileIdentity") == file_identity:
                    existing = row
                    existing_metadata = row_metadata
                    break

            if existing:
                if existing_metadata.get("fileHash") == file_hash and not force:
                    return self._source_from_row(existing), False

                chunk_ids = [
                    str(row["id"])
                    for row in conn.execute("SELECT id FROM chunks WHERE source_id = ?", (existing["id"],)).fetchall()
                ]
                conn.execute("DELETE FROM chunks WHERE source_id = ?", (existing["id"],))
                for chunk_id in chunk_ids:
                    conn.execute(
                        "DELETE FROM brain_index WHERE entity_type = 'chunk' AND entity_id = ?",
                        (chunk_id,),
                    )
                conn.execute(
                    """
                    UPDATE sources
                       SET title = ?,
                           body = ?,
                           author = ?,
                           source_date = ?,
                           tags = ?,
                           metadata = ?,
                           updated_at = ?
                     WHERE id = ?
                    """,
                    (
                        title,
                        body,
                        author,
                        source_date,
                        self._json_dumps(clean_tags),
                        self._json_dumps(clean_metadata),
                        now,
                        existing["id"],
                    ),
                )
                self._replace_index(conn, "source", int(existing["id"]), title, body, clean_tags)
                row = conn.execute("SELECT * FROM sources WHERE id = ?", (existing["id"],)).fetchone()
                return self._source_from_row(row), True

            cur = conn.execute(
                """
                INSERT INTO sources(kind, title, body, author, source_date, tags, metadata, created_at, updated_at)
                VALUES ('file', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            return self._source_from_row(row), True

    def list_sources(
        self,
        query: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        fts_query = self._safe_fts_query(query)
        with self._lock, self._connect() as conn:
            params: list[Any] = []
            if fts_query:
                sql = """
                    SELECT DISTINCT s.*
                    FROM sources s
                    JOIN brain_index i
                      ON i.entity_type = 'source'
                     AND i.entity_id = CAST(s.id AS TEXT)
                    WHERE brain_index MATCH ?
                """
                params.append(fts_query)
                if kind:
                    sql += " AND s.kind = ?"
                    params.append(kind.strip().lower())
                sql += " ORDER BY s.created_at DESC LIMIT ?"
                params.append(limit)
            else:
                sql = "SELECT * FROM sources"
                if kind:
                    sql += " WHERE kind = ?"
                    params.append(kind.strip().lower())
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

            return [self._source_from_row(row) for row in conn.execute(sql, params).fetchall()]

    def get_source(self, source_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            return self._source_from_row(row) if row else None

    def get_file_source_by_identity(self, file_identity: str) -> dict[str, Any] | None:
        file_identity = str(file_identity or "").strip()
        if not file_identity:
            return None

        with self._lock, self._connect() as conn:
            for row in conn.execute("SELECT * FROM sources WHERE kind = 'file'").fetchall():
                metadata = self._json_loads(row["metadata"], {})
                if metadata.get("fileIdentity") == file_identity:
                    return self._source_from_row(row)
        return None

    def list_file_source_lookup(self) -> list[dict[str, Any]]:
        """Return the compact metadata needed by a local indexing pass in one query."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, metadata FROM sources WHERE kind = 'file'"
            ).fetchall()
            return [
                {"id": int(row["id"]), "metadata": self._json_loads(row["metadata"], {})}
                for row in rows
            ]

    def get_file_source_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        file_hash = str(file_hash or "").strip()
        if not file_hash:
            return None

        with self._lock, self._connect() as conn:
            for row in conn.execute("SELECT * FROM sources WHERE kind = 'file' ORDER BY id").fetchall():
                metadata = self._json_loads(row["metadata"], {})
                if metadata.get("fileHash") == file_hash:
                    return self._source_from_row(row)
        return None

    def add_chunks(self, source_id: int, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not chunks:
            return []

        now = self._now()
        saved: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            source = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            if not source:
                raise ValueError(f"Source {source_id} does not exist")

            for index, chunk in enumerate(chunks):
                title = str(chunk.get("title") or f"{source['title']} - chunk {index + 1}").strip()
                body = str(chunk.get("body") or "").strip()
                if not body:
                    continue

                tags = self._clean_tags(chunk.get("tags") or self._json_loads(source["tags"], []))
                metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
                content_hash = str(chunk.get("contentHash") or chunk.get("content_hash") or "").strip()
                if not content_hash:
                    raise ValueError("Chunk contentHash is required")

                conn.execute(
                    """
                    INSERT INTO chunks(
                        source_id, ordinal, title, body, summary, token_count, page_start, page_end,
                        tags, metadata, content_hash, embedding_model, embedding, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, content_hash) DO UPDATE SET
                        ordinal = excluded.ordinal,
                        title = excluded.title,
                        body = excluded.body,
                        summary = excluded.summary,
                        token_count = excluded.token_count,
                        page_start = excluded.page_start,
                        page_end = excluded.page_end,
                        tags = excluded.tags,
                        metadata = excluded.metadata,
                        embedding_model = excluded.embedding_model,
                        embedding = excluded.embedding,
                        updated_at = excluded.updated_at
                    """,
                    (
                        source_id,
                        int(chunk.get("ordinal") or index),
                        title,
                        body,
                        chunk.get("summary"),
                        int(chunk.get("tokenCount") or chunk.get("token_count") or 0),
                        chunk.get("pageStart") or chunk.get("page_start"),
                        chunk.get("pageEnd") or chunk.get("page_end"),
                        self._json_dumps(tags),
                        self._json_dumps(metadata),
                        content_hash,
                        chunk.get("embeddingModel") or chunk.get("embedding_model"),
                        self._json_dumps(chunk.get("embedding")) if chunk.get("embedding") is not None else None,
                        now,
                        now,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM chunks WHERE source_id = ? AND content_hash = ?",
                    (source_id, content_hash),
                ).fetchone()
                indexed_body = f"{body}\n\n{row['summary'] or ''}".strip()
                self._replace_index(conn, "chunk", int(row["id"]), title, indexed_body, tags)
                saved.append(self._chunk_from_row(row))

        return saved

    def list_chunks(
        self,
        source_id: int | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        fts_query = self._safe_fts_query(query)
        with self._lock, self._connect() as conn:
            params: list[Any] = []
            if fts_query:
                sql = """
                    SELECT DISTINCT c.*
                    FROM chunks c
                    JOIN brain_index i
                      ON i.entity_type = 'chunk'
                     AND i.entity_id = CAST(c.id AS TEXT)
                    WHERE brain_index MATCH ?
                """
                params.append(fts_query)
                if source_id is not None:
                    sql += " AND c.source_id = ?"
                    params.append(source_id)
                sql += " ORDER BY c.source_id, c.ordinal LIMIT ?"
                params.append(limit)
            else:
                sql = "SELECT * FROM chunks"
                if source_id is not None:
                    sql += " WHERE source_id = ?"
                    params.append(source_id)
                sql += " ORDER BY source_id, ordinal LIMIT ?"
                params.append(limit)

            return [self._chunk_from_row(row) for row in conn.execute(sql, params).fetchall()]

    def list_chunks_for_embedding(
        self,
        *,
        limit: int = 50,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            sql = "SELECT * FROM chunks"
            if not force:
                sql += " WHERE embedding IS NULL OR embedding = ''"
            sql += " ORDER BY source_id, ordinal LIMIT ?"
            return [self._chunk_from_row_with_embedding(row) for row in conn.execute(sql, (limit,)).fetchall()]

    def embedding_stats(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN embedding IS NOT NULL AND embedding != '' THEN 1 ELSE 0 END) AS embedded
                  FROM chunks
                """
            ).fetchone()
            model_rows = conn.execute(
                """
                SELECT embedding_model, COUNT(*) AS count
                  FROM chunks
                 WHERE embedding IS NOT NULL AND embedding != ''
                 GROUP BY embedding_model
                 ORDER BY count DESC
                """
            ).fetchall()

        total = int(row["total"] or 0)
        embedded = int(row["embedded"] or 0)
        return {
            "total": total,
            "embedded": embedded,
            "missing": max(0, total - embedded),
            "coverage": (embedded / total) if total else 0,
            "models": [
                {"model": model_row["embedding_model"] or "unknown", "count": int(model_row["count"] or 0)}
                for model_row in model_rows
            ],
        }

    @staticmethod
    def _chunk_from_row_with_embedding(row: sqlite3.Row) -> dict[str, Any]:
        chunk = BrainStore._chunk_from_row(row)
        chunk["embedding"] = BrainStore._json_loads(row["embedding"], None)
        return chunk

    def update_chunk_embedding(
        self,
        chunk_id: int,
        *,
        embedding_model: str,
        embedding: list[float],
    ) -> None:
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE chunks
                   SET embedding_model = ?,
                       embedding = ?,
                       updated_at = ?
                 WHERE id = ?
                """,
                (embedding_model, self._json_dumps(embedding), now, chunk_id),
            )

    def update_chunk_embeddings(
        self,
        *,
        embedding_model: str,
        updates: list[tuple[int, list[float]]],
    ) -> None:
        if not updates:
            return
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                UPDATE chunks
                   SET embedding_model = ?,
                       embedding = ?,
                       updated_at = ?
                 WHERE id = ?
                """,
                [
                    (embedding_model, self._json_dumps(embedding), now, int(chunk_id))
                    for chunk_id, embedding in updates
                ],
            )

    def semantic_search_chunks(
        self,
        query_embedding: list[float],
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        query_norm = math.sqrt(sum(value * value for value in query_embedding))
        if query_norm == 0:
            return []

        scored: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE embedding IS NOT NULL AND embedding != ''"
            ).fetchall()

        for row in rows:
            embedding = self._json_loads(row["embedding"], None)
            if not isinstance(embedding, list) or len(embedding) != len(query_embedding):
                continue

            dot = 0.0
            chunk_norm_sq = 0.0
            for left, right in zip(query_embedding, embedding):
                right_value = float(right)
                dot += left * right_value
                chunk_norm_sq += right_value * right_value
            chunk_norm = math.sqrt(chunk_norm_sq)
            if chunk_norm == 0:
                continue

            result = self._chunk_from_row(row)
            result["score"] = dot / (query_norm * chunk_norm)
            scored.append(result)

        return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]

    def semantic_search_chunks_in_sources(
        self,
        query_embedding: list[float],
        source_ids: list[int],
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """SQLite equivalent of the scoped pgvector search used by reference sources."""
        clean_source_ids = list(dict.fromkeys(
            int(source_id)
            for source_id in source_ids
            if isinstance(source_id, int) or str(source_id).strip().isdigit()
        ))
        limit = max(1, min(int(limit), 100))
        query_norm = math.sqrt(sum(value * value for value in query_embedding))
        if not clean_source_ids or query_norm == 0:
            return []

        placeholders = ", ".join("?" for _ in clean_source_ids)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE source_id IN ({placeholders}) AND embedding IS NOT NULL AND embedding != ''",
                clean_source_ids,
            ).fetchall()

        scored: list[dict[str, Any]] = []
        for row in rows:
            embedding = self._json_loads(row["embedding"], None)
            if not isinstance(embedding, list) or len(embedding) != len(query_embedding):
                continue

            dot = 0.0
            chunk_norm_sq = 0.0
            for left, right in zip(query_embedding, embedding):
                right_value = float(right)
                dot += left * right_value
                chunk_norm_sq += right_value * right_value
            chunk_norm = math.sqrt(chunk_norm_sq)
            if chunk_norm == 0:
                continue

            result = self._chunk_from_row(row)
            result["score"] = dot / (query_norm * chunk_norm)
            scored.append(result)

        return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]

    def get_setting(self, key: str) -> str | None:
        clean_key = str(key or "").strip()
        if not clean_key:
            return None

        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM brain_settings WHERE key = ?", (clean_key,)).fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        clean_key = str(key or "").strip()
        clean_value = str(value or "").strip()
        if not clean_key or not clean_value:
            raise ValueError("key and value are required")

        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO brain_settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (clean_key, clean_value, now),
            )

    def delete_source(self, source_id: int) -> bool:
        with self._lock, self._connect() as conn:
            chunk_ids = [
                str(row["id"])
                for row in conn.execute("SELECT id FROM chunks WHERE source_id = ?", (source_id,)).fetchall()
            ]
            cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.execute(
                "DELETE FROM brain_index WHERE entity_type = 'source' AND entity_id = ?",
                (str(source_id),),
            )
            for chunk_id in chunk_ids:
                conn.execute(
                    "DELETE FROM brain_index WHERE entity_type = 'chunk' AND entity_id = ?",
                    (chunk_id,),
                )
            return cur.rowcount > 0

    def search(self, query: str, limit: int = 50, entity_type: str | None = None) -> list[dict[str, Any]]:
        fts_query = self._safe_fts_query(query)
        if not fts_query:
            return []

        limit = max(1, min(int(limit), 200))
        params: list[Any] = [fts_query]
        sql = """
            SELECT brain_index.entity_type,
                   brain_index.entity_id,
                   brain_index.title,
                   brain_index.body,
                   brain_index.tags,
                   CASE
                       WHEN brain_index.entity_type = 'source' THEN CAST(brain_index.entity_id AS INTEGER)
                       ELSE c.source_id
                   END AS source_id,
                   bm25(brain_index) AS rank
            FROM brain_index
            LEFT JOIN chunks c
              ON brain_index.entity_type = 'chunk'
             AND c.id = CAST(brain_index.entity_id AS INTEGER)
            WHERE brain_index MATCH ?
        """
        if entity_type:
            sql += " AND brain_index.entity_type = ?"
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
                    "sourceId": int(row["source_id"]) if row["source_id"] is not None else None,
                }
                for row in conn.execute(sql, params).fetchall()
            ]

    def counts(self) -> dict[str, int]:
        with self._lock, self._connect() as conn:
            tables = ["memories", "sources", "chunks", "ideas", "theses", "edges"]
            result = {
                table: int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])
                for table in tables
            }
            result["indexed"] = int(conn.execute("SELECT COUNT(*) AS c FROM brain_index").fetchone()["c"])
            return result


def create_brain_store():
    database_url = os.environ.get("BRAIN_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if database_url:
        from brain_store_postgres import PostgresBrainStore

        return PostgresBrainStore(database_url)

    return BrainStore()
