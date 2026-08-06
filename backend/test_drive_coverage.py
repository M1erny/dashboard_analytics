"""Checks for the Drive coverage report.

This report is the answer to "how much of my Drive is actually in the Brain",
so its job is to be honest about the difference between a number it counted and
a number it guessed. These tests pin both.
"""

import drive_coverage


def drive_file(file_id, name, mime_type, size=None, path=None):
    item = {"id": file_id, "name": name, "mimeType": mime_type, "relativePath": path or name}
    if size is not None:
        item["size"] = str(size)
    return item


def source(source_id, drive_file_id, words, *, chunks=5, embedded=5, **extraction):
    return {
        "id": source_id,
        "title": f"source-{source_id}",
        "kind": "file",
        "chunkCount": chunks,
        "embeddedChunks": embedded,
        "words": words,
        "metadata": {"driveFileId": drive_file_id, "sourceType": "google_drive", **extraction},
    }


PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GDOC = "application/vnd.google-apps.document"
FOLDER = "application/vnd.google-apps.folder"

DRIVE = [
    drive_file("f1", "meta-10k.pdf", PDF, size=8_000_000),          # indexed, truncated at 40/200 pages
    drive_file("f2", "thesis.docx", DOCX, size=90_000),             # indexed complete
    drive_file("f3", "notes.txt", "text/plain", size=12_000),       # indexed complete
    drive_file("f4", "model.xlsx", XLSX, size=600_000),             # supported now, never synced
    drive_file("f5", "scan.pdf", PDF, size=3_000_000),              # indexed, no text (no OCR)
    drive_file("f6", "old-deck.key", "application/x-iwork", size=4_000_000),  # no extractor
    drive_file("f7", "huge.pdf", PDF, size=200_000_000),            # over the byte limit
    drive_file("f8", "memo", GDOC),                                 # native Doc, no size reported
    drive_file("f9", "sub", FOLDER),                                # folders are not content
    drive_file(
        "f10",
        "chat.md",
        "text/markdown",
        size=5_000,
        path="Investment Brain/Conversations/chat.md",
    ),
]

SOURCES = [
    source(1, "f1", 20_000, pages=200, pagesRead=40, truncated=True),
    source(2, "f2", 4_000),
    source(3, "f3", 1_800),
    source(5, "f5", 0, chunks=0, embedded=0),
    source(8, "f8", 1_200),
    # A source with no driveFileId (e.g. a pasted note) must not break the join.
    {"id": 9, "title": "manual", "kind": "note", "chunkCount": 2, "embeddedChunks": 1, "words": 300, "metadata": {}},
]

report = drive_coverage.build_coverage_report(
    DRIVE, SOURCES, max_bytes=64 * 1024 * 1024, folder_id="folder-1"
)
by_id = {item["driveFileId"]: item for item in report["files"]}
counts = report["counts"]
coverage = report["coverage"]

# --- classification --------------------------------------------------------

assert by_id["f1"]["status"] == "indexed_truncated"
assert "page 40 of 200" in by_id["f1"]["reason"]
assert by_id["f2"]["status"] == "indexed_complete"
assert by_id["f3"]["status"] == "indexed_complete"
assert by_id["f4"]["status"] == "never_indexed_not_synced", "xlsx is supported now, so it is pending, not unsupported"
assert by_id["f5"]["status"] == "never_indexed_no_text"
assert by_id["f6"]["status"] == "never_indexed_unsupported"
assert by_id["f7"]["status"] == "never_indexed_too_large"
assert by_id["f8"]["status"] == "indexed_complete", "native Google Docs are exported and indexed"
assert by_id["f10"]["status"] == "excluded_transcript"
assert "f9" not in by_id, "folders must not appear as content"

assert counts["driveFiles"] == 9, counts
assert counts["countedFiles"] == 8, "the transcript is excluded from the denominator"
assert counts["indexed_complete"] == 3, counts
assert counts["indexed_truncated"] == 1

# --- exact percentages -----------------------------------------------------

# 3 of 8 countable files are complete: the OCR-less scan is indexed but empty.
assert coverage["filesPercent"] == 37.5, coverage
# 4 of 8 are at least partly present.
assert coverage["filesPartialPercent"] == 50.0, coverage
# 40 of 200 pages read is exact, not an estimate.
assert coverage["pdfPagesPercent"] == 20.0, coverage
assert report["volume"]["pdfPagesRead"] == 40 and report["volume"]["pdfPagesTotal"] == 200

# Embedded chunk coverage counts only chunks attached to Drive files.
assert counts["chunks"] == 20 and counts["embeddedChunks"] == 20
assert coverage["embeddedChunksPercent"] == 100.0

# --- estimated volume ------------------------------------------------------

# The truncated filing knows its own page ratio, so the missing tail is arithmetic.
assert by_id["f1"]["estimateBasis"] == "page_ratio"
assert by_id["f1"]["estimatedMissingWords"] == 80_000, by_id["f1"]

