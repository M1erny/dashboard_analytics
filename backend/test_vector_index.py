"""The Brain's vector index: it must exist, and its absence must be visible.

pgvector's HNSW index on the `vector` type stops at 2000 dimensions; the
embeddings are 3072. The original CREATE INDEX therefore failed on Supabase, and
the failure was swallowed, so every semantic search scanned every row and began
timing out (504) once the library passed ten thousand passages. These checks pin
the halfvec route pgvector documents for wider vectors, the rule that both query
sides go through the same cast the index is built on, and the reporting of the
outcome instead of silence.
"""

import sys

import brain_store_postgres as pg

FAILED = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


print("\n=== Index definition ===")
ddl = " ".join(pg.VECTOR_INDEX_SQL.split())
check("uses HNSW", "USING hnsw" in ddl, ddl)
check("indexes the halfvec cast, not the raw vector column",
      "((embedding::halfvec(3072)) halfvec_cosine_ops)" in ddl, ddl)
check("is partial on rows that actually have an embedding", "WHERE embedding IS NOT NULL" in ddl, ddl)
check("is idempotent across restarts", "IF NOT EXISTS" in ddl)
check("the build budget is well above the 12 s statement timeout",
      pg.VECTOR_INDEX_BUILD_TIMEOUT_MS >= 60_000, str(pg.VECTOR_INDEX_BUILD_TIMEOUT_MS))

print("\n=== Search SQL matches the index ===")
for name, sql in (("library-wide", pg.SEMANTIC_SEARCH_SQL),
                  ("within sources", pg.SEMANTIC_SEARCH_IN_SOURCES_SQL.format(source_placeholders="%s"))):
    flat = " ".join(sql.split())
    check(f"{name}: ORDER BY goes through the indexed expression",
          "ORDER BY c.embedding::halfvec(3072) <=> %s::halfvec(3072)" in flat, flat[-200:])
    check(f"{name}: the score uses the same cast", "1 - (c.embedding::halfvec(3072) <=> %s::halfvec(3072)) AS score" in flat)
    check(f"{name}: no bare ::vector left to defeat the index", "::vector" not in flat)
    check(f"{name}: keeps the partial-index predicate", "WHERE c.embedding IS NOT NULL" in flat)
check("the sources query still takes its placeholder list",
      "IN (%s, %s, %s)" in pg.SEMANTIC_SEARCH_IN_SOURCES_SQL.format(source_placeholders="%s, %s, %s"))

print("\n=== Outcome is recorded, never swallowed ===")


class FakeCursor:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class FakeConn:
    """Scripts the catalogue's answers in order; records every statement."""

    def __init__(self, catalogue_answers, raise_on=None):
        self.answers = list(catalogue_answers)
        self.raise_on = raise_on
        self.statements = []
        self.closed = False
        self.kwargs = None

    def execute(self, sql, params=None):
        flat = " ".join(str(sql).split())
        self.statements.append(flat)
        if self.raise_on and self.raise_on in flat:
            raise RuntimeError("ERROR:  column cannot have more than 2000 dimensions for hnsw index")
        if "pg_index" in flat:
            return FakeCursor(self.answers.pop(0) if self.answers else None)
        return FakeCursor(None)

    def close(self): self.closed = True


def run(conn):
    store = pg.PostgresBrainStore.__new__(pg.PostgresBrainStore)
    store.database_url = "postgresql://x:y@h/db"
    saved = pg.psycopg.connect

    def fake_connect(*args, **kwargs):
        conn.kwargs = kwargs
        return conn

    pg.psycopg.connect = fake_connect
    try:
        store._ensure_vector_index()
    finally:
        pg.psycopg.connect = saved
    return store.vector_index_state, conn


state, conn = run(FakeConn([{"indisvalid": True}]))
check("an index already present and valid is left alone and reported ok",
      state["status"] == "ok" and not any("CREATE INDEX" in s for s in conn.statements), str(state))
check("the build connection is autocommit, as CONCURRENTLY requires", conn.kwargs.get("autocommit") is True)
check("with its own statement timeout and no lock timeout",
      f"statement_timeout={pg.VECTOR_INDEX_BUILD_TIMEOUT_MS}" in conn.kwargs.get("options", "") and "lock_timeout=0" in conn.kwargs.get("options", ""), conn.kwargs.get("options"))
check("the connection is closed afterwards", conn.closed)

state, conn = run(FakeConn([None, {"indisvalid": True}]))
check("a missing index is built concurrently",
      any(s.startswith("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_embedding_hnsw_halfvec") for s in conn.statements), str(conn.statements))
check("and confirmed valid afterwards", state["status"] == "ok", str(state))

state, conn = run(FakeConn([{"indisvalid": False}, {"indisvalid": True}]))
check("an invalid leftover from an interrupted build is dropped first",
      any(s.startswith("DROP INDEX CONCURRENTLY IF EXISTS idx_chunks_embedding_hnsw_halfvec") for s in conn.statements), str(conn.statements))
check("then rebuilt and reported ok", any("CREATE INDEX CONCURRENTLY" in s for s in conn.statements) and state["status"] == "ok")

state, conn = run(FakeConn([None, None]))
check("a build that leaves no valid index is reported missing, not ok",
      state["status"] == "missing" and state["error"], str(state))

state, conn = run(FakeConn([None], raise_on="CREATE INDEX"))
check("a failing build is caught, not raised", state["status"] == "failed")
check("and the database's own reason is kept", "2000 dimensions" in (state["error"] or ""), str(state))
check("the connection is closed even when the build fails", conn.closed)
check("the state always names the index", state["index"] == pg.VECTOR_INDEX_NAME)

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s): {', '.join(FAILED)}")
    sys.exit(1)
print("All vector index checks passed.")
