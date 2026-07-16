"""Focused edge-case checks for hybrid Brain retrieval."""

import math
import tempfile
from pathlib import Path

import server
from brain_store import BrainStore
from drive_indexer import match_legacy_sources_to_drive
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

drive_reference = server._public_source_reference({
    "id": 10,
    "kind": "file",
    "title": "Annual report",
    "metadata": {"driveFileId": "drive-123"},
})
assert drive_reference["webUrl"] == "https://drive.google.com/file/d/drive-123/view"
assert drive_reference["linkType"] == "drive_file"

legacy_reference = server._public_source_reference({
    "id": 11,
    "kind": "file",
    "title": "Legacy framework",
    "metadata": {
        "sourceType": "local_file",
        "fileName": "Legacy framework.pdf",
        "relativePath": "Books/Legacy framework.pdf",
    },
})
assert legacy_reference["webUrl"] is None
assert legacy_reference["linkType"] == "drive_search"
assert legacy_reference["driveSearchUrl"].startswith("https://drive.google.com/drive/u/0/search?q=")

conversation_source = {
    "id": 12,
    "kind": "file",
    "title": "Saved Brain thread",
    "metadata": {"relativePath": "Investment Brain/Conversations/thread.md"},
}
assert server._is_brain_conversation_source(conversation_source) is True
assert server._is_brain_conversation_source({"metadata": {"relativePath": "Research/META.md"}}) is False
assert server._exclude_brain_conversation_results([
    {"entityId": 1, "source": server._public_source_reference(conversation_source)},
    {"entityId": 2, "source": legacy_reference},
]) == [{"entityId": 2, "source": legacy_reference}]

legacy_matches = match_legacy_sources_to_drive(
    [{
        "id": 21,
        "metadata": {
            "sourceType": "local_file",
            "fileIdentity": "local-file:legacy.pdf",
            "relativePath": "Books/Old descriptive filename.pdf",
            "extension": ".pdf",
            "bytes": 1635920,
        },
    }],
    [{
        "id": "drive-file-21",
        "name": "Renamed edition.pdf",
        "relativePath": "Books/Renamed edition.pdf",
        "mimeType": "application/pdf",
        "size": "1635920",
        "webViewLink": "https://drive.google.com/file/d/drive-file-21/view",
    }],
)
assert legacy_matches[0]["sourceId"] == 21
assert legacy_matches[0]["file"]["id"] == "drive-file-21"
assert legacy_matches[0]["matchType"] == "folder_size_extension"


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
    updated_source = store.update_source_metadata(source["id"], {"driveFileId": "linked-file"})
    assert updated_source["metadata"]["driveFileId"] == "linked-file"
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