# A file never read can only be estimated from its byte count, and says so.
assert by_id["f4"]["estimateBasis"] == "byte_ratio"
assert by_id["f4"]["estimatedMissingWords"] > 0
assert by_id["f8"]["estimateBasis"] == "indexed", "an indexed Workspace file is measured, not assumed"

indexed_words = 20_000 + 4_000 + 1_800 + 0 + 1_200
assert report["volume"]["indexedWords"] == indexed_words, report["volume"]
assert report["volume"]["indexedTokens"] == int(indexed_words * drive_coverage.TOKENS_PER_WORD)
assert 0 < coverage["tokensPercentEstimate"] < 100

# --- honesty ---------------------------------------------------------------

notes = " ".join(report["notes"])
assert "estimates" in notes, "the report must label its estimated numbers"
assert "cut short" in notes and "160,000 PDF pages" not in notes
assert "160 PDF pages never read" in notes, notes
assert "no extractor" in notes
assert "never been synced" in notes

# An empty Drive must not divide by zero.
empty = drive_coverage.build_coverage_report([], [], max_bytes=1024, folder_id=None)
assert empty["coverage"]["filesPercent"] is None
assert empty["counts"]["driveFiles"] == 0

# A truncated listing must say the denominator is incomplete.
partial = drive_coverage.build_coverage_report(
    DRIVE, SOURCES, max_bytes=64 * 1024 * 1024, folder_id="folder-1", listing_complete=False
)
assert "file ceiling" in " ".join(partial["notes"])

# Re-indexing the same Drive file under a second source row counts once, at its fullest.
duplicated = drive_coverage.build_coverage_report(
    [drive_file("f2", "thesis.docx", DOCX, size=90_000)],
    [source(2, "f2", 4_000), source(20, "f2", 9_000)],
    max_bytes=64 * 1024 * 1024,
)
assert duplicated["volume"]["indexedWords"] == 9_000
assert duplicated["counts"]["indexed_complete"] == 1

# --- source_content_stats against a real store -----------------------------
#
# The report is only as good as the aggregate feeding it, and that aggregate
# reads wordEnd out of chunk metadata in SQL. Exercise it end to end rather than
# trusting hand-built fixtures.

import tempfile
from pathlib import Path

from brain_ingestion import chunk_text
from brain_store import BrainStore

with tempfile.TemporaryDirectory() as directory:
    store = BrainStore(Path(directory) / "coverage.db")

    body = " ".join(f"word{n}" for n in range(5_000))
    saved_source, _changed = store.upsert_file_source(
        title="Long filing",
        body=body[:4000],
        tags=["google-drive", "pdf"],
        metadata={
            "fileIdentity": "drive:drive-long",
            "fileHash": "hash-long",
            "driveFileId": "drive-long",
            "sourceType": "google_drive",
            "pages": 120,
            "pagesRead": 30,
            "truncated": True,
        },
    )
    chunks = chunk_text(body, source_title="Long filing", tags=["google-drive"])
    assert len(chunks) > 1, "the fixture must span several overlapping chunks"
    store.add_chunks(saved_source["id"], chunks)

    # A second source with no Drive id must survive the join untouched.
    note, _ = store.upsert_file_source(
        title="Note",
        body="short note",
        tags=[],
        metadata={"fileIdentity": "local:note", "fileHash": "hash-note"},
    )
    store.add_chunks(note["id"], chunk_text("a short standalone note", source_title="Note"))

    stats = store.source_content_stats()
    by_id = {item["id"]: item for item in stats}
    long_source = by_id[saved_source["id"]]

    # Chunks overlap, so a naive sum would exceed the document. wordEnd must not.
    assert long_source["words"] == 5_000, f"expected 5000 distinct words, got {long_source['words']}"
    assert long_source["chunkCount"] == len(chunks)
    assert long_source["embeddedChunks"] == 0, "nothing was embedded in this fixture"
    assert long_source["metadata"]["driveFileId"] == "drive-long"
    naive_sum = sum(chunk["metadata"]["wordEnd"] - chunk["metadata"]["wordStart"] for chunk in chunks)
    assert naive_sum > 5_000, "the fixture must actually overlap, or this proves nothing"

    # And the report built from real store output agrees.
    live = drive_coverage.build_coverage_report(
        [drive_file("drive-long", "filing.pdf", PDF, size=6_000_000)],
        stats,
        max_bytes=64 * 1024 * 1024,
    )
    entry = live["files"][0]
    assert entry["status"] == "indexed_truncated"
    assert entry["wordsInBrain"] == 5_000
    assert live["coverage"]["pdfPagesPercent"] == 25.0
    # 30 of 120 pages read means the Brain holds a quarter, so three quarters are missing.
    assert entry["estimatedMissingWords"] == 15_000, entry

print("Drive coverage report checks passed.")
