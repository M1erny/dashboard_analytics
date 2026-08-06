"""Measure how much of a Google Drive folder actually reached the Brain.

"Indexed" and "fully indexed" are different claims, and the difference is where
research quietly goes wrong: a 200 page filing that was cut at page 40 still
answers questions, it just answers them from the first fifth of the document.

This module joins the live Drive listing against what the store holds and reports
the gap. Numbers that can be counted exactly are reported separately from numbers
that can only be estimated, because the honest answer to "what percentage" depends
on which one you mean.
"""

from typing import Any

from brain_indexer import SUPPORTED_EXTENSIONS
from drive_indexer import (
    FOLDER_MIME_TYPE,
    extension_for_file,
    is_brain_conversation_transcript,
)


# Words to tokens. Same 1.3 ratio brain_ingestion.estimate_tokens uses, so a
# coverage percentage is comparable with the chunk token counts in the store.
TOKENS_PER_WORD = 1.3

# Bytes of file to words of extractable text. Only used for files the Brain has
# never read, where nothing better exists. Wildly different per format, which is
# exactly why these numbers are labelled as estimates everywhere they surface.
BYTES_PER_WORD = {
    ".txt": 6.0,
    ".md": 6.0,
    ".markdown": 6.0,
    ".rst": 6.0,
    ".csv": 7.0,
    ".tsv": 7.0,
    ".json": 12.0,
    ".jsonl": 12.0,
    ".html": 20.0,
    ".htm": 20.0,
    ".docx": 40.0,
    ".pdf": 180.0,
    ".xlsx": 60.0,
    ".pptx": 400.0,
}
DEFAULT_BYTES_PER_WORD = 60.0

# A Workspace file reports no size. These are rough per-document word counts used
# only to keep native Docs from vanishing out of the denominator entirely.
WORKSPACE_ASSUMED_WORDS = {
    "application/vnd.google-apps.document": 1500,
    "application/vnd.google-apps.presentation": 400,
    "application/vnd.google-apps.spreadsheet": 800,
}

STATUS_ORDER = [
    "indexed_complete",
    "indexed_truncated",
    "never_indexed_unsupported",
    "never_indexed_too_large",
    "never_indexed_no_text",
    "never_indexed_not_synced",
    "excluded_transcript",
]


