import json
import math
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


MEMORY_TYPES = {"liked", "passed", "trend", "framework", "question"}
EMBEDDING_DIMENSIONS = 3072


CHUNK_COLUMNS = """
    c.id,
    c.source_id,
    c.ordinal,
    c.title,
    c.body,
    c.summary,
    c.token_count,
    c.page_start,
    c.page_end,
    c.tags,
    c.metadata,
    c.content_hash,
    c.embedding_model,
    c.embedding::text AS embedding,
    c.created_at,
    c.updated_at
"""


CHUNK_RETURNING_COLUMNS = """
    id,
    source_id,
    ordinal,
    title,
    body,
    summary,
    token_count,
    page_start,
    page_end,
    tags,
    metadata,
    content_hash,
    embedding_model,
    embedding::text AS embedding,
    created_at,
    updated_at
"""


class _NoopLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class PostgresBrainStore:
    """Postgres/pgvector persistence for the Investment Brain."""

    storage_label = "postgres_pgvector"
    search_label = "postgres_full_text"
    vector_search_label = "pgvector_cosine"
    search_stopwords = {
        "about",
        "again",
        "against",
        "also",
        "and",
        "answer",
        "are",
        "brain",
        "can",
        "could",
        "does",
        "for",
        "from",
        "have",
        "how",
        "into",
        "its",
        "just",
        "like",
        "look",
        "make",
        "might",
        "more",
        "most",
        "must",
        "my",
        "need",
        "needs",
        "not",
        "our",
        "question",
        "say",
        "should",
        "show",
        "that",
        "the",
        "their",
        "this",
        "through",
        "using",
        "what",
        "when",
        "where",
        "which",
        "with",
        "would",
        "your",
    }

    def __init__(self, database_url: str | None = None):
        self.database_url = self._normalize_database_url(
            database_url
            or os.environ.get("BRAIN_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or ""
        )
        if not self.database_url:
            raise ValueError("DATABASE_URL or BRAIN_DATABASE_URL is required for Postgres brain storage")

        self.database_label = self._safe_database_label(self.database_url)
        self.db_path = self.database_label
        self.statement_timeout_ms = self._env_int("BRAIN_POSTGRES_STATEMENT_TIMEOUT_MS", 12000)
        self.lock_timeout_ms = self._env_int("BRAIN_POSTGRES_LOCK_TIMEOUT_MS", 4000)
        self.idle_transaction_timeout_ms = self._env_int("BRAIN_POSTGRES_IDLE_TIMEOUT_MS", 30000)
        self._lock = _NoopLock()
        self._init_db()

    @staticmethod
    def _normalize_database_url(database_url: str) -> str:
        value = database_url.strip()
        if not value:
            return value

        parsed = urlparse(value)
        hostname = parsed.hostname or ""
        if "supabase" not in hostname.lower():
            return value

        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if any(key.lower() == "sslmode" for key, _ in query_pairs):
            return value

        query_pairs.append(("sslmode", "require"))
        return urlunparse(parsed._replace(query=urlencode(query_pairs)))

    @staticmethod
    def _safe_database_label(database_url: str) -> str:
        parsed = urlparse(database_url)
        host = parsed.hostname or "postgres"
        port = f":{parsed.port}" if parsed.port else ""
        name = (parsed.path or "/postgres").lstrip("/") or "postgres"
        return f"postgresql://{host}{port}/{name}"

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    @contextmanager
    def _connect(self):
        conn = psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            prepare_threshold=None,
            connect_timeout=10,
            options=(
                f"-c statement_timeout={self.statement_timeout_ms} "
                f"-c lock_timeout={self.lock_timeout_ms} "
                f"-c idle_in_transaction_session_timeout={self.idle_transaction_timeout_ms}"
            ),
        )
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
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id BIGSERIAL PRIMARY KEY,
                    type TEXT NOT NULL CHECK (type IN ('liked', 'passed', 'trend', 'framework', 'question')),
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    source TEXT NOT NULL DEFAULT 'manual',
                    confidence DOUBLE PRECISION,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id BIGSERIAL PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT 'note',
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    author TEXT,
                    source_date TEXT,
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                    id BIGSERIAL PRIMARY KEY,
                    source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    summary TEXT,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    page_start INTEGER,
                    page_end INTEGER,
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    content_hash TEXT NOT NULL,
                    embedding_model TEXT,
                    embedding vector({EMBEDDING_DIMENSIONS}),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_id, content_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ideas (
                    id BIGSERIAL PRIMARY KEY,
                    source_id BIGINT REFERENCES sources(id) ON DELETE SET NULL,
                    kind TEXT NOT NULL DEFAULT 'principle',
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    confidence DOUBLE PRECISION,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS theses (
                    id BIGSERIAL PRIMARY KEY,
                    company TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'watchlist',
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS edges (
                    id BIGSERIAL PRIMARY KEY,
                    from_type TEXT NOT NULL,
                    from_id BIGINT NOT NULL,
                    to_type TEXT NOT NULL,
                    to_id BIGINT NOT NULL,
                    relation TEXT NOT NULL,
                    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_index (
                    entity_type TEXT NOT NULL,
                    entity_id BIGINT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '',
                    search_vector TSVECTOR GENERATED ALWAYS AS (
                        to_tsvector(
                            'simple',
                            coalesce(title, '') || ' ' || coalesce(body, '') || ' ' || coalesce(tags, '')
                        )
                    ) STORED,
                    PRIMARY KEY(entity_type, entity_id)
                )
                """
            )

            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_kind ON sources(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_file_identity ON sources ((metadata->>'fileIdentity'))")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_embedding_model ON chunks(embedding_model)")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_missing_embedding_order
                ON chunks(source_id, ordinal)
                WHERE embedding IS NULL
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ideas_kind ON ideas(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_theses_company ON theses(company)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_brain_index_search ON brain_index USING GIN(search_vector)")
            conn.execute("SAVEPOINT vector_index")
            try:
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
                    ON chunks USING hnsw (embedding vector_cosine_ops)
                    WHERE embedding IS NOT NULL
                    """
                )
                conn.execute("RELEASE SAVEPOINT vector_index")
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT vector_index")
                conn.execute("RELEASE SAVEPOINT vector_index")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json_loads(value: Any, fallback: Any) -> Any:
        if value is None:
            return fallback
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value))
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
    def _safe_fts_query(query: str | None, *, operator: str = "|") -> str | None:
        if not query:
            return None
        tokens = re.findall(r"[\w]+", query.lower(), flags=re.UNICODE)
        tokens = [
            token
            for token in tokens
            if len(token) > 1 and token not in PostgresBrainStore.search_stopwords
        ]
        if not tokens:
            return None
        joiner = " & " if operator == "&" else " | "
        return joiner.join(f"{token}:*" for token in tokens[:12])

    @staticmethod
    def _embedding_literal(embedding: list[float] | None) -> str | None:
        if embedding is None:
            return None
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Expected {EMBEDDING_DIMENSIONS} embedding dimensions, got {len(embedding)}")
        return "[" + ",".join(f"{float(value):.12g}" for value in embedding) + "]"

    @staticmethod
    def _parse_embedding(value: Any) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(item) for item in value]
        text = str(value).strip()
        if not text:
            return None
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        if not text:
            return []
        return [float(part) for part in text.split(",") if part.strip()]

    @staticmethod
    def _memory_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "type": row["type"],
            "title": row["title"],
            "body": row["body"],
            "tags": PostgresBrainStore._json_loads(row["tags"], []),
            "source": row["source"],
            "confidence": row["confidence"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _source_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "kind": row["kind"],
            "title": row["title"],
            "body": row["body"],
            "author": row["author"],
            "sourceDate": row["source_date"],
            "tags": PostgresBrainStore._json_loads(row["tags"], []),
            "metadata": PostgresBrainStore._json_loads(row["metadata"], {}),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _chunk_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "sourceId": int(row["source_id"]),
            "ordinal": row["ordinal"],
            "title": row["title"],
            "body": row["body"],
            "summary": row["summary"],
            "tokenCount": row["token_count"],
            "pageStart": row["page_start"],
            "pageEnd": row["page_end"],
            "tags": PostgresBrainStore._json_loads(row["tags"], []),
            "metadata": PostgresBrainStore._json_loads(row["metadata"], {}),
            "contentHash": row["content_hash"],
            "embeddingModel": row["embedding_model"],
            "hasEmbedding": bool(row["embedding"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _chunk_from_row_with_embedding(row: dict[str, Any]) -> dict[str, Any]:
        chunk = PostgresBrainStore._chunk_from_row(row)
        chunk["embedding"] = PostgresBrainStore._parse_embedding(row.get("embedding"))
        return chunk

    def _replace_index(
        self,
        conn,
        entity_type: str,
        entity_id: int,
        title: str,
        body: str,
        tags: list[str],
    ) -> None:
        conn.execute(
            "DELETE FROM brain_index WHERE entity_type = %s AND entity_id = %s",
            (entity_type, entity_id),
        )
        conn.execute(
            """
            INSERT INTO brain_index(entity_type, entity_id, title, body, tags)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                title = excluded.title,
                body = excluded.body,
                tags = excluded.tags
            """,
            (entity_type, entity_id, title, body, " ".join(tags)),
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
            row = conn.execute(
                """
                INSERT INTO memories(type, title, body, tags, source, confidence, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (memory_type, title, body, Jsonb(clean_tags), source, confidence, now, now),
            ).fetchone()
            self._replace_index(conn, "memory", int(row["id"]), title, body, clean_tags)
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
                     AND i.entity_id = m.id
                    WHERE i.search_vector @@ to_tsquery('simple', %s)
                """
                params.append(fts_query)
                if memory_type:
                    sql += " AND m.type = %s"
                    params.append(memory_type)
                sql += " ORDER BY m.created_at DESC LIMIT %s"
                params.append(limit)
            else:
                sql = "SELECT * FROM memories"
                if memory_type:
                    sql += " WHERE type = %s"
                    params.append(memory_type)
                sql += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)

            return [self._memory_from_row(row) for row in conn.execute(sql, params).fetchall()]

    def delete_memory(self, memory_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
            conn.execute(
                "DELETE FROM brain_index WHERE entity_type = 'memory' AND entity_id = %s",
                (memory_id,),
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
            row = conn.execute(
                """
                INSERT INTO sources(kind, title, body, author, source_date, tags, metadata, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    kind.strip().lower() or "note",
                    title,
                    body,
                    author,
                    source_date,
                    Jsonb(clean_tags),
                    Jsonb(clean_metadata),
                    now,
                    now,
                ),
            ).fetchone()
            self._replace_index(conn, "source", int(row["id"]), title, body, clean_tags)
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
            existing = conn.execute(
                "SELECT * FROM sources WHERE kind = 'file' AND metadata->>'fileIdentity' = %s LIMIT 1",
                (file_identity,),
            ).fetchone()

            if existing:
                existing_metadata = self._json_loads(existing["metadata"], {})
                if existing_metadata.get("fileHash") == file_hash and not force:
                    return self._source_from_row(existing), False

                chunk_rows = conn.execute(
                    "DELETE FROM chunks WHERE source_id = %s RETURNING id",
                    (existing["id"],),
                ).fetchall()
                for chunk in chunk_rows:
                    conn.execute(
                        "DELETE FROM brain_index WHERE entity_type = 'chunk' AND entity_id = %s",
                        (chunk["id"],),
                    )

                row = conn.execute(
                    """
                    UPDATE sources
                       SET title = %s,
                           body = %s,
                           author = %s,
                           source_date = %s,
                           tags = %s,
                           metadata = %s,
                           updated_at = %s
                     WHERE id = %s
                     RETURNING *
                    """,
                    (
                        title,
                        body,
                        author,
                        source_date,
                        Jsonb(clean_tags),
                        Jsonb(clean_metadata),
                        now,
                        existing["id"],
                    ),
                ).fetchone()
                self._replace_index(conn, "source", int(row["id"]), title, body, clean_tags)
                return self._source_from_row(row), True

            row = conn.execute(
                """
                INSERT INTO sources(kind, title, body, author, source_date, tags, metadata, created_at, updated_at)
                VALUES ('file', %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    title,
                    body,
                    author,
                    source_date,
                    Jsonb(clean_tags),
                    Jsonb(clean_metadata),
                    now,
                    now,
                ),
            ).fetchone()
            self._replace_index(conn, "source", int(row["id"]), title, body, clean_tags)
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
                     AND i.entity_id = s.id
                    WHERE i.search_vector @@ to_tsquery('simple', %s)
                """
                params.append(fts_query)
                if kind:
                    sql += " AND s.kind = %s"
                    params.append(kind.strip().lower())
                sql += " ORDER BY s.created_at DESC LIMIT %s"
                params.append(limit)
            else:
                sql = "SELECT * FROM sources"
                if kind:
                    sql += " WHERE kind = %s"
                    params.append(kind.strip().lower())
                sql += " ORDER BY created_at DESC LIMIT %s"
                params.append(limit)

            return [self._source_from_row(row) for row in conn.execute(sql, params).fetchall()]

    def get_source(self, source_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = %s", (source_id,)).fetchone()
            return self._source_from_row(row) if row else None

    def get_file_source_by_identity(self, file_identity: str) -> dict[str, Any] | None:
        file_identity = str(file_identity or "").strip()
        if not file_identity:
            return None

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sources WHERE kind = 'file' AND metadata->>'fileIdentity' = %s LIMIT 1",
                (file_identity,),
            ).fetchone()
            return self._source_from_row(row) if row else None

    def get_file_source_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        file_hash = str(file_hash or "").strip()
        if not file_hash:
            return None

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sources WHERE kind = 'file' AND metadata->>'fileHash' = %s ORDER BY id LIMIT 1",
                (file_hash,),
            ).fetchone()
            return self._source_from_row(row) if row else None

    def add_chunks(self, source_id: int, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not chunks:
            return []

        now = self._now()
        saved: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            source = conn.execute("SELECT * FROM sources WHERE id = %s", (source_id,)).fetchone()
            if not source:
                raise ValueError(f"Source {source_id} does not exist")

            source_tags = self._json_loads(source["tags"], [])
            for index, chunk in enumerate(chunks):
                title = str(chunk.get("title") or f"{source['title']} - chunk {index + 1}").strip()
                body = str(chunk.get("body") or "").strip()
                if not body:
                    continue

                tags = self._clean_tags(chunk.get("tags") or source_tags)
                metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
                content_hash = str(chunk.get("contentHash") or chunk.get("content_hash") or "").strip()
                if not content_hash:
                    raise ValueError("Chunk contentHash is required")

                embedding_literal = self._embedding_literal(chunk.get("embedding"))
                row = conn.execute(
                    f"""
                    INSERT INTO chunks(
                        source_id, ordinal, title, body, summary, token_count, page_start, page_end,
                        tags, metadata, content_hash, embedding_model, embedding, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s)
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
                    RETURNING {CHUNK_RETURNING_COLUMNS}
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
                        Jsonb(tags),
                        Jsonb(metadata),
                        content_hash,
                        chunk.get("embeddingModel") or chunk.get("embedding_model"),
                        embedding_literal,
                        now,
                        now,
                    ),
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
                sql = f"""
                    SELECT DISTINCT {CHUNK_COLUMNS}
                    FROM chunks c
                    JOIN brain_index i
                      ON i.entity_type = 'chunk'
                     AND i.entity_id = c.id
                    WHERE i.search_vector @@ to_tsquery('simple', %s)
                """
                params.append(fts_query)
                if source_id is not None:
                    sql += " AND c.source_id = %s"
                    params.append(source_id)
                sql += " ORDER BY c.source_id, c.ordinal LIMIT %s"
                params.append(limit)
            else:
                sql = f"SELECT {CHUNK_COLUMNS} FROM chunks c"
                if source_id is not None:
                    sql += " WHERE c.source_id = %s"
                    params.append(source_id)
                sql += " ORDER BY c.source_id, c.ordinal LIMIT %s"
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
            sql = f"SELECT {CHUNK_COLUMNS} FROM chunks c"
            params: list[Any] = []
            if not force:
                sql += " WHERE c.embedding IS NULL"
            sql += " ORDER BY c.source_id, c.ordinal LIMIT %s"
            params.append(limit)
            return [self._chunk_from_row_with_embedding(row) for row in conn.execute(sql, params).fetchall()]

    def embedding_stats(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(embedding) AS embedded
                  FROM chunks
                """
            ).fetchone()
            model_rows = conn.execute(
                """
                SELECT embedding_model, COUNT(*) AS count
                  FROM chunks
                 WHERE embedding IS NOT NULL
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

    def update_chunk_embedding(
        self,
        chunk_id: int,
        *,
        embedding_model: str,
        embedding: list[float],
    ) -> None:
        now = self._now()
        embedding_literal = self._embedding_literal(embedding)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE chunks
                   SET embedding_model = %s,
                       embedding = %s::vector,
                       updated_at = %s
                 WHERE id = %s
                """,
                (embedding_model, embedding_literal, now, chunk_id),
            )

    def semantic_search_chunks(
        self,
        query_embedding: list[float],
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        if math.sqrt(sum(value * value for value in query_embedding)) == 0:
            return []

        embedding_literal = self._embedding_literal(query_embedding)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {CHUNK_COLUMNS},
                       1 - (c.embedding <=> %s::vector) AS score
                  FROM chunks c
                 WHERE c.embedding IS NOT NULL
                 ORDER BY c.embedding <=> %s::vector
                 LIMIT %s
                """,
                (embedding_literal, embedding_literal, limit),
            ).fetchall()

        results = []
        for row in rows:
            item = self._chunk_from_row(row)
            item["score"] = float(row["score"])
            results.append(item)
        return results

    def semantic_search_chunks_in_sources(
        self,
        query_embedding: list[float],
        source_ids: list[int],
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Return semantic hits only from a bounded, user-selected reference set."""
        clean_source_ids = list(dict.fromkeys(
            int(source_id)
            for source_id in source_ids
            if isinstance(source_id, int) or str(source_id).strip().isdigit()
        ))
        if not clean_source_ids or math.sqrt(sum(value * value for value in query_embedding)) == 0:
            return []

        limit = max(1, min(int(limit), 100))
        embedding_literal = self._embedding_literal(query_embedding)
        source_placeholders = ", ".join("%s" for _ in clean_source_ids)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {CHUNK_COLUMNS},
                       1 - (c.embedding <=> %s::vector) AS score
                  FROM chunks c
                 WHERE c.embedding IS NOT NULL
                   AND c.source_id IN ({source_placeholders})
                 ORDER BY c.embedding <=> %s::vector
                 LIMIT %s
                """,
                (embedding_literal, *clean_source_ids, embedding_literal, limit),
            ).fetchall()

        results = []
        for row in rows:
            item = self._chunk_from_row(row)
            item["score"] = float(row["score"])
            results.append(item)
        return results

    def get_setting(self, key: str) -> str | None:
        clean_key = str(key or "").strip()
        if not clean_key:
            return None

        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM brain_settings WHERE key = %s", (clean_key,)).fetchone()
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
                VALUES (%s, %s, %s)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (clean_key, clean_value, now),
            )

    def delete_source(self, source_id: int) -> bool:
        with self._lock, self._connect() as conn:
            chunk_ids = [
                int(row["id"])
                for row in conn.execute("SELECT id FROM chunks WHERE source_id = %s", (source_id,)).fetchall()
            ]
            cur = conn.execute("DELETE FROM sources WHERE id = %s", (source_id,))
            conn.execute(
                "DELETE FROM brain_index WHERE entity_type = 'source' AND entity_id = %s",
                (source_id,),
            )
            for chunk_id in chunk_ids:
                conn.execute(
                    "DELETE FROM brain_index WHERE entity_type = 'chunk' AND entity_id = %s",
                    (chunk_id,),
                )
            return cur.rowcount > 0

    def search(self, query: str, limit: int = 50, entity_type: str | None = None) -> list[dict[str, Any]]:
        strict_query = self._safe_fts_query(query, operator="&")
        loose_query = self._safe_fts_query(query, operator="|")
        if not strict_query:
            return []

        limit = max(1, min(int(limit), 200))

        with self._lock, self._connect() as conn:
            def run_query(fts_query: str) -> list[dict[str, Any]]:
                params: list[Any] = [fts_query, fts_query]
                sql = """
                    SELECT i.entity_type,
                           i.entity_id,
                           i.title,
                           i.body,
                           i.tags,
                           CASE
                               WHEN i.entity_type = 'source' THEN i.entity_id
                               ELSE c.source_id
                           END AS source_id,
                           ts_rank_cd(i.search_vector, to_tsquery('simple', %s)) AS rank
                      FROM brain_index i
                      LEFT JOIN chunks c
                        ON i.entity_type = 'chunk'
                       AND c.id = i.entity_id
                     WHERE i.search_vector @@ to_tsquery('simple', %s)
                """
                if entity_type:
                    sql += " AND i.entity_type = %s"
                    params.append(entity_type)
                sql += " ORDER BY rank DESC LIMIT %s"
                params.append(limit)

                return [
                    {
                        "entityType": row["entity_type"],
                        "entityId": int(row["entity_id"]),
                        "title": row["title"],
                        "body": row["body"],
                        "tags": row["tags"].split() if row["tags"] else [],
                        "rank": float(row["rank"]),
                        "sourceId": int(row["source_id"]) if row["source_id"] is not None else None,
                    }
                    for row in conn.execute(sql, params).fetchall()
                ]

            results = run_query(strict_query)
            if not results and loose_query and loose_query != strict_query:
                results = run_query(loose_query)
            return results

    def counts(self) -> dict[str, int]:
        with self._lock, self._connect() as conn:
            tables = ["memories", "sources", "chunks", "ideas", "theses", "edges"]
            result = {
                table: int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])
                for table in tables
            }
            result["indexed"] = int(conn.execute("SELECT COUNT(*) AS c FROM brain_index").fetchone()["c"])
            return result
