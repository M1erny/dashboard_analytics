"""Focused edge-case checks for hybrid Brain retrieval."""

import math
import tempfile
from pathlib import Path

import server
from brain_store import BrainStore
from pydantic import ValidationError


threshold = server.SEMANTIC_MIN_SCORE
accepted = server._filter_semantic_results([
    {"id": 1, "score": threshold + 0.01},
    {"id": 2, "score": threshold - 0.01},
    {"id": 3, "score": float("nan")},
    {"id": 4, "score": "not-a-number"},
])
assert [item["id"] for item in accepted] == [1]

merged = server._merge_retrieval_results(
    [],
    [{"entityType": "chunk", "entityId": 7, "sourceId": 2, "ordinal": 9, "title": "Exact hit", "body": "underwriting"}],
    limit=6,
)
assert len(merged) == 1
assert merged[0]["retrievalSignals"] == {"keywordRank": 1}
assert merged[0]["ordinal"] == 9

assert server.BrainCompanyAnalysisRequest(question="Compare the value chain").ticker is None
try:
    server.BrainCompanyAnalysisRequest(question="x" * 4001)
    raise AssertionError("Questions above the context budget must be rejected")
except ValidationError:
    pass

assert server._clean_brain_search_query(" X ") == "X"
try:
    server._clean_brain_search_query("   ")
    raise AssertionError("Blank search queries must be rejected before embedding")
except server.HTTPException as error:
    assert error.status_code == 422


class ExpansionStore:
    def get_source(self, source_id):
        return {"id": source_id, "title": f"Source {source_id}", "kind": "file", "tags": [], "metadata": {}}

    def list_chunks(self, *, source_id, limit):
        chunks = {
            1: [
                {"id": 11, "ordinal": 1, "title": "One", "body": "first"},
                {"id": 12, "ordinal": 9, "title": "Nine", "body": "later"},
            ],
            2: [{"id": 21, "ordinal": 2, "title": "Two", "body": "second source"}],
        }
        return chunks[source_id][:limit]


expanded = server._expand_semantic_hits_into_sources(
    ExpansionStore(),
    [
        {"sourceId": 1, "ordinal": 1},
        {"sourceId": 2, "ordinal": 2},
        {"sourceId": 1, "ordinal": 9},
    ],
    max_sources=2,
    window=0,
)
assert expanded[0]["hitOrdinals"] == [1, 9]
assert [chunk["ordinal"] for chunk in expanded[0]["chunks"]] == [1, 9]

with tempfile.TemporaryDirectory() as directory:
    store = BrainStore(Path(directory) / "brain.db")
    source = store.add_source("file", "Test source", "metadata only")
    store.add_chunks(source["id"], [{
        "ordinal": 9,
        "title": "Underwriting passage",
        "body": "Credit underwriting uses repayment data.",
        "pageStart": 42,
        "pageEnd": 43,
        "contentHash": "underwriting-passage",
    }])
    keyword_results = store.search("underwriting")
    chunk_result = next(item for item in keyword_results if item["entityType"] == "chunk")
    assert chunk_result["ordinal"] == 9
    assert chunk_result["pageStart"] == 42
    assert chunk_result["pageEnd"] == 43

assert math.isfinite(threshold)
print("Brain retrieval edge-case checks passed.")