def _estimated_words_from_drive(file: dict[str, Any]) -> tuple[int, str]:
    """Guess a file's word count from Drive metadata alone. Returns (words, basis)."""
    mime_type = str(file.get("mimeType") or "")
    if mime_type in WORKSPACE_ASSUMED_WORDS:
        return WORKSPACE_ASSUMED_WORDS[mime_type], "workspace_assumption"

    try:
        size = int(file.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        return 0, "unknown_size"

    extension = extension_for_file(file) or ""
    ratio = BYTES_PER_WORD.get(extension.lower(), DEFAULT_BYTES_PER_WORD)
    return max(1, int(size / ratio)), "byte_ratio"


def _indexed_by_drive_id(source_stats: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for source in source_stats:
        metadata = source.get("metadata") or {}
        drive_file_id = metadata.get("driveFileId")
        if not drive_file_id:
            continue
        key = str(drive_file_id)
        # A file re-indexed under a new source row should count once, at its fullest.
        existing = indexed.get(key)
        if existing is None or source.get("words", 0) > existing.get("words", 0):
            indexed[key] = source
    return indexed


def _classify(
    file: dict[str, Any],
    source: dict[str, Any] | None,
    *,
    max_bytes: int,
) -> tuple[str, str]:
    """Return (status, human reason) for one Drive file."""
    name = str(file.get("name") or "")
    if is_brain_conversation_transcript(file):
        return "excluded_transcript", "Brain transcript, deliberately excluded from retrieval"

    extension = extension_for_file(file)
    if not extension or extension not in SUPPORTED_EXTENSIONS:
        suffix = extension or ("." + name.rsplit(".", 1)[-1].lower() if "." in name else "no extension")
        return "never_indexed_unsupported", f"No extractor for {suffix}"

    if source is None:
        try:
            size = int(file.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size and max_bytes and size > max_bytes:
            return "never_indexed_too_large", f"{size:,} bytes is over the {max_bytes:,} byte sync limit"
        return "never_indexed_not_synced", "Supported, but no indexed source exists yet. Run Sync Drive."

    metadata = source.get("metadata") or {}
    extraction = metadata if isinstance(metadata, dict) else {}
    if extraction.get("truncated"):
        pages = extraction.get("pages")
        pages_read = extraction.get("pagesRead")
        if isinstance(pages, int) and isinstance(pages_read, int) and pages > 0:
            return (
                "indexed_truncated",
                f"Cut at page {pages_read} of {pages}",
            )
        return "indexed_truncated", f"Cut at {extraction.get('maxExtractedChars') or 'the character'} limit"

    if not source.get("chunkCount"):
        return "never_indexed_no_text", "Indexed with no extractable text (likely a scan without OCR)"

    return "indexed_complete", "Fully indexed"


def _page_ratio(extraction: dict[str, Any]) -> float | None:
    pages = extraction.get("pages")
    pages_read = extraction.get("pagesRead")
    if isinstance(pages, int) and isinstance(pages_read, int) and pages > 0:
        return max(0.0, min(1.0, pages_read / pages))
    return None


def _percent(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return round(100.0 * part / whole, 1)


def build_coverage_report(
    drive_files: list[dict[str, Any]],
    source_stats: list[dict[str, Any]],
    *,
    max_bytes: int,
    folder_id: str | None = None,
    listing_complete: bool = True,
) -> dict[str, Any]:
    """Join a Drive listing against indexed sources and report the gap.

    drive_files come from GoogleDriveClient.iter_files. source_stats come from
    BrainStore.source_content_stats.
    """
    indexed = _indexed_by_drive_id(source_stats)

    files: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {status: 0 for status in STATUS_ORDER}

    indexed_words = 0
    estimated_missing_words = 0
    pages_total = 0
    pages_read = 0

    for file in drive_files:
        if file.get("mimeType") == FOLDER_MIME_TYPE:
            continue

        drive_file_id = str(file.get("id") or "")
        source = indexed.get(drive_file_id)
        status, reason = _classify(file, source, max_bytes=max_bytes)
        status_counts[status] = status_counts.get(status, 0) + 1

        words_in_brain = int((source or {}).get("words") or 0)
        extraction = (source or {}).get("metadata") or {}
        ratio = _page_ratio(extraction) if source else None

        if isinstance(extraction.get("pages"), int) and isinstance(extraction.get("pagesRead"), int):
            pages_total += int(extraction["pages"])
            pages_read += int(extraction["pagesRead"])

        missing_words = 0
        basis = "indexed"
        if status == "indexed_complete":
            indexed_words += words_in_brain
        elif status == "indexed_truncated":
            indexed_words += words_in_brain
            if ratio and ratio > 0:
                # Page ratio is measured, so the missing tail is arithmetic, not a guess.
                missing_words = max(0, int(words_in_brain / ratio) - words_in_brain)
                basis = "page_ratio"
            else:
                estimate, basis = _estimated_words_from_drive(file)
                missing_words = max(0, estimate - words_in_brain)
            estimated_missing_words += missing_words
        elif status == "excluded_transcript":
            basis = "excluded"
        else:
            missing_words, basis = _estimated_words_from_drive(file)
            estimated_missing_words += missing_words

        files.append(
            {
                "driveFileId": drive_file_id,
                "name": file.get("name"),
                "relativePath": file.get("relativePath"),
                "mimeType": file.get("mimeType"),
                "extension": extension_for_file(file),
                "sizeBytes": int(file.get("size") or 0) or None,
                "webViewLink": file.get("webViewLink"),
                "status": status,
                "reason": reason,
                "sourceId": (source or {}).get("id"),
                "chunkCount": (source or {}).get("chunkCount"),
                "embeddedChunks": (source or {}).get("embeddedChunks"),
                "wordsInBrain": words_in_brain or None,
                "pages": extraction.get("pages"),
                "pagesRead": extraction.get("pagesRead"),
                "estimatedMissingWords": missing_words or None,
                "estimateBasis": basis,
            }
        )

    total_files = len(files)
    countable_files = total_files - status_counts.get("excluded_transcript", 0)
    fully_indexed_files = status_counts.get("indexed_complete", 0)
    partly_indexed_files = status_counts.get("indexed_truncated", 0)

    total_words_estimate = indexed_words + estimated_missing_words
    indexed_tokens = int(indexed_words * TOKENS_PER_WORD)
    missing_tokens = int(estimated_missing_words * TOKENS_PER_WORD)

    embedded_chunks = sum(int(item.get("embeddedChunks") or 0) for item in files)
    total_chunks = sum(int(item.get("chunkCount") or 0) for item in files)

    return {
        "folderId": folder_id,
        "listingComplete": listing_complete,
        "maxBytes": max_bytes,
        "coverage": {
            # Exact: every file in the folder is either indexed or it is not.
            "filesPercent": _percent(fully_indexed_files, countable_files),
            "filesPartialPercent": _percent(fully_indexed_files + partly_indexed_files, countable_files),
            # Exact for PDFs the Brain has read: pypdf reports the real page count.
            "pdfPagesPercent": _percent(pages_read, pages_total),
            # Estimated: the size of what was never read can only be guessed.
            "tokensPercentEstimate": _percent(indexed_words, total_words_estimate),
            # Exact: a chunk without an embedding is invisible to semantic search.
            "embeddedChunksPercent": _percent(embedded_chunks, total_chunks),
        },
        "counts": {
            "driveFiles": total_files,
            "countedFiles": countable_files,
            **{status: status_counts.get(status, 0) for status in STATUS_ORDER},
            "chunks": total_chunks,
            "embeddedChunks": embedded_chunks,
        },
        "volume": {
            "indexedWords": indexed_words,
            "indexedTokens": indexed_tokens,
            "estimatedMissingWords": estimated_missing_words,
            "estimatedMissingTokens": missing_tokens,
            "estimatedTotalTokens": indexed_tokens + missing_tokens,
            "pdfPagesRead": pages_read,
            "pdfPagesTotal": pages_total,
        },
        "notes": _coverage_notes(status_counts, pages_read, pages_total, listing_complete),
        "files": sorted(
            files,
            key=lambda item: (
                STATUS_ORDER.index(item["status"]) if item["status"] in STATUS_ORDER else 99,
                -(item.get("estimatedMissingWords") or 0),
            ),
        ),
    }


def _coverage_notes(
    status_counts: dict[str, int],
    pages_read: int,
    pages_total: int,
    listing_complete: bool,
) -> list[str]:
    notes: list[str] = []
    if not listing_complete:
        notes.append(
            "The Drive listing hit its file ceiling, so this report covers only the files it saw."
        )
    if status_counts.get("indexed_truncated"):
        missing_pages = max(0, pages_total - pages_read)
        detail = f" ({missing_pages:,} PDF pages never read)" if missing_pages else ""
        notes.append(
            f"{status_counts['indexed_truncated']} file(s) are indexed but cut short{detail}. "
            "Re-sync with force after raising the extraction limits to pull the rest."
        )
    if status_counts.get("never_indexed_unsupported"):
        notes.append(
            f"{status_counts['never_indexed_unsupported']} file(s) have no extractor. "
            "The Brain has never seen a word of them."
        )
    if status_counts.get("never_indexed_too_large"):
        notes.append(
            f"{status_counts['never_indexed_too_large']} file(s) are over the per-file size limit."
        )
    if status_counts.get("never_indexed_no_text"):
        notes.append(
            f"{status_counts['never_indexed_no_text']} file(s) yielded no text, which usually means "
            "a scan with no OCR layer."
        )
    if status_counts.get("never_indexed_not_synced"):
        notes.append(
            f"{status_counts['never_indexed_not_synced']} supported file(s) have never been synced. "
            "Sync Drive processes a limited number of changed files per run, so repeat it until this is zero."
        )
    notes.append(
        "Token percentages are estimates: the size of a document the Brain never read "
        "can only be inferred from its byte count. File and PDF page percentages are exact."
    )
    return notes
