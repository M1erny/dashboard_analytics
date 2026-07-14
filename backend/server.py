import sys
import os
import html
import re
import asyncio
import json
import math
from collections import OrderedDict

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import pandas as pd
import numpy as np
import time
import yfinance as yf
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

# Import risk.py (Now local)
try:
    import risk
except ImportError as e:
    print(f"Error importing risk.py: {e}")
    risk = None

try:
    from brain_agent import (
        DEFAULT_AGENT_MAX_BYTES,
        find_official_source_candidates,
        import_url_into_brain,
    )
    from brain_store import create_brain_store
    from brain_ingestion import chunk_text, normalize_text, stable_hash
    from brain_indexer import index_local_library, indexer_status
    from drive_indexer import (
        GoogleDriveClient,
        configured_redirect_uri,
        extension_for_file,
        google_drive_auth_url,
        index_drive_folder,
        parse_drive_folder_id,
    )
    from gemini_client import GeminiClient, load_backend_env
except ImportError as e:
    print(f"Error importing Investment Brain modules: {e}")
    DEFAULT_AGENT_MAX_BYTES = 15 * 1024 * 1024
    find_official_source_candidates = None
    import_url_into_brain = None
    create_brain_store = None
    index_local_library = None
    indexer_status = None
    GoogleDriveClient = None
    configured_redirect_uri = None
    extension_for_file = None
    google_drive_auth_url = None
    index_drive_folder = None
    parse_drive_folder_id = None
    GeminiClient = None
    load_backend_env = None

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Response cache (mapped by costTier, 5 minute TTL)
_cache = {}
_data_cache = {}  # Shared raw market data cache keyed by portfolio
_brain_portfolio_context_lock = asyncio.Lock()
if load_backend_env:
    load_backend_env()
brain_store_error = None
try:
    brain_store = create_brain_store() if create_brain_store else None
except Exception as e:
    print(f"Error initializing Investment Brain store: {e}")
    brain_store_error = str(e)
    brain_store = None
gemini_client = GeminiClient() if GeminiClient else None


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


BRAIN_SEARCH_TIMEOUT_SECONDS = _env_float("BRAIN_SEARCH_TIMEOUT_SECONDS", 18.0)
BRAIN_ANALYSIS_TIMEOUT_SECONDS = _env_float("BRAIN_ANALYSIS_TIMEOUT_SECONDS", 8.0)
BRAIN_INDEX_TIMEOUT_SECONDS = _env_float("BRAIN_INDEX_TIMEOUT_SECONDS", 240.0)
SEMANTIC_MIN_SCORE = max(0.0, min(_env_float("BRAIN_SEMANTIC_MIN_SCORE", 0.66), 1.0))
REFERENCE_SOURCE_IDS_SETTING = "brain.reference_source_ids.v1"
MAX_REFERENCE_SOURCES = 6
FULL_CONTEXT_SOURCE_IDS_SETTING = "brain.full_context_source_ids.v1"
MAX_FULL_CONTEXT_SOURCES = 4
FULL_CONTEXT_MAX_CHARS_PER_SOURCE = max(20_000, min(_env_int("BRAIN_FULL_CONTEXT_MAX_CHARS_PER_SOURCE", 250_000), 1_000_000))
FULL_CONTEXT_TOTAL_MAX_CHARS = max(100_000, min(_env_int("BRAIN_FULL_CONTEXT_TOTAL_MAX_CHARS", 800_000), 1_500_000))
FULL_CONTEXT_GENERATION_TIMEOUT_SECONDS = max(15.0, min(_env_float("BRAIN_FULL_CONTEXT_GENERATION_TIMEOUT_SECONDS", 45.0), 120.0))
FULL_DOCUMENT_CACHE_MAX_ENTRIES = max(2, min(_env_int("BRAIN_FULL_DOCUMENT_CACHE_MAX_ENTRIES", 12), 32))
BRAIN_STATUS_CACHE_SECONDS = max(2.0, min(_env_float("BRAIN_STATUS_CACHE_SECONDS", 15.0), 60.0))
SYSTEM_PROMPT_SETTING = "brain.system_prompt.v1"
MAX_SYSTEM_PROMPT_CHARS = 6000
DEFAULT_BRAIN_SYSTEM_PROMPT = """You are Investment Brain, a rigorous private investing research assistant.

Think like a patient, independent equity analyst. Separate evidence from inference, make assumptions explicit, identify contradictions, and avoid false precision. Treat primary sources and dated company evidence as stronger than commentary. Do not invent facts, citations, or certainty. When information is missing, say what would be needed to decide.

Use the investor's standing reference sources as durable frameworks and lenses, not as proof of company-specific claims. Be concise, clear, and willing to challenge the investor's thesis."""

embedding_backfill_job: dict[str, Any] = {
    "running": False,
    "startedAt": None,
    "finishedAt": None,
    "model": None,
    "requested": 0,
    "embedded": 0,
    "errors": [],
    "message": "Idle",
    "embeddings": None,
}

drive_index_job: dict[str, Any] = {
    "running": False,
    "startedAt": None,
    "finishedAt": None,
    "folderId": None,
    "folderUrl": None,
    "summary": None,
    "progress": None,
    "counts": None,
    "results": [],
    "message": "Idle",
}

# These caches are deliberately short-lived/versioned: they reduce repeated Supabase
# work during a research thread without hiding newly indexed files for long.
brain_status_cache: dict[str, Any] = {"payload": None, "expiresAt": 0.0}
full_document_text_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()


async def _run_brain_step(label: str, func, *args, timeout: float | None = None, **kwargs):
    try:
        return await asyncio.wait_for(
            run_in_threadpool(func, *args, **kwargs),
            timeout=timeout or BRAIN_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"{label} timed out. Try again in a moment, or check Render/Supabase if this repeats.",
        )


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _public_embedding_job() -> dict[str, Any]:
    return {
        "running": embedding_backfill_job.get("running", False),
        "startedAt": embedding_backfill_job.get("startedAt"),
        "finishedAt": embedding_backfill_job.get("finishedAt"),
        "model": embedding_backfill_job.get("model"),
        "requested": embedding_backfill_job.get("requested", 0),
        "embedded": embedding_backfill_job.get("embedded", 0),
        "errors": embedding_backfill_job.get("errors", [])[-10:],
        "message": embedding_backfill_job.get("message", "Idle"),
        "embeddings": embedding_backfill_job.get("embeddings"),
    }


def _public_drive_job() -> dict[str, Any]:
    return {
        "running": drive_index_job.get("running", False),
        "startedAt": drive_index_job.get("startedAt"),
        "finishedAt": drive_index_job.get("finishedAt"),
        "folderId": drive_index_job.get("folderId"),
        "folderUrl": drive_index_job.get("folderUrl"),
        "summary": drive_index_job.get("summary"),
        "progress": drive_index_job.get("progress"),
        "counts": drive_index_job.get("counts"),
        "results": drive_index_job.get("results", [])[-500:],
        "message": drive_index_job.get("message", "Idle"),
    }


def _clean_public_error(error: Exception | str) -> str:
    clean = _safe_backend_error(str(error))
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:500]


def _public_exception_reason(error: Exception | str) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, dict):
            detail = " ".join(str(value) for value in detail.values() if value)
        return _clean_public_error(str(detail))
    return _clean_public_error(error)


def _semantic_error_detail(error: Exception | str) -> dict[str, str]:
    reason = _public_exception_reason(error)
    lower_reason = reason.lower()
    if "http 403" in lower_reason or "forbidden" in lower_reason:
        return {
            "message": "Google AI rejected the embedding request.",
            "reason": "Embedding API returned 403 Forbidden.",
            "action": "Check the Render GOOGLE_AI_API_KEY value, API quota/billing, and access to gemini-embedding-001.",
        }
    return {
        "message": "Semantic search could not create a query embedding.",
        "reason": reason or "Unknown provider error.",
        "action": "Check the Gemini embedding provider and try Embed Missing again after the provider is healthy.",
    }


def _generation_error_detail(error: Exception | str) -> dict[str, str]:
    reason = _public_exception_reason(error)
    lower_reason = reason.lower()
    if "http 403" in lower_reason or "forbidden" in lower_reason:
        return {
            "message": "Google AI rejected the Gemini analysis request.",
            "reason": "Generation API returned 403 Forbidden.",
            "action": "Replace or fix the Render GOOGLE_AI_API_KEY value, then redeploy/restart the backend.",
        }
    return {
        "message": "Gemini analysis failed.",
        "reason": reason or "Unknown provider error.",
        "action": "Check the Google AI key, model access, quota, and Render logs.",
    }


def _public_source_reference(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not source:
        return None

    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    raw_drive_file_id = metadata.get("driveFileId")
    drive_file_id = str(raw_drive_file_id).strip() if raw_drive_file_id else None
    web_url = next(
        (
            value.strip()
            for value in (
                metadata.get("webViewLink"),
                metadata.get("driveWebViewLink"),
                metadata.get("sourceUrl"),
                metadata.get("finalUrl"),
                metadata.get("url"),
            )
            if isinstance(value, str) and value.strip()
        ),
        None,
    )
    if not web_url and drive_file_id:
        web_url = f"https://drive.google.com/file/d/{drive_file_id}/view"
    relative_path = metadata.get("relativePath")
    source_type = metadata.get("sourceType")
    drive_search_url = None
    if not web_url and (source_type == "local_file" or str(metadata.get("fileIdentity") or "").startswith("local-file:")):
        search_term = metadata.get("fileName") or source.get("title") or relative_path
        if isinstance(search_term, str) and search_term.strip():
            drive_search_url = f"https://drive.google.com/drive/u/0/search?q={quote_plus(search_term.strip())}"

    link_type = None
    if web_url:
        link_type = "drive_file" if drive_file_id or "drive.google.com" in web_url or "docs.google.com" in web_url else "web"
    elif drive_search_url:
        link_type = "drive_search"

    return {
        "id": source.get("id"),
        "title": source.get("title"),
        "kind": source.get("kind"),
        "tags": source.get("tags", []),
        "sourceType": source_type,
        "fileName": metadata.get("fileName"),
        "relativePath": relative_path,
        "webUrl": web_url,
        "driveFileId": drive_file_id,
        "driveSearchUrl": drive_search_url,
        "linkType": link_type,
    }


async def _attach_source_references(store: Any, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_ids: set[int] = set()
    for item in results:
        value = item.get("sourceId") or item.get("source_id")
        if value is None and item.get("entityType") == "source":
            value = item.get("entityId") or item.get("id")
        try:
            if value is not None:
                source_ids.add(int(value))
        except (TypeError, ValueError):
            continue

    if not source_ids or not hasattr(store, "get_source"):
        return results

    references: dict[int, dict[str, Any] | None] = {}
    for source_id in sorted(source_ids):
        source = await _run_brain_step(
            "Search source reference",
            store.get_source,
            source_id,
            timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
        )
        references[source_id] = _public_source_reference(source)

    enriched = []
    for item in results:
        next_item = dict(item)
        value = next_item.get("sourceId") or next_item.get("source_id")
        if value is None and next_item.get("entityType") == "source":
            value = next_item.get("entityId") or next_item.get("id")
        try:
            source_id = int(value) if value is not None else None
        except (TypeError, ValueError):
            source_id = None
        if source_id is not None:
            next_item["sourceId"] = source_id
            reference = references.get(source_id)
            if reference:
                next_item["source"] = reference
        enriched.append(next_item)
    return enriched


def _parse_reference_source_ids(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        raw_ids = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(raw_ids, list):
        return []

    source_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in raw_ids:
        try:
            source_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if source_id <= 0 or source_id in seen:
            continue
        seen.add(source_id)
        source_ids.append(source_id)
        if len(source_ids) >= MAX_REFERENCE_SOURCES:
            break
    return source_ids


async def _load_reference_sources(store: Any, source_ids: list[int]) -> list[dict[str, Any]]:
    if not source_ids or not hasattr(store, "get_source"):
        return []

    requests = [
        _run_brain_step(
            "Reference source lookup",
            store.get_source,
            source_id,
            timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
        )
        for source_id in source_ids
    ]
    results = await asyncio.gather(*requests, return_exceptions=True)
    sources: list[dict[str, Any]] = []
    for source_id, result in zip(source_ids, results):
        if isinstance(result, Exception) or not result:
            continue
        source = dict(result)
        source["id"] = int(source.get("id") or source_id)
        sources.append(source)
    return sources


async def _reference_sources_from_store(store: Any) -> tuple[list[int], list[dict[str, Any]]]:
    if not hasattr(store, "get_setting"):
        return [], []
    raw_ids = await _run_brain_step(
        "Reference set lookup",
        store.get_setting,
        REFERENCE_SOURCE_IDS_SETTING,
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    source_ids = _parse_reference_source_ids(raw_ids)
    sources = await _load_reference_sources(store, source_ids)
    available_ids = [int(source["id"]) for source in sources]
    return available_ids, sources


def _parse_full_context_source_ids(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        raw_ids = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(raw_ids, list):
        return []

    source_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in raw_ids:
        try:
            source_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if source_id <= 0 or source_id in seen:
            continue
        seen.add(source_id)
        source_ids.append(source_id)
        if len(source_ids) >= MAX_FULL_CONTEXT_SOURCES:
            break
    return source_ids


async def _full_context_sources_from_store(store: Any) -> tuple[list[int], list[dict[str, Any]]]:
    if not hasattr(store, "get_setting"):
        return [], []
    raw_ids = await _run_brain_step(
        "Full-document context lookup",
        store.get_setting,
        FULL_CONTEXT_SOURCE_IDS_SETTING,
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    source_ids = _parse_full_context_source_ids(raw_ids)
    sources = await _load_reference_sources(store, source_ids)
    available_ids = [int(source["id"]) for source in sources]
    return available_ids, sources


async def _system_prompt_from_store(store: Any) -> str:
    if not hasattr(store, "get_setting"):
        return DEFAULT_BRAIN_SYSTEM_PROMPT
    saved_prompt = await _run_brain_step(
        "System prompt lookup",
        store.get_setting,
        SYSTEM_PROMPT_SETTING,
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    clean_prompt = str(saved_prompt or "").strip()
    return clean_prompt[:MAX_SYSTEM_PROMPT_CHARS] or DEFAULT_BRAIN_SYSTEM_PROMPT


def _stitch_source_chunks(chunks: list[dict[str, Any]]) -> str:
    """Reconstruct indexed text while removing the indexer's word overlap."""
    stitched_words: list[str] = []
    max_overlap_words = 160
    for chunk in chunks:
        words = str(chunk.get("body") or "").split()
        if not words:
            continue
        overlap = 0
        max_overlap = min(max_overlap_words, len(stitched_words), len(words))
        for size in range(max_overlap, 0, -1):
            if stitched_words[-size:] == words[:size]:
                overlap = size
                break
        stitched_words.extend(words[overlap:])
    return " ".join(stitched_words).strip()


def _full_document_cache_key(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    version = (
        source.get("updatedAt")
        or source.get("updated_at")
        or metadata.get("indexedAt")
        or metadata.get("fileHash")
        or "unknown"
    )
    return f"{int(source['id'])}:{version}"


def _get_cached_full_document(source: dict[str, Any]) -> dict[str, Any] | None:
    cache_key = _full_document_cache_key(source)
    cached = full_document_text_cache.get(cache_key)
    if cached is not None:
        full_document_text_cache.move_to_end(cache_key)
    return cached


def _cache_full_document(source: dict[str, Any], *, full_text: str, chunk_count: int) -> dict[str, Any]:
    cache_key = _full_document_cache_key(source)
    cached = {"fullText": full_text, "chunkCount": chunk_count}
    full_document_text_cache[cache_key] = cached
    full_document_text_cache.move_to_end(cache_key)
    while len(full_document_text_cache) > FULL_DOCUMENT_CACHE_MAX_ENTRIES:
        full_document_text_cache.popitem(last=False)
    return cached


async def _build_full_document_context(
    store: Any,
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Load the full indexed text of selected documents with visible budgets."""
    if not sources or not hasattr(store, "list_chunks"):
        return []

    cached_documents: dict[int, dict[str, Any]] = {}
    uncached_sources: list[dict[str, Any]] = []
    for source in sources:
        cached = _get_cached_full_document(source)
        if cached is None:
            uncached_sources.append(source)
        else:
            cached_documents[int(source["id"])] = cached

    chunk_requests = [
        _run_brain_step(
            "Full-document chunk lookup",
            store.list_chunks,
            source_id=int(source["id"]),
            limit=500,
            timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
        )
        for source in uncached_sources
    ]
    chunk_results = await asyncio.gather(*chunk_requests, return_exceptions=True)
    for source, chunks in zip(uncached_sources, chunk_results):
        if isinstance(chunks, Exception):
            continue
        full_text = _stitch_source_chunks(chunks or [])
        if full_text:
            cached_documents[int(source["id"])] = _cache_full_document(
                source,
                full_text=full_text,
                chunk_count=len(chunks or []),
            )

    remaining_chars = FULL_CONTEXT_TOTAL_MAX_CHARS
    documents: list[dict[str, Any]] = []

    for source in sources:
        cached = cached_documents.get(int(source["id"]))
        if not cached:
            continue
        full_text = str(cached["fullText"])
        available_chars = len(full_text)
        chars_allowed = min(available_chars, FULL_CONTEXT_MAX_CHARS_PER_SOURCE, remaining_chars)
        if chars_allowed <= 0:
            break
        context_text = full_text[:chars_allowed]
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        index_truncated = bool(metadata.get("truncated"))
        documents.append({
            "sourceId": int(source["id"]),
            "source": _public_source_reference(source),
            "body": context_text,
            "chunkCount": int(cached["chunkCount"]),
            "charsIncluded": len(context_text),
            "availableChars": available_chars,
            "contextTruncated": len(context_text) < available_chars,
            "indexTruncated": index_truncated,
        })
        remaining_chars -= len(context_text)
    return documents


def _public_full_document_context(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sourceId": item.get("sourceId"),
            "source": item.get("source"),
            "chunkCount": item.get("chunkCount", 0),
            "charsIncluded": item.get("charsIncluded", 0),
            "availableChars": item.get("availableChars", 0),
            "contextTruncated": item.get("contextTruncated", False),
            "indexTruncated": item.get("indexTruncated", False),
        }
        for item in items
    ]


def _format_full_document_context(items: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(items, start=1):
        source = item.get("source") or {}
        source_title = source.get("title") or f"Source {item.get('sourceId')}"
        flags = []
        if item.get("contextTruncated"):
            flags.append("context cap reached")
        if item.get("indexTruncated"):
            flags.append("index extraction cap reached")
        flag_text = f" | {', '.join(flags)}" if flags else " | full indexed text"
        blocks.append(
            f"[F{index}] {source_title} | {item.get('charsIncluded', 0)} characters | "
            f"{item.get('chunkCount', 0)} chunks{flag_text}\n{item.get('body', '')}"
        )
    return "\n\n---\n\n".join(blocks)


async def _build_reference_context(
    store: Any,
    sources: list[dict[str, Any]],
    *,
    query_embedding: list[float] | None,
) -> tuple[list[dict[str, Any]], int]:
    """Build a bounded framework layer from every selected reference source.

    Each selected source contributes one query-relevant passage when embeddings
    are available, otherwise the first indexed passage acts as an anchor. This
    gives the model a stable investing lens without injecting whole books.
    """
    if not sources:
        return [], 0

    source_ids = [int(source["id"]) for source in sources]
    semantic_hits: list[dict[str, Any]] = []
    if query_embedding and hasattr(store, "semantic_search_chunks_in_sources"):
        try:
            semantic_hits = await _run_brain_step(
                "Reference semantic search",
                store.semantic_search_chunks_in_sources,
                query_embedding,
                source_ids,
                limit=len(source_ids) * 3,
                timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
            ) or []
            semantic_hits = _filter_semantic_results(semantic_hits)
        except Exception:
            semantic_hits = []

    best_hit_by_source: dict[int, dict[str, Any]] = {}
    for hit in semantic_hits:
        try:
            source_id = int(hit.get("sourceId") or hit.get("source_id"))
        except (TypeError, ValueError):
            continue
        if source_id in source_ids and source_id not in best_hit_by_source:
            best_hit_by_source[source_id] = hit

    missing_source_ids = [source_id for source_id in source_ids if source_id not in best_hit_by_source]
    fallback_chunks: dict[int, dict[str, Any]] = {}
    if missing_source_ids and hasattr(store, "list_chunks"):
        fallback_requests = [
            _run_brain_step(
                "Reference anchor lookup",
                store.list_chunks,
                source_id=source_id,
                limit=1,
                timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
            )
            for source_id in missing_source_ids
        ]
        fallback_results = await asyncio.gather(*fallback_requests, return_exceptions=True)
        for source_id, chunks in zip(missing_source_ids, fallback_results):
            if isinstance(chunks, Exception) or not chunks:
                continue
            fallback_chunks[source_id] = chunks[0]

    references: list[dict[str, Any]] = []
    for source in sources:
        source_id = int(source["id"])
        chunk = best_hit_by_source.get(source_id) or fallback_chunks.get(source_id)
        mode = "semantic" if source_id in best_hit_by_source else "anchor"
        if not chunk and source.get("body"):
            chunk = {
                "sourceId": source_id,
                "ordinal": 0,
                "title": source.get("title") or "Reference source",
                "body": str(source.get("body") or ""),
            }
        if not chunk:
            continue
        references.append({
            "sourceId": source_id,
            "source": _public_source_reference(source),
            "referenceMode": mode,
            "chunks": [chunk],
            "maxCharsPerChunk": 750,
        })

    return references, len(best_hit_by_source)


def _format_reference_context(items: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(items, start=1):
        source = item.get("source") or {}
        source_title = source.get("title") or f"Source {item.get('sourceId')}"
        mode = item.get("referenceMode") or "anchor"
        chunk = next((chunk for chunk in item.get("chunks", []) if chunk.get("body")), {})
        body = str(chunk.get("body") or "").strip()[: int(item.get("maxCharsPerChunk") or 750)]
        ordinal = chunk.get("ordinal")
        location = f" | passage {ordinal}" if isinstance(ordinal, int) and ordinal > 0 else ""
        blocks.append(f"[R{index}] {source_title} | persistent {mode} reference{location}\n{body}")
    return "\n\n".join(blocks)


async def _run_drive_index_job(
    *,
    folder_id: str | None,
    limit_files: int,
    max_bytes: int,
    changed_files_limit: int | None,
    force: bool,
) -> None:
    store = brain_store
    if not store or not index_drive_folder:
        drive_index_job.update({
            "running": False,
            "finishedAt": _utc_now_iso(),
            "message": "Drive sync cannot start: backend or Drive indexer is not configured.",
        })
        return

    drive_index_job.update({
        "running": True,
        "startedAt": _utc_now_iso(),
        "finishedAt": None,
        "folderId": folder_id,
        "folderUrl": None,
        "summary": None,
        "progress": None,
        "counts": None,
        "results": [],
        "message": "Drive sync started.",
    })

    try:
        def update_progress(progress: dict[str, Any]) -> None:
            summary = progress.get("summary") or {}
            current_file = progress.get("currentFile")
            processed = progress.get("processed", 0)
            total = progress.get("total", 0)
            drive_index_job["progress"] = progress
            drive_index_job["summary"] = summary
            current_note = f": {str(current_file)[:180]}" if current_file else ""
            drive_index_job["message"] = (
                f"Syncing Drive {processed}/{total} file(s)"
                f"{current_note}."
            )

        result = await run_in_threadpool(
            index_drive_folder,
            store,
            folder_id=folder_id,
            limit_files=limit_files,
            max_bytes=max_bytes,
            changed_files_limit=changed_files_limit,
            force=force,
            progress_callback=update_progress,
        )
        summary = result.get("summary") or {}
        drive_index_job.update({
            "folderId": result.get("folderId"),
            "folderUrl": result.get("folderUrl"),
            "summary": summary,
            "counts": result.get("counts"),
            "results": result.get("results", []),
            "message": (
                f"{summary.get('indexed', 0)} indexed, "
                f"{summary.get('skipped', 0)} skipped, "
                f"{summary.get('errors', 0)} errors, "
                f"{summary.get('deferred', 0)} deferred from "
                f"{summary.get('found', 0)} Drive file(s)."
            ),
        })
    except Exception as exc:
        drive_index_job["message"] = f"Drive sync stopped: {_clean_public_error(exc)}"
    finally:
        drive_index_job["running"] = False
        drive_index_job["finishedAt"] = _utc_now_iso()


async def _run_embedding_backfill_job(*, batch_size: int, max_chunks: int, force: bool) -> None:
    store = brain_store
    client = gemini_client
    if not store or not client or not client.configured:
        embedding_backfill_job.update({
            "running": False,
            "finishedAt": _utc_now_iso(),
            "message": "Embedding job cannot start: backend or Gemini is not configured.",
        })
        return

    embedding_backfill_job.update({
        "running": True,
        "startedAt": _utc_now_iso(),
        "finishedAt": None,
        "model": client.embedding_model,
        "requested": 0,
        "embedded": 0,
        "errors": [],
        "message": "Embedding job started.",
    })

    processed = 0
    skipped_chunk_ids: set[int] = set()
    try:
        while processed < max_chunks:
            limit = min(batch_size, max_chunks - processed)
            fetch_limit = limit + len(skipped_chunk_ids)
            chunks = await _run_brain_step(
                "Embedding chunk list",
                store.list_chunks_for_embedding,
                limit=fetch_limit,
                force=force,
                timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
            )
            chunks = [
                chunk for chunk in chunks
                if int(chunk.get("id")) not in skipped_chunk_ids
            ][:limit]
            embedding_backfill_job["requested"] += len(chunks)
            if not chunks:
                embedding_backfill_job["message"] = "No missing chunks left."
                break

            for chunk in chunks:
                title = str(chunk.get("title") or f"chunk {chunk.get('id')}")
                embedding_backfill_job["message"] = f"Embedding {title[:120]}"
                try:
                    embedding = await _run_brain_step(
                        "Gemini embedding",
                        client.embed_text,
                        chunk["body"],
                        task_type="RETRIEVAL_DOCUMENT",
                        timeout=float(getattr(client, "embedding_timeout", 15.0)) + 5.0,
                    )
                    await _run_brain_step(
                        "Store embedding",
                        store.update_chunk_embedding,
                        int(chunk["id"]),
                        embedding_model=client.embedding_model,
                        embedding=embedding,
                        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
                    )
                    embedding_backfill_job["embedded"] += 1
                except Exception as exc:
                    try:
                        skipped_chunk_ids.add(int(chunk.get("id")))
                    except (TypeError, ValueError):
                        pass
                    embedding_backfill_job["errors"].append({
                        "id": chunk.get("id"),
                        "title": title,
                        "error": str(exc)[:300],
                    })
                processed += 1

            if hasattr(store, "embedding_stats"):
                embedding_backfill_job["embeddings"] = await _run_brain_step(
                    "Embedding coverage",
                    store.embedding_stats,
                    timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
                )
                missing = int((embedding_backfill_job["embeddings"] or {}).get("missing") or 0)
                embedding_backfill_job["message"] = f"{missing} chunks still missing embeddings."
                if missing <= 0:
                    break

            if chunks and embedding_backfill_job["embedded"] == 0 and embedding_backfill_job["errors"]:
                embedding_backfill_job["message"] = "Embedding job stopped after provider errors. Check Google AI key, quota, billing, or model access."
                break

            await asyncio.sleep(0.5)
    except Exception as exc:
        embedding_backfill_job["message"] = f"Embedding job stopped: {str(exc)[:300]}"
    finally:
        if hasattr(store, "embedding_stats"):
            try:
                embedding_backfill_job["embeddings"] = await _run_brain_step(
                    "Embedding coverage",
                    store.embedding_stats,
                    timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
                )
            except Exception:
                pass
        embedding_backfill_job["running"] = False
        embedding_backfill_job["finishedAt"] = _utc_now_iso()
        if embedding_backfill_job.get("embedded", 0) > 0 and not str(embedding_backfill_job.get("message", "")).startswith("Embedding job stopped"):
            embedding_backfill_job["message"] = "Embedding job finished."


def _local_indexing_enabled() -> bool:
    return os.environ.get("BRAIN_ENABLE_LOCAL_INDEXING", "").strip().lower() in {"1", "true", "yes", "on"}


def _queue_embedding_after_import(max_chunks: int) -> bool:
    if not gemini_client or not gemini_client.configured:
        return False
    if embedding_backfill_job.get("running"):
        return False
    asyncio.create_task(_run_embedding_backfill_job(
        batch_size=5,
        max_chunks=max(1, min(int(max_chunks), 500)),
        force=False,
    ))
    return True


class BrainMemoryRequest(BaseModel):
    type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=240)
    body: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"
    confidence: float | None = Field(default=None, ge=0, le=1)


class BrainSourceRequest(BaseModel):
    kind: str = "note"
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    author: str | None = None
    sourceDate: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class BrainChunkRequest(BaseModel):
    ordinal: int = 0
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    summary: str | None = None
    tokenCount: int = 0
    pageStart: int | None = None
    pageEnd: int | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    contentHash: str | None = None
    embeddingModel: str | None = None
    embedding: list[float] | None = None


class BrainTextIngestRequest(BaseModel):
    kind: str = "document"
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)
    author: str | None = None
    sourceDate: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunkWords: int = Field(default=900, ge=150, le=2500)
    overlapWords: int = Field(default=120, ge=0, le=800)


class BrainLocalIndexRequest(BaseModel):
    rootPath: str | None = None
    extensions: list[str] | None = None
    limitFiles: int = Field(default=250, ge=1, le=5000)
    maxBytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    force: bool = False


class BrainDriveIndexRequest(BaseModel):
    folderId: str | None = None
    limitFiles: int = Field(default=2000, ge=1, le=2000)
    maxBytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    changedFilesLimit: int | None = Field(default=10, ge=1, le=100)
    force: bool = False


class BrainEmbeddingBackfillRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=25)
    force: bool = False


class BrainEmbeddingBackfillStartRequest(BaseModel):
    batchSize: int = Field(default=5, ge=1, le=10)
    maxChunks: int = Field(default=500, ge=1, le=5000)
    force: bool = False


class BrainAgentUrlImportRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    tags: list[str] = Field(default_factory=list)
    uploadToDrive: bool = True
    driveFolderId: str | None = None
    driveSubfolder: str = Field(default="Agent Downloads", min_length=1, max_length=120)
    force: bool = False
    trustedOnly: bool = False
    maxBytes: int = Field(default=DEFAULT_AGENT_MAX_BYTES, ge=1024, le=75 * 1024 * 1024)
    embedAfterImport: bool = True
    embedMaxChunks: int = Field(default=60, ge=1, le=500)
    agentTask: str | None = Field(default=None, max_length=500)


class BrainAgentOfficialSearchRequest(BaseModel):
    task: str = Field(..., min_length=3, max_length=500)
    company: str | None = Field(default=None, max_length=120)
    ticker: str | None = Field(default=None, max_length=20)
    limit: int = Field(default=8, ge=1, le=20)


class BrainAgentRunRequest(BaseModel):
    task: str = Field(..., min_length=3, max_length=500)
    company: str | None = Field(default=None, max_length=120)
    ticker: str | None = Field(default=None, max_length=20)
    importBest: bool = False
    uploadToDrive: bool = True
    driveFolderId: str | None = None
    driveSubfolder: str = Field(default="Agent Downloads", min_length=1, max_length=120)
    force: bool = False
    maxBytes: int = Field(default=DEFAULT_AGENT_MAX_BYTES, ge=1024, le=75 * 1024 * 1024)
    embedAfterImport: bool = True
    embedMaxChunks: int = Field(default=60, ge=1, le=500)


class BrainReferenceSetRequest(BaseModel):
    sourceIds: list[int] = Field(default_factory=list, max_length=MAX_REFERENCE_SOURCES)


class BrainFullContextSetRequest(BaseModel):
    sourceIds: list[int] = Field(default_factory=list, max_length=MAX_FULL_CONTEXT_SOURCES)


class BrainSystemPromptRequest(BaseModel):
    systemPrompt: str = Field(default="", max_length=MAX_SYSTEM_PROMPT_CHARS)


class BrainConversationTurn(BaseModel):
    role: str = Field(..., min_length=1, max_length=20)
    content: str = Field(..., min_length=1, max_length=5000)


class BrainCompanyAnalysisRequest(BaseModel):
    ticker: str | None = Field(default=None, max_length=40)
    question: str | None = Field(default=None, max_length=4000)
    limit: int = Field(default=8, ge=1, le=20)
    useSemantic: bool = True
    conversation: list[BrainConversationTurn] = Field(default_factory=list, max_length=12)


def _safe_backend_error(message: str | None) -> str:
    if not message:
        return "not initialized"

    clean = str(message)
    clean = re.sub(r"postgres(?:ql)?://[^\s]+", "postgresql://<redacted>", clean)
    clean = re.sub(r"password=[^\s]+", "password=<redacted>", clean, flags=re.IGNORECASE)
    clean = re.sub(r"(api[_-]?key|secret|token)=([^\s&]+)", r"\1=<redacted>", clean, flags=re.IGNORECASE)
    return clean[:500]


def _brain_or_503():
    if not brain_store:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Investment Brain store is not available",
                "startupError": _safe_backend_error(brain_store_error),
            },
        )
    return brain_store


def _gemini_or_503():
    if not gemini_client:
        raise HTTPException(status_code=503, detail="Gemini client is not available")
    if not gemini_client.configured:
        raise HTTPException(
            status_code=503,
            detail="Google AI API key is not configured. Set GOOGLE_AI_API_KEY or GEMINI_API_KEY.",
        )
    return gemini_client

def _get_cached_market_data(force: bool = False, portfolio_name: str = "main"):
    """Fetch and cache raw market data for a portfolio."""
    global _data_cache
    now = time.time()
    
    if portfolio_name not in _data_cache:
        _data_cache[portfolio_name] = {"data": None, "timestamp": 0}
        
    cache_entry = _data_cache[portfolio_name]
    
    if not force and cache_entry["data"] and (now - cache_entry["timestamp"]) < CACHE_TTL:
        print(f"Using cached market data for {portfolio_name} (age: {int(now - cache_entry['timestamp'])}s)")
        return cache_entry["data"]
    
    print(f"Fetching fresh market data for {portfolio_name}...")
    raw_prices, fx_rates, volume_data = risk.fetch_data(portfolio_name)
    usd_prices = risk.normalize_to_base_currency(raw_prices, fx_rates, portfolio_name)
    cache_entry["data"] = (usd_prices, fx_rates, volume_data, raw_prices)
    cache_entry["timestamp"] = now
    return cache_entry["data"]


def _nearest_price(raw_prices, ticker: str, effective_date: str):
    """Return the latest original-currency price available at or before a change date."""
    if raw_prices is None or ticker not in raw_prices.columns:
        return None, None

    series = raw_prices[ticker].dropna()
    if series.empty:
        return None, None

    price_date = pd.Timestamp(effective_date).tz_localize(None)
    index = series.index
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    series = pd.Series(series.values, index=index)

    prior = series[series.index <= price_date]
    if prior.empty:
        nearest_date = series.index[0]
        nearest_price = series.iloc[0]
    else:
        nearest_date = prior.index[-1]
        nearest_price = prior.iloc[-1]

    return nearest_date.strftime("%Y-%m-%d"), float(nearest_price)


def _position_summary(info: dict | None):
    if not info:
        return {
            "weight": 0.0,
            "direction": None,
            "currency": None,
            "sector": None,
            "country": None,
        }
    return {
        "weight": float(info.get("weight", 0) or 0),
        "direction": info.get("type", "Long"),
        "currency": info.get("currency"),
        "sector": info.get("sector"),
        "country": info.get("country"),
    }


def _build_rebalance_change_history(portfolio: str, raw_prices, ytd_position_contributions: dict):
    """Compare dated books and expose a readable rebalance ledger for the UI."""
    target_config = risk.load_portfolio_config(portfolio)
    snapshots = risk.get_rebalance_snapshots(portfolio, target_config)
    if not snapshots:
        return []

    today = pd.Timestamp(datetime.now()).tz_localize(None).normalize()
    history = []
    previous_positions = {}

    for idx, snapshot in enumerate(snapshots):
        positions = snapshot.get("positions", {}) or {}
        effective_date = str(snapshot.get("date"))
        effective_ts = pd.Timestamp(effective_date).tz_localize(None).normalize()
        all_tickers = sorted(set(previous_positions.keys()) | set(positions.keys()))
        changes = []

        for ticker in all_tickers:
            before = _position_summary(previous_positions.get(ticker))
            after = _position_summary(positions.get(ticker))
            before_weight = before["weight"]
            after_weight = after["weight"]
            before_direction = before["direction"]
            after_direction = after["direction"]

            if idx == 0 and after_weight > 0:
                action = "opening"
            elif before_weight == 0 and after_weight > 0:
                action = "added"
            elif before_weight > 0 and after_weight == 0:
                action = "removed"
            elif before_weight > 0 and after_weight > 0 and before_direction != after_direction:
                action = "flipped"
            elif after_weight > before_weight + 1e-9:
                action = "increased"
            elif after_weight < before_weight - 1e-9:
                action = "reduced"
            else:
                continue

            price_date, price = _nearest_price(raw_prices, ticker, effective_date)
            metadata = after if after_weight > 0 else before
            contribution = ytd_position_contributions.get(ticker)
            if contribution is not None:
                try:
                    contribution = float(contribution)
                    if pd.isna(contribution):
                        contribution = None
                except Exception:
                    contribution = None

            changes.append({
                "ticker": ticker,
                "action": action,
                "beforeWeight": before_weight if before_weight > 0 else None,
                "afterWeight": after_weight if after_weight > 0 else None,
                "weightDelta": after_weight - before_weight,
                "beforeDirection": before_direction,
                "afterDirection": after_direction,
                "currency": metadata.get("currency"),
                "sector": metadata.get("sector"),
                "country": metadata.get("country"),
                "priceAtChange": price,
                "priceDate": price_date,
                "ytdContribution": contribution,
            })

        before_exposure = risk.calculate_exposure_stats(previous_positions) if previous_positions else None
        after_exposure = risk.calculate_exposure_stats(positions)
        history.append({
            "date": effective_date,
            "label": snapshot.get("label", "Portfolio snapshot"),
            "source": snapshot.get("source", "snapshot"),
            "executionTiming": snapshot.get("executionTiming", "effective_open"),
            "status": "active" if effective_ts <= today else "planned",
            "changeCount": len(changes),
            "beforeExposure": before_exposure,
            "afterExposure": after_exposure,
            "changes": changes,
        })
        previous_positions = positions

    return history

CACHE_TTL = 300  # seconds

@app.get("/api/status")
async def get_status():
    if risk:
        return {"state": "ready", "message": "Ready"}
    else:
        return {"state": "error", "message": "Risk module failed to load"}


# ==========================================
# Investment Brain API (SQLite + unified FTS)
# ==========================================

@app.get("/api/brain/status")
async def get_brain_status():
    now = time.monotonic()
    cached_payload = brain_status_cache.get("payload")
    if cached_payload is not None and now < float(brain_status_cache.get("expiresAt") or 0):
        return cached_payload

    store = _brain_or_503()
    counts = await _run_brain_step("Brain counts", store.counts)
    embeddings = await _run_brain_step(
        "Embedding coverage",
        store.embedding_stats if hasattr(store, "embedding_stats") else lambda: {},
    )
    capabilities = [
        "manual_memories",
        "source_storage",
        "text_ingestion",
        "chunk_indexing",
        "google_drive_indexing",
        "keyword_search",
        "semantic_vector_search",
        "gemini_embeddings",
        "gemini_company_analysis",
        "embedding_ready_schema",
        "persistent_reference_layer",
        "full_document_context",
        "editable_system_prompt",
        "live_portfolio_context",
        "yahoo_momentum_context",
        "question_routed_market_data",
        "completed_session_volume_screen",
    ]
    if import_url_into_brain:
        capabilities.append("agentic_url_import")
    if find_official_source_candidates:
        capabilities.append("official_source_finder")
    if _local_indexing_enabled():
        capabilities.append("local_file_indexing")

    payload = {
        "state": "ready",
        "database": getattr(store, "database_label", str(getattr(store, "db_path", "unknown"))),
        "storage": getattr(store, "storage_label", "unknown"),
        "search": getattr(store, "search_label", "unknown"),
        "vectorSearch": getattr(store, "vector_search_label", "unknown"),
        "embeddingProvider": "google_ai_studio" if gemini_client and gemini_client.configured else "not_configured",
        "llm": gemini_client.status() if gemini_client else {"configured": False},
        "capabilities": capabilities,
        "counts": counts,
        "embeddings": embeddings,
    }
    brain_status_cache["payload"] = payload
    brain_status_cache["expiresAt"] = now + BRAIN_STATUS_CACHE_SECONDS
    return payload


@app.get("/api/brain/llm/status")
async def get_brain_llm_status():
    if not gemini_client:
        return {"configured": False, "provider": None}
    return gemini_client.status()


@app.get("/api/brain/embeddings/status")
async def get_brain_embedding_status():
    store = _brain_or_503()
    if not hasattr(store, "embedding_stats"):
        return {"total": 0, "embedded": 0, "missing": 0, "coverage": 0, "models": []}
    return await _run_brain_step("Embedding coverage", store.embedding_stats)


@app.get("/api/brain/embeddings/backfill/status")
async def get_brain_embedding_backfill_status():
    return _public_embedding_job()


@app.get("/api/brain/index/local/status")
async def get_local_indexer_status(rootPath: str | None = None):
    _brain_or_503()
    if not _local_indexing_enabled():
        raise HTTPException(status_code=403, detail="Local folder indexing is disabled. Use Google Drive sync instead.")
    if not indexer_status:
        raise HTTPException(status_code=503, detail="Local brain indexer is not available")
    try:
        return indexer_status(rootPath)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _drive_or_503() -> GoogleDriveClient:
    store = _brain_or_503()
    if not GoogleDriveClient:
        raise HTTPException(status_code=503, detail="Google Drive client is not available")
    return GoogleDriveClient(store=store)


@app.get("/api/brain/index/drive/status")
async def get_drive_indexer_status():
    client = _drive_or_503()
    folder_id = parse_drive_folder_id() if parse_drive_folder_id else None
    status = await _run_brain_step("Drive index status", client.status, folder_id)
    if not status.get("configured"):
        status["connectionState"] = "not_configured"
        return status

    try:
        await _run_brain_step("Drive authorization", client.get_access_token, timeout=35)
        status["connected"] = True
        status["connectionState"] = "ready"
    except Exception:
        # A stored token alone is not proof that Google will still authorize it.
        # Keep the raw provider error server-side and give the UI an actionable state.
        status["connected"] = False
        status["connectionState"] = "needs_reconnect"
        status["connectionMessage"] = "Google Drive authorization expired. Reconnect to sync new files."
    return status


@app.get("/api/brain/index/drive/job/status")
async def get_drive_index_job_status():
    return _public_drive_job()


@app.get("/api/brain/index/drive/files")
async def list_google_drive_brain_files(limitFiles: int = 2000):
    client = _drive_or_503()
    if not parse_drive_folder_id:
        raise HTTPException(status_code=503, detail="Google Drive folder parser is not available")
    folder_id = parse_drive_folder_id()
    if not folder_id:
        raise HTTPException(status_code=400, detail="GOOGLE_DRIVE_FOLDER_ID is not configured")

    limit_files = max(1, min(int(limitFiles), 5000))
    try:
        files = await _run_brain_step(
            "Drive file listing",
            client.iter_files,
            folder_id,
            limit_files=limit_files,
            timeout=BRAIN_INDEX_TIMEOUT_SECONDS,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Google Drive file listing failed: {_clean_public_error(e)}",
        )
    items = []
    for file in files:
        extension = extension_for_file(file) if extension_for_file else None
        items.append({
            "id": file.get("id"),
            "name": file.get("name"),
            "relativePath": file.get("relativePath"),
            "mimeType": file.get("mimeType"),
            "size": file.get("size"),
            "modifiedTime": file.get("modifiedTime"),
            "webViewLink": file.get("webViewLink"),
            "extension": extension,
            "supported": bool(extension),
        })

    return {
        "folderId": folder_id,
        "folderUrl": f"https://drive.google.com/drive/folders/{folder_id}",
        "summary": {
            "found": len(items),
            "supported": sum(1 for item in items if item["supported"]),
            "unsupported": sum(1 for item in items if not item["supported"]),
            "limitFiles": limit_files,
            "limitReached": len(items) >= limit_files,
        },
        "files": items,
    }


@app.get("/api/brain/drive/auth-url")
async def get_drive_auth_url(request: Request):
    _drive_or_503()
    if not google_drive_auth_url or not configured_redirect_uri:
        raise HTTPException(status_code=503, detail="Google Drive OAuth is not available")

    redirect_uri = configured_redirect_uri(str(request.url_for("google_drive_oauth_callback")))
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="Google Drive redirect URI is not configured")
    try:
        return {"url": google_drive_auth_url(redirect_uri), "redirectUri": redirect_uri}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/brain/drive/oauth/callback", response_class=HTMLResponse)
async def google_drive_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    client = _drive_or_503()
    if error:
        return HTMLResponse(
            f"<h1>Google Drive connection failed</h1><p>{html.escape(error)}</p>",
            status_code=400,
        )
    if not code:
        return HTMLResponse("<h1>Google Drive connection failed</h1><p>Missing OAuth code.</p>", status_code=400)

    expected_state = os.environ.get("GOOGLE_OAUTH_STATE")
    if expected_state and state != expected_state:
        return HTMLResponse("<h1>Google Drive connection failed</h1><p>Invalid OAuth state.</p>", status_code=400)

    redirect_uri = configured_redirect_uri(str(request.url_for("google_drive_oauth_callback"))) if configured_redirect_uri else None
    try:
        result = client.exchange_code(code, redirect_uri)
    except Exception as e:
        return HTMLResponse(
            f"<h1>Google Drive connection failed</h1><p>{html.escape(str(e))}</p>",
            status_code=400,
        )

    refresh_message = (
        "Refresh token saved to the brain database."
        if result.get("hasRefreshToken")
        else "Access granted, but Google did not return a refresh token. Reconnect with prompt=consent or set GOOGLE_DRIVE_REFRESH_TOKEN in Render."
    )
    return HTMLResponse(
        "<h1>Google Drive connected</h1>"
        f"<p>{refresh_message}</p>"
        "<p>You can close this tab and return to the Investment Brain.</p>"
    )


@app.get("/api/auth/google/callback", response_class=HTMLResponse)
async def google_drive_legacy_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    return await google_drive_oauth_callback(request=request, code=code, state=state, error=error)


@app.post("/api/brain/index/local")
async def index_local_brain_library(payload: BrainLocalIndexRequest):
    store = _brain_or_503()
    if not _local_indexing_enabled():
        raise HTTPException(status_code=403, detail="Local folder indexing is disabled. Use Google Drive sync instead.")
    if not index_local_library:
        raise HTTPException(status_code=503, detail="Local brain indexer is not available")
    try:
        return await _run_brain_step(
            "Local library indexing",
            index_local_library,
            store,
            root_path=payload.rootPath,
            extensions=payload.extensions,
            limit_files=payload.limitFiles,
            max_bytes=payload.maxBytes,
            force=payload.force,
            timeout=BRAIN_INDEX_TIMEOUT_SECONDS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/brain/index/drive")
async def index_google_drive_brain_folder(payload: BrainDriveIndexRequest):
    store = _brain_or_503()
    if not index_drive_folder:
        raise HTTPException(status_code=503, detail="Google Drive indexer is not available")
    try:
        return await _run_brain_step(
            "Google Drive indexing",
            index_drive_folder,
            store,
            folder_id=payload.folderId,
            limit_files=payload.limitFiles,
            max_bytes=payload.maxBytes,
            changed_files_limit=payload.changedFilesLimit,
            force=payload.force,
            timeout=BRAIN_INDEX_TIMEOUT_SECONDS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/brain/index/drive/start")
async def start_google_drive_brain_index(payload: BrainDriveIndexRequest):
    _brain_or_503()
    if not index_drive_folder:
        raise HTTPException(status_code=503, detail="Google Drive indexer is not available")
    if drive_index_job.get("running"):
        return _public_drive_job()

    asyncio.create_task(_run_drive_index_job(
        folder_id=payload.folderId,
        limit_files=payload.limitFiles,
        max_bytes=payload.maxBytes,
        changed_files_limit=payload.changedFilesLimit,
        force=payload.force,
    ))
    return {
        **_public_drive_job(),
        "message": "Drive sync queued.",
    }


@app.post("/api/brain/agent/import-url")
async def import_brain_agent_url(payload: BrainAgentUrlImportRequest):
    store = _brain_or_503()
    if not import_url_into_brain:
        raise HTTPException(status_code=503, detail="Brain research agent is not available")

    try:
        result = await _run_brain_step(
            "Brain agent URL import",
            import_url_into_brain,
            store,
            url=payload.url,
            title=payload.title,
            tags=payload.tags,
            upload_to_drive=payload.uploadToDrive,
            drive_folder_id=payload.driveFolderId,
            drive_subfolder=payload.driveSubfolder,
            force=payload.force,
            max_bytes=payload.maxBytes,
            trusted_only=payload.trustedOnly,
            agent_task=payload.agentTask,
            timeout=BRAIN_INDEX_TIMEOUT_SECONDS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_clean_public_error(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=_clean_public_error(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_clean_public_error(e))

    embedding_queued = bool(
        payload.embedAfterImport
        and result.get("status") == "indexed"
        and _queue_embedding_after_import(payload.embedMaxChunks)
    )
    return {
        **result,
        "embeddingQueued": embedding_queued,
    }


@app.post("/api/brain/agent/find-official-sources")
async def find_brain_agent_official_sources(payload: BrainAgentOfficialSearchRequest):
    if not find_official_source_candidates:
        raise HTTPException(status_code=503, detail="Official source finder is not available")

    try:
        return await _run_brain_step(
            "Official source finder",
            find_official_source_candidates,
            task=payload.task,
            company=payload.company,
            ticker=payload.ticker,
            limit=payload.limit,
            timeout=BRAIN_INDEX_TIMEOUT_SECONDS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_clean_public_error(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=_clean_public_error(e))


@app.post("/api/brain/agent/run")
async def run_brain_research_agent(payload: BrainAgentRunRequest):
    store = _brain_or_503()
    if not find_official_source_candidates or not import_url_into_brain:
        raise HTTPException(status_code=503, detail="Brain research agent is not available")

    try:
        plan = await _run_brain_step(
            "Official source finder",
            find_official_source_candidates,
            task=payload.task,
            company=payload.company,
            ticker=payload.ticker,
            limit=8,
            timeout=BRAIN_INDEX_TIMEOUT_SECONDS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_clean_public_error(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=_clean_public_error(e))

    candidates = plan.get("candidates", []) if isinstance(plan, dict) else []
    if not payload.importBest:
        return {
            "action": "planned",
            "plan": plan,
            "message": "Reviewed official candidates. Import was not requested.",
        }
    if not candidates:
        return {
            "action": "no_candidate",
            "plan": plan,
            "message": "No trusted official source candidate was found.",
        }

    best = candidates[0]
    best_url = best.get("url")
    if not best_url:
        raise HTTPException(status_code=502, detail="Top official source candidate is missing a URL")
    resolved = plan.get("resolvedCompany") or {}
    ticker = str(resolved.get("ticker") or payload.ticker or "").upper()
    tags = ["official-source", "sec"]
    if ticker:
        tags.append(ticker.lower())

    try:
        imported = await _run_brain_step(
            "Brain agent official import",
            import_url_into_brain,
            store,
            url=best_url,
            title=best.get("title"),
            tags=tags,
            upload_to_drive=payload.uploadToDrive,
            drive_folder_id=payload.driveFolderId,
            drive_subfolder=payload.driveSubfolder,
            force=payload.force,
            max_bytes=payload.maxBytes,
            trusted_only=True,
            agent_task=payload.task,
            source_label=best.get("source"),
            timeout=BRAIN_INDEX_TIMEOUT_SECONDS,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_clean_public_error(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=_clean_public_error(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_clean_public_error(e))

    embedding_queued = bool(
        payload.embedAfterImport
        and imported.get("status") == "indexed"
        and _queue_embedding_after_import(payload.embedMaxChunks)
    )
    return {
        "action": "imported_best_candidate",
        "plan": plan,
        "import": imported,
        "embeddingQueued": embedding_queued,
        "message": "Imported the top trusted official source.",
    }


@app.get("/api/brain/memories")
async def list_brain_memories(
    q: str | None = None,
    memory_type: str | None = Query(default=None, alias="type"),
    limit: int = 100,
):
    store = _brain_or_503()
    try:
        memories = await _run_brain_step(
            "Memory list",
            store.list_memories,
            query=q,
            memory_type=memory_type,
            limit=limit,
        )
        return {"memories": memories}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/brain/memories")
async def add_brain_memory(memory: BrainMemoryRequest):
    store = _brain_or_503()
    try:
        saved = store.add_memory(
            memory_type=memory.type,
            title=memory.title,
            body=memory.body,
            tags=memory.tags,
            source=memory.source,
            confidence=memory.confidence,
        )
        return {"memory": saved}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/brain/memories/{memory_id}")
async def delete_brain_memory(memory_id: int):
    store = _brain_or_503()
    deleted = store.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted", "id": memory_id}


@app.post("/api/brain/sources")
async def add_brain_source(source: BrainSourceRequest):
    store = _brain_or_503()
    try:
        saved = store.add_source(
            kind=source.kind,
            title=source.title,
            body=source.body,
            author=source.author,
            source_date=source.sourceDate,
            tags=source.tags,
            metadata=source.metadata,
        )
        return {"source": saved}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/brain/sources")
async def list_brain_sources(
    q: str | None = None,
    kind: str | None = None,
    limit: int = 100,
):
    store = _brain_or_503()
    sources = await _run_brain_step(
        "Source list",
        store.list_sources,
        query=q,
        kind=kind,
        limit=limit,
    )
    return {"sources": sources}


@app.get("/api/brain/references")
async def get_brain_reference_set():
    store = _brain_or_503()
    source_ids, sources = await _reference_sources_from_store(store)
    return {
        "maxSources": MAX_REFERENCE_SOURCES,
        "sourceIds": source_ids,
        "sources": [_public_source_reference(source) for source in sources],
    }


@app.put("/api/brain/references")
async def update_brain_reference_set(payload: BrainReferenceSetRequest):
    store = _brain_or_503()
    requested_ids = _parse_reference_source_ids(json.dumps(payload.sourceIds))
    if len(requested_ids) != len(payload.sourceIds) or len(set(payload.sourceIds)) != len(payload.sourceIds):
        raise HTTPException(status_code=400, detail="Reference source IDs must be unique positive integers.")

    sources = await _load_reference_sources(store, requested_ids)
    found_ids = {int(source["id"]) for source in sources}
    missing_ids = [source_id for source_id in requested_ids if source_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Reference source not found: {missing_ids[0]}")
    if not hasattr(store, "set_setting"):
        raise HTTPException(status_code=503, detail="Brain settings are not available")

    await _run_brain_step(
        "Reference set save",
        store.set_setting,
        REFERENCE_SOURCE_IDS_SETTING,
        json.dumps(requested_ids),
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    return {
        "maxSources": MAX_REFERENCE_SOURCES,
        "sourceIds": requested_ids,
        "sources": [_public_source_reference(source) for source in sources],
    }


@app.get("/api/brain/full-context")
async def get_brain_full_context_set():
    store = _brain_or_503()
    source_ids, sources = await _full_context_sources_from_store(store)
    return {
        "maxSources": MAX_FULL_CONTEXT_SOURCES,
        "sourceIds": source_ids,
        "sources": [_public_source_reference(source) for source in sources],
        "maxCharsPerSource": FULL_CONTEXT_MAX_CHARS_PER_SOURCE,
        "totalMaxChars": FULL_CONTEXT_TOTAL_MAX_CHARS,
    }


@app.put("/api/brain/full-context")
async def update_brain_full_context_set(payload: BrainFullContextSetRequest):
    store = _brain_or_503()
    requested_ids = _parse_full_context_source_ids(json.dumps(payload.sourceIds))
    if len(requested_ids) != len(payload.sourceIds) or len(set(payload.sourceIds)) != len(payload.sourceIds):
        raise HTTPException(status_code=400, detail="Full-document source IDs must be unique positive integers.")

    sources = await _load_reference_sources(store, requested_ids)
    found_ids = {int(source["id"]) for source in sources}
    missing_ids = [source_id for source_id in requested_ids if source_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Full-document source not found: {missing_ids[0]}")
    if not hasattr(store, "set_setting"):
        raise HTTPException(status_code=503, detail="Brain settings are not available")

    await _run_brain_step(
        "Full-document context save",
        store.set_setting,
        FULL_CONTEXT_SOURCE_IDS_SETTING,
        json.dumps(requested_ids),
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    return {
        "maxSources": MAX_FULL_CONTEXT_SOURCES,
        "sourceIds": requested_ids,
        "sources": [_public_source_reference(source) for source in sources],
        "maxCharsPerSource": FULL_CONTEXT_MAX_CHARS_PER_SOURCE,
        "totalMaxChars": FULL_CONTEXT_TOTAL_MAX_CHARS,
    }


@app.get("/api/brain/system-prompt")
async def get_brain_system_prompt():
    store = _brain_or_503()
    return {
        "systemPrompt": await _system_prompt_from_store(store),
        "defaultSystemPrompt": DEFAULT_BRAIN_SYSTEM_PROMPT,
        "maxChars": MAX_SYSTEM_PROMPT_CHARS,
    }


@app.put("/api/brain/system-prompt")
async def update_brain_system_prompt(payload: BrainSystemPromptRequest):
    store = _brain_or_503()
    if not hasattr(store, "set_setting"):
        raise HTTPException(status_code=503, detail="Brain settings are not available")
    system_prompt = payload.systemPrompt.strip() or DEFAULT_BRAIN_SYSTEM_PROMPT
    await _run_brain_step(
        "System prompt save",
        store.set_setting,
        SYSTEM_PROMPT_SETTING,
        system_prompt,
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    return {
        "systemPrompt": system_prompt,
        "defaultSystemPrompt": DEFAULT_BRAIN_SYSTEM_PROMPT,
        "maxChars": MAX_SYSTEM_PROMPT_CHARS,
    }


@app.delete("/api/brain/sources/{source_id}")
async def delete_brain_source(source_id: int):
    store = _brain_or_503()
    deleted = store.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"status": "deleted", "id": source_id, "counts": store.counts()}


@app.post("/api/brain/ingest/text")
async def ingest_brain_text(payload: BrainTextIngestRequest):
    store = _brain_or_503()
    body = normalize_text(payload.body)
    if not body:
        raise HTTPException(status_code=400, detail="body is required")

    metadata = {
        **payload.metadata,
        "sourceHash": stable_hash(payload.title, body),
        "ingestion": {
            "mode": "text",
            "chunkWords": payload.chunkWords,
            "overlapWords": payload.overlapWords,
            "embeddingProvider": "not_configured",
        },
    }

    try:
        source = store.add_source(
            kind=payload.kind,
            title=payload.title,
            body=body,
            author=payload.author,
            source_date=payload.sourceDate,
            tags=payload.tags,
            metadata=metadata,
        )
        chunks = chunk_text(
            body,
            source_title=payload.title,
            tags=payload.tags,
            chunk_words=payload.chunkWords,
            overlap_words=payload.overlapWords,
        )
        saved_chunks = store.add_chunks(source["id"], chunks)
        return {
            "source": source,
            "chunks": saved_chunks,
            "counts": store.counts(),
            "message": "Text stored, chunked, and indexed. Embeddings can be attached later.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/brain/sources/{source_id}/chunks")
async def add_brain_chunks(source_id: int, chunks: list[BrainChunkRequest]):
    store = _brain_or_503()
    prepared = []
    for chunk in chunks:
        data = chunk.dict()
        body = normalize_text(data["body"])
        data["body"] = body
        data["contentHash"] = data["contentHash"] or stable_hash(str(source_id), str(data["ordinal"]), body)
        prepared.append(data)

    try:
        saved = store.add_chunks(source_id, prepared)
        return {"chunks": saved, "counts": store.counts()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/brain/chunks")
async def list_brain_chunks(
    source_id: int | None = None,
    q: str | None = None,
    limit: int = 100,
):
    store = _brain_or_503()
    chunks = await _run_brain_step(
        "Chunk list",
        store.list_chunks,
        source_id=source_id,
        query=q,
        limit=limit,
    )
    return {"chunks": chunks}


@app.get("/api/brain/sources/{source_id}/chunks")
async def list_brain_source_chunks(source_id: int, limit: int = 100):
    store = _brain_or_503()
    chunks = await _run_brain_step(
        "Source chunk list",
        store.list_chunks,
        source_id=source_id,
        limit=limit,
    )
    return {"chunks": chunks}


def _clean_brain_search_query(value: str) -> str:
    query = (value or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="Search query cannot be blank")
    return query


@app.get("/api/brain/search")
async def search_brain(
    q: str = Query(min_length=1, max_length=4000),
    limit: int = Query(default=50, ge=1, le=100),
    entity_type: str | None = None,
):
    store = _brain_or_503()
    query = _clean_brain_search_query(q)
    started_at = time.perf_counter()
    results = await _run_brain_step(
        "Keyword brain search",
        store.search,
        query=query,
        limit=limit,
        entity_type=entity_type,
    )
    results = await _attach_source_references(store, results)
    counts = await _run_brain_step("Brain counts", store.counts)
    return {
        "query": query,
        "results": results,
        "counts": counts,
        "timings": {
            "totalMs": round((time.perf_counter() - started_at) * 1000, 1),
        },
    }


@app.post("/api/brain/embeddings/backfill")
async def backfill_brain_embeddings(payload: BrainEmbeddingBackfillRequest):
    store = _brain_or_503()
    client = _gemini_or_503()
    chunks = await _run_brain_step(
        "Embedding chunk list",
        store.list_chunks_for_embedding,
        limit=payload.limit,
        force=payload.force,
    )
    indexed = []
    errors = []

    for chunk in chunks:
        try:
            embedding = await _run_brain_step(
                "Gemini embedding",
                client.embed_text,
                chunk["body"],
                task_type="RETRIEVAL_DOCUMENT",
                timeout=float(getattr(client, "embedding_timeout", 15.0)) + 5.0,
            )
            await _run_brain_step(
                "Store embedding",
                store.update_chunk_embedding,
                int(chunk["id"]),
                embedding_model=client.embedding_model,
                embedding=embedding,
            )
            indexed.append({
                "id": chunk["id"],
                "title": chunk["title"],
                "dimensions": len(embedding),
            })
        except Exception as e:
            errors.append({
                "id": chunk.get("id"),
                "title": chunk.get("title"),
                "error": str(e),
            })
    counts = await _run_brain_step("Brain counts", store.counts)
    embeddings = await _run_brain_step(
        "Embedding coverage",
        store.embedding_stats if hasattr(store, "embedding_stats") else lambda: {},
    )

    return {
        "model": client.embedding_model,
        "requested": len(chunks),
        "embedded": len(indexed),
        "errors": errors,
        "items": indexed,
        "counts": counts,
        "embeddings": embeddings,
    }


@app.post("/api/brain/embeddings/backfill/start")
async def start_brain_embedding_backfill(payload: BrainEmbeddingBackfillStartRequest):
    _brain_or_503()
    _gemini_or_503()
    if embedding_backfill_job.get("running"):
        return _public_embedding_job()

    asyncio.create_task(_run_embedding_backfill_job(
        batch_size=payload.batchSize,
        max_chunks=payload.maxChunks,
        force=payload.force,
    ))
    return {
        **_public_embedding_job(),
        "message": "Embedding job queued.",
    }


@app.get("/api/brain/search/semantic")
async def semantic_brain_search(
    q: str = Query(min_length=1, max_length=4000),
    limit: int = Query(default=10, ge=1, le=50),
):
    store = _brain_or_503()
    client = _gemini_or_503()
    query = _clean_brain_search_query(q)
    started_at = time.perf_counter()
    try:
        query_embedding = await _run_brain_step(
            "Semantic embedding",
            client.embed_text,
            query,
            task_type="RETRIEVAL_QUERY",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=_semantic_error_detail(e))

    embedding_ms = round((time.perf_counter() - started_at) * 1000, 1)
    search_started_at = time.perf_counter()
    try:
        raw_chunks = await _run_brain_step(
            "Supabase vector search",
            store.semantic_search_chunks,
            query_embedding,
            limit=limit,
        ) or []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Supabase vector search failed.",
                "reason": _clean_public_error(e),
                "action": "Check pgvector schema, embedding dimensions, and database availability.",
            },
        )
    chunks = _filter_semantic_results(raw_chunks)
    search_ms = round((time.perf_counter() - search_started_at) * 1000, 1)
    counts = await _run_brain_step("Brain counts", store.counts)
    results = await _attach_source_references(store, [
        {
            "entityType": "chunk",
            "entityId": int(chunk["id"]),
            "title": chunk["title"],
            "body": chunk["body"],
            "tags": chunk.get("tags", []),
            "rank": chunk.get("score"),
            "score": chunk.get("score"),
            "sourceId": chunk.get("sourceId"),
            "ordinal": chunk.get("ordinal"),
            "pageStart": chunk.get("pageStart"),
            "pageEnd": chunk.get("pageEnd"),
        }
        for chunk in chunks
    ])
    return {
        "query": query,
        "model": client.embedding_model,
        "results": results,
        "rejectedWeakMatches": len(raw_chunks) - len(chunks),
        "counts": counts,
        "timings": {
            "embeddingMs": embedding_ms,
            "searchMs": search_ms,
            "totalMs": round((time.perf_counter() - started_at) * 1000, 1),
        },
    }


def _format_context_block(items: list[dict], *, max_chars: int = 1000) -> str:
    blocks = []
    for index, item in enumerate(items, start=1):
        title = item.get("title", "Untitled")
        kind = item.get("entityType") or item.get("kind") or "chunk"
        body = str(item.get("body", "")).strip()[:max_chars]
        score = item.get("score")
        score_text = f" | score={score:.3f}" if isinstance(score, (int, float)) else ""
        blocks.append(f"[{index}] {kind}: {title}{score_text}\n{body}")
    return "\n\n".join(blocks)


def _merge_retrieval_results(
    semantic_results: list[dict[str, Any]],
    keyword_results: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Fuse semantic and lexical rankings without comparing incompatible scores.

    pgvector cosine scores and full-text ranks have different scales. Reciprocal
    rank fusion only relies on position, preserves strong exact matches, and
    gives a useful boost to evidence surfaced by both retrieval methods.
    """
    fused: dict[tuple[str, int], dict[str, Any]] = {}
    rank_constant = 60.0

    for channel, results in (("semantic", semantic_results), ("keyword", keyword_results)):
        for rank, item in enumerate(results, start=1):
            entity_type = str(item.get("entityType") or "chunk")
            entity_id = item.get("id") or item.get("entityId")
            if entity_id is None:
                continue
            try:
                key = (entity_type, int(entity_id))
            except (TypeError, ValueError):
                continue

            existing = fused.get(key)
            if existing is None:
                existing = dict(item)
                existing["entityType"] = entity_type
                existing["entityId"] = key[1]
                existing["retrievalSignals"] = {}
                existing["hybridScore"] = 0.0
                fused[key] = existing

            signals = existing["retrievalSignals"]
            signals[f"{channel}Rank"] = rank
            existing["hybridScore"] += 1.0 / (rank_constant + rank)

            # Keep the semantic score visible for diagnostics when available.
            if channel == "semantic" and item.get("score") is not None:
                existing["score"] = item.get("score")

    ordered = sorted(
        fused.values(),
        key=lambda item: (
            float(item.get("hybridScore") or 0),
            int("semanticRank" in item.get("retrievalSignals", {}))
            + int("keywordRank" in item.get("retrievalSignals", {})),
        ),
        reverse=True,
    )
    return ordered[: max(1, min(int(limit), 20))]


def _filter_semantic_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only semantic matches that clear the configured relevance floor.

    A nearest-neighbour query always has an answer, including for nonsense and
    off-topic text. Weak matches are excluded from the model context; keyword
    retrieval remains available for precise but low-similarity terms.
    """
    accepted: list[dict[str, Any]] = []
    for item in results:
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(score) and score >= SEMANTIC_MIN_SCORE:
            accepted.append(item)
    return accepted


def _context_excerpt(item: dict[str, Any], *, max_chars: int = 360) -> str:
    body = re.sub(r"\s+", " ", str(item.get("body") or "")).strip()
    if len(body) <= max_chars:
        return body
    return body[: max_chars - 3].rstrip() + "..."


def _format_retrieval_fallback_answer(
    *,
    error: Exception | str,
    memory_results: list[dict[str, Any]],
    context_items: list[dict[str, Any]],
    deep_sources: list[dict[str, Any]],
) -> str:
    reason = _public_exception_reason(error) or "Gemini did not return an answer in time."
    lines = [
        "Gemini timed out before writing the final analysis, but I did retrieve brain context.",
        "",
        "1. Retrieved evidence",
    ]

    evidence_lines: list[str] = []
    for item in context_items[:4]:
        source = item.get("source") or {}
        source_title = source.get("title") or item.get("title") or "Untitled source"
        excerpt = _context_excerpt(item)
        if excerpt:
            evidence_lines.append(f"- {source_title}: {excerpt}")

    if not evidence_lines:
        for source_item in deep_sources[:2]:
            source = source_item.get("source") or {}
            source_title = source.get("title") or f"Source {source_item.get('sourceId')}"
            first_chunk = next((chunk for chunk in source_item.get("chunks", []) if chunk.get("body")), {})
            excerpt = _context_excerpt(first_chunk)
            if excerpt:
                evidence_lines.append(f"- {source_title}: {excerpt}")

    if evidence_lines:
        lines.extend(evidence_lines)
    else:
        lines.append("- No source excerpt was available from the retrieval step.")

    if memory_results:
        lines.extend(["", "2. Matching memory"])
        for memory in memory_results[:2]:
            excerpt = _context_excerpt(memory, max_chars=260)
            lines.append(f"- {memory.get('title') or 'Memory'}: {excerpt}")

    lines.extend([
        "",
        "3. What happened",
        f"- {reason}",
        "- Retry the same question; if Google is slow again, the retrieved sources below are still the right place to inspect.",
    ])
    return "\n".join(lines)


def _source_id_from_context(item: dict[str, Any]) -> int | None:
    value = item.get("sourceId") or item.get("source_id")
    if value is None and item.get("entityType") == "source":
        value = item.get("entityId") or item.get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _expand_semantic_hits_into_sources(
    store: Any,
    hits: list[dict[str, Any]],
    *,
    max_sources: int = 2,
    window: int = 2,
    max_source_chunks: int = 24,
    max_chunks_per_source: int = 4,
    max_chars_per_chunk: int = 650,
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    source_ids: list[int] = []
    hit_ordinals: dict[int, list[int]] = {}

    for item in hits:
        source_id = _source_id_from_context(item)
        if source_id is None:
            continue
        if source_id not in source_ids:
            if len(source_ids) >= max_sources:
                continue
            source_ids.append(source_id)
        ordinal = item.get("ordinal")
        if isinstance(ordinal, int):
            hit_ordinals.setdefault(source_id, []).append(ordinal)

    for source_id in source_ids:
        source = store.get_source(source_id) if hasattr(store, "get_source") else None
        chunks = store.list_chunks(source_id=source_id, limit=max_source_chunks)
        if not chunks:
            continue

        ordinals = hit_ordinals.get(source_id) or [int(chunks[0].get("ordinal") or 0)]
        selected: list[dict[str, Any]] = []
        selected_ids: set[int] = set()

        for ordinal in ordinals:
            for chunk in chunks:
                chunk_ordinal = int(chunk.get("ordinal") or 0)
                chunk_id = int(chunk.get("id"))
                if abs(chunk_ordinal - ordinal) <= window and chunk_id not in selected_ids:
                    selected.append(chunk)
                    selected_ids.add(chunk_id)
                if len(selected) >= max_chunks_per_source:
                    break
            if len(selected) >= max_chunks_per_source:
                break

        if not selected:
            selected = chunks[:max_chunks_per_source]

        source_summary = None
        if source:
            source_summary = {
                **(_public_source_reference(source) or {}),
                "author": source.get("author"),
                "sourceDate": source.get("sourceDate"),
                "metadata": source.get("metadata", {}),
            }

        expanded.append({
            "source": source_summary,
            "sourceId": source_id,
            "hitOrdinals": ordinals,
            "chunks": selected[:max_chunks_per_source],
            "maxCharsPerChunk": max_chars_per_chunk,
        })

    return expanded


def _format_deep_source_context(items: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(items, start=1):
        source = item.get("source") or {}
        source_id = item.get("sourceId")
        source_title = source.get("title") or f"Source {source_id}"
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        link = metadata.get("webViewLink") or metadata.get("driveWebViewLink") or metadata.get("driveFileId")
        hit_ordinals = ", ".join(str(value) for value in item.get("hitOrdinals", []))
        header = f"[File {index}] {source_title} | source_id={source_id}"
        if hit_ordinals:
            header += f" | semantic_hit_chunks={hit_ordinals}"
        if link:
            header += f" | link={link}"

        chunk_lines = []
        for chunk in item.get("chunks", []):
            ordinal = chunk.get("ordinal")
            title = chunk.get("title", "Chunk")
            body = str(chunk.get("body", "")).strip()[: int(item.get("maxCharsPerChunk") or 900)]
            chunk_lines.append(f"chunk {ordinal}: {title}\n{body}")

        blocks.append(f"{header}\n" + "\n\n".join(chunk_lines))
    return "\n\n---\n\n".join(blocks)


def _format_conversation_history(turns: list[BrainConversationTurn], *, max_turns: int = 8, max_chars: int = 3500) -> str:
    lines: list[str] = []
    remaining = max_chars
    for turn in turns[-max_turns:]:
        role = "User" if turn.role.lower() == "user" else "Assistant"
        content = re.sub(r"\s+", " ", turn.content).strip()
        if not content:
            continue
        snippet = content[: min(remaining, 700)]
        lines.append(f"{role}: {snippet}")
        remaining -= len(snippet)
        if remaining <= 0:
            break
    return "\n".join(lines)


def _finite_number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _signed_position_return(value: Any, side: str) -> float | None:
    result = _finite_number(value)
    if result is None:
        return None
    return result if side == "Long" else -result


_MARKET_SESSION_SCHEDULES = {
    "USA": ("America/New_York", 16, 15),
    "CAN": ("America/Toronto", 16, 15),
    "POL": ("Europe/Warsaw", 17, 15),
    "BEL": ("Europe/Brussels", 17, 45),
    "DNK": ("Europe/Copenhagen", 17, 15),
    "FIN": ("Europe/Helsinki", 18, 45),
    "JPN": ("Asia/Tokyo", 15, 30),
}


def _market_session_is_complete(timestamp: Any, country: str) -> bool:
    """Conservatively identify whether a daily bar's volume can be treated as complete."""
    if timestamp is None:
        return False
    schedule = _MARKET_SESSION_SCHEDULES.get(country)
    if schedule is None:
        return False
    timezone_name, close_hour, close_minute = schedule
    try:
        now_local = datetime.now(ZoneInfo(timezone_name))
        session_date = pd.Timestamp(timestamp).date()
    except (TypeError, ValueError, KeyError):
        return False
    if session_date < now_local.date():
        return True
    if session_date > now_local.date():
        return False
    return (now_local.hour, now_local.minute) >= (close_hour, close_minute)


_MARKET_DATA_INTENT_PATTERNS = {
    "price_momentum_or_volume": r"\b(momentum|volume|technical|price action|relative strength|moving average|trend|weakness|breakout|selloff|liquidity)\b",
    "live_performance": r"\b(ytd|return|performance|contribution|p&l|pnl|profit|loss|financing|alpha|sharpe|sortino|batting average)\b",
    "live_risk": r"\b(beta|volatility|drawdown|var|cvar|portfolio risk|book risk|risk attribution|stress test|correlation|concentration|exposure|leverage)\b",
    "current_book_state": r"\b(current weight|drifted weight|live weight|today(?:'s)? weight|current portfolio|current book|latest portfolio)\b",
    "portfolio_action": r"\b(sell|reduce|trim|exit|cover|rebalance|resize|increase|decrease|add to|position sizing)\b",
    "explicit_live_data": r"\b(live data|market data|yahoo|latest price|current price|today|right now)\b",
}
_NO_MARKET_DATA_PATTERN = re.compile(
    r"\b(without (?:live |current )?market data|documents? only|research only|drive only|do not (?:fetch|use) market data)\b",
    re.IGNORECASE,
)


def _brain_market_data_intent(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if _NO_MARKET_DATA_PATTERN.search(cleaned):
        return {"requested": False, "reasons": [], "explicitlyDisabled": True}
    reasons = [
        reason
        for reason, pattern in _MARKET_DATA_INTENT_PATTERNS.items()
        if re.search(pattern, cleaned, flags=re.IGNORECASE)
    ]
    return {"requested": bool(reasons), "reasons": reasons, "explicitlyDisabled": False}


def _build_brain_portfolio_outline(portfolio: str = "main") -> dict[str, Any]:
    portfolio_config = risk.get_effective_portfolio_config(portfolio) if risk else {}
    positions = []
    target_long = 0.0
    target_short = 0.0
    for ticker, config in portfolio_config.items():
        side = config.get("type", "Long")
        target_weight = _finite_number(config.get("weight")) or 0.0
        if side == "Long":
            target_long += target_weight
        else:
            target_short += target_weight
        positions.append({
            "ticker": ticker,
            "side": side,
            "targetWeight": target_weight,
            "currentWeight": None,
            "sector": config.get("sector", "Unknown"),
            "country": config.get("country", "Unknown"),
            "currency": config.get("currency", "USD"),
        })
    positions.sort(key=lambda item: item["targetWeight"], reverse=True)
    return {
        "portfolio": portfolio,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataAsOf": None,
        "fresh": None,
        "marketDataRequested": False,
        "marketDataAvailable": False,
        "source": "Effective dated portfolio configuration; no market-data fetch",
        "benchmark": getattr(risk, "BENCHMARK", "SPY") if risk else "SPY",
        "positionCount": len(positions),
        "exposure": {
            "target": {
                "long": target_long,
                "short": target_short,
                "gross": target_long + target_short,
                "net": target_long - target_short,
            },
            "currentDrifted": None,
        },
        "positions": positions,
    }


def _position_technical_diagnostic(position: dict[str, Any]) -> dict[str, Any]:
    side = position.get("side", "Long")
    returns = position.get("positionMomentum", {})
    volume = position.get("volume", {})
    rs_position = _signed_position_return(position.get("relativeStrength1m"), side)
    acceleration_position = _signed_position_return(position.get("momentumAcceleration1m"), side)
    price_vs_50d = _finite_number(position.get("priceVs50d"))
    price_vs_200d = _finite_number(position.get("priceVs200d"))
    adverse_50d = price_vs_50d is not None and (price_vs_50d < 0 if side == "Long" else price_vs_50d > 0)
    adverse_200d = price_vs_200d is not None and (price_vs_200d < 0 if side == "Long" else price_vs_200d > 0)

    signals: list[str] = []
    if (_finite_number(returns.get("1m")) or 0) < -0.05:
        signals.append("adverse_1m_momentum")
    if (_finite_number(returns.get("3m")) or 0) < -0.10:
        signals.append("adverse_3m_momentum")
    if (_finite_number(returns.get("12mEx1m")) or 0) < 0:
        signals.append("adverse_12_minus_1_momentum")
    if adverse_50d:
        signals.append("adverse_50d_trend")
    if adverse_200d:
        signals.append("adverse_200d_trend")
    if rs_position is not None and rs_position < -0.03:
        signals.append("adverse_relative_strength")
    if acceleration_position is not None and acceleration_position < -0.05:
        signals.append("negative_momentum_acceleration")

    adverse_volume_ratio = _finite_number(volume.get("adverseVolumeRatio20d"))
    volume_pressure = _finite_number(volume.get("positionVolumePressure20d"))
    volume_5d_vs_20d = _finite_number(volume.get("volume5dVs20d"))
    volume_20d_vs_63d = _finite_number(volume.get("volume20dVs63d"))
    volume_zscore = _finite_number(volume.get("latestCompletedVolumeZScore"))
    adverse_days_heavier = adverse_volume_ratio is not None and adverse_volume_ratio >= 1.15
    negative_volume_pressure = volume_pressure is not None and volume_pressure <= -0.10
    expanding_volume = any(value is not None and value >= threshold for value, threshold in (
        (volume_5d_vs_20d, 1.10),
        (volume_20d_vs_63d, 1.10),
        (volume_zscore, 1.0),
    ))
    volume_confirms_weakness = adverse_days_heavier and negative_volume_pressure and expanding_volume
    signal_count = len(signals)
    if signal_count >= 5 and volume_confirms_weakness:
        status = "high_conviction_technical_review"
        action = "review_reduce_or_exit" if side == "Long" else "review_reduce_or_cover"
    elif signal_count >= 5:
        status = "momentum_weakness_not_confirmed_by_volume"
        action = "watch_for_volume_confirmation"
    elif signal_count >= 3 and volume_confirms_weakness:
        status = "technical_review"
        action = "review_position"
    elif signal_count >= 3:
        status = "technical_watch"
        action = "watch"
    else:
        status = "no_broad_technical_weakness"
        action = "no_technical_action"

    volume_observations = int(volume.get("observations") or 0)
    momentum_observations_sufficient = returns.get("6m") is not None
    evidence_quality = "high" if volume_observations >= 63 and momentum_observations_sufficient else "limited"
    return {
        "screeningStatus": status,
        "technicalAction": action,
        "weaknessSignalCount": signal_count,
        "weaknessSignals": signals,
        "volumeConfirmsWeakness": volume_confirms_weakness,
        "positionRelativeStrength1m": rs_position,
        "positionMomentumAcceleration1m": acceleration_position,
        "evidenceQuality": evidence_quality,
        "guardrail": "Technical screen only; require thesis, valuation, catalyst, tax, and liquidity review before trading.",
    }


def _build_brain_portfolio_context(
    metrics_payload: dict[str, Any] | None,
    *,
    portfolio: str = "main",
    cache_timestamp: float | None = None,
) -> dict[str, Any]:
    """Build the compact, authoritative live-book snapshot supplied to the Brain."""
    payload = metrics_payload if isinstance(metrics_payload, dict) else {}
    portfolio_config = risk.get_effective_portfolio_config(portfolio) if risk else {}
    return_rows = {
        str(row.get("ticker")): row
        for row in payload.get("periodicReturns", [])
        if isinstance(row, dict) and row.get("ticker")
    }
    relative_strength = {
        str(row.get("ticker")): row
        for row in ((payload.get("momentum") or {}).get("all_rs") or [])
        if isinstance(row, dict) and row.get("ticker")
    }

    positions: list[dict[str, Any]] = []
    for ticker, config in portfolio_config.items():
        row = return_rows.get(ticker, {})
        side = config.get("type", "Long")
        target_weight = _finite_number(config.get("weight")) or 0.0
        current_weight = _finite_number(row.get("currentWeight"))
        if current_weight is None:
            current_weight = target_weight
        rs = relative_strength.get(ticker, {})
        raw_ytd_return = _finite_number(row.get("ytd"))
        raw_momentum_acceleration = _finite_number(row.get("momentumAcceleration1m"))
        position = {
            "ticker": ticker,
            "side": side,
            "targetWeight": target_weight,
            "currentWeight": current_weight,
            "signedCurrentWeight": current_weight if side == "Long" else -current_weight,
            "sector": config.get("sector", "Unknown"),
            "country": config.get("country", "Unknown"),
            "currency": config.get("currency", "USD"),
            "lastPrice": _finite_number(row.get("lastPrice")),
            "returns": {
                "1d": _finite_number(row.get("r1d")),
                "1w": _finite_number(row.get("r7d")),
                "1m": _finite_number(row.get("r1m")),
                "3m": _finite_number(row.get("r3m")),
                "6m": _finite_number(row.get("r6m")),
                "12m": _finite_number(row.get("r12m")),
                "12mEx1m": _finite_number(row.get("r12mEx1m")),
                "ytd": raw_ytd_return,
            },
            "positionMomentum": {
                "1m": _signed_position_return(row.get("r1m"), side),
                "3m": _signed_position_return(row.get("r3m"), side),
                "6m": _signed_position_return(row.get("r6m"), side),
                "12mEx1m": _signed_position_return(row.get("r12mEx1m"), side),
                "calendarYtdSecurity": _signed_position_return(raw_ytd_return, side),
            },
            "prior1mReturn": _finite_number(row.get("prior1m")),
            "momentumAcceleration1m": raw_momentum_acceleration,
            "relativeStrength1m": _finite_number(rs.get("rs")),
            "relativeStrengthBenchmark": rs.get("bmk"),
            "priceVs50d": _finite_number(row.get("priceVs50d")),
            "priceVs200d": _finite_number(row.get("priceVs200d")),
            "drawdown52w": _finite_number(row.get("drawdown52w")),
            "trendSignal": row.get("trendSignal"),
            "annualizedVolatility": _finite_number(row.get("volatility")),
            "volumeVsYtdAverage": _finite_number(row.get("volumeIndicator")),
            "volume": {
                "dataThrough": row.get("volumeDataThrough"),
                "latestSessionVolume": _finite_number(row.get("latestSessionVolume")),
                "latestSessionComplete": bool(row.get("latestSessionVolumeComplete")),
                "observations": int(row.get("volumeObservations") or 0),
                "volume5dVs20d": _finite_number(row.get("volume5dVs20d")),
                "volume20dVs63d": _finite_number(row.get("volume20dVs63d")),
                "latestVolumeVs20d": _finite_number(row.get("latestVolumeVs20d")),
                "latestCompletedVolumeZScore": _finite_number(row.get("latestCompletedVolumeZScore")),
                "averageDollarVolume20d": _finite_number(row.get("averageDollarVolume20d")),
                "downUpVolumeRatio20d": _finite_number(row.get("downUpVolumeRatio20d")),
                "adverseVolumeRatio20d": _finite_number(row.get("adverseVolumeRatio20d")),
                "obvPressure20d": _finite_number(row.get("obvPressure20d")),
                "positionVolumePressure20d": _finite_number(row.get("positionVolumePressure20d")),
                "priceVolumeCorrelation20d": _finite_number(row.get("priceVolumeCorrelation20d")),
                "positionPriceVolumeCorrelation20d": _finite_number(row.get("positionPriceVolumeCorrelation20d")),
            },
            "ytdContribution": _finite_number(row.get("ytdContribution")),
            "sinceRebalanceContribution": _finite_number(row.get("sinceRebalanceContribution")),
            "sinceRebalanceStartDate": row.get("sinceRebalanceStartDate"),
        }
        position["technical"] = _position_technical_diagnostic(position)
        positions.append(position)

    positions.sort(key=lambda item: item["currentWeight"], reverse=True)
    current_long = sum(item["currentWeight"] for item in positions if item["side"] == "Long")
    current_short = sum(item["currentWeight"] for item in positions if item["side"] == "Short")
    target_long = sum(item["targetWeight"] for item in positions if item["side"] == "Long")
    target_short = sum(item["targetWeight"] for item in positions if item["side"] == "Short")
    leverage = payload.get("leverage") if isinstance(payload.get("leverage"), dict) else {}
    target_long = _finite_number(leverage.get("Long_Exp")) or target_long
    target_short = _finite_number(leverage.get("Short_Exp")) or target_short

    ytd_history = payload.get("ytdHistory") if isinstance(payload.get("ytdHistory"), list) else []
    data_as_of = ytd_history[-1].get("date") if ytd_history and isinstance(ytd_history[-1], dict) else None
    cache_age = max(0.0, time.time() - cache_timestamp) if cache_timestamp else None
    market_data_age_days = None
    if data_as_of:
        try:
            market_data_age_days = (datetime.now().astimezone().date() - datetime.strptime(data_as_of, "%Y-%m-%d").date()).days
        except (TypeError, ValueError):
            market_data_age_days = None
    vitals = payload.get("vitals") if isinstance(payload.get("vitals"), dict) else {}
    ytd_net = _finite_number(vitals.get("ytdReturn"))
    benchmark_ytd = _finite_number(vitals.get("benchmarkYtd"))
    top_five_weight = sum(item["currentWeight"] for item in positions[:5])
    current_gross = current_long + current_short

    momentum_ranked = sorted(
        (item for item in positions if item["positionMomentum"]["3m"] is not None),
        key=lambda item: item["positionMomentum"]["3m"],
        reverse=True,
    )
    momentum = payload.get("momentum") if isinstance(payload.get("momentum"), dict) else {}

    def ranked_values(field: str, *, nested: str | None = None, descending: bool = True, limit: int = 5):
        ranked = []
        for item in positions:
            container = item.get(nested, {}) if nested else item
            value = _finite_number(container.get(field)) if isinstance(container, dict) else None
            if value is not None:
                ranked.append({"ticker": item["ticker"], "side": item["side"], "value": value})
        ranked.sort(key=lambda item: item["value"], reverse=descending)
        return ranked[:limit]

    technical_ranked = sorted(
        positions,
        key=lambda item: (
            item.get("technical", {}).get("weaknessSignalCount", 0),
            bool(item.get("technical", {}).get("volumeConfirmsWeakness")),
            -(_finite_number(item.get("positionMomentum", {}).get("3m")) or 0),
        ),
        reverse=True,
    )
    partial_volume_tickers = [
        item["ticker"]
        for item in positions
        if item.get("volume", {}).get("latestSessionVolume") is not None
        and not item.get("volume", {}).get("latestSessionComplete")
    ]

    return {
        "portfolio": portfolio,
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataAsOf": data_as_of,
        "marketDataAgeDays": market_data_age_days,
        "cacheAgeSeconds": round(cache_age, 1) if cache_age is not None else None,
        "fresh": bool(
            data_as_of
            and market_data_age_days is not None
            and -1 <= market_data_age_days <= 4
            and cache_age is not None
            and cache_age <= CACHE_TTL + 5
        ),
        "marketDataRequested": True,
        "marketDataAvailable": bool(return_rows),
        "source": "Shared dashboard risk engine using Yahoo Finance adjusted prices",
        "benchmark": getattr(risk, "BENCHMARK", "SPY") if risk else "SPY",
        "positionCount": len(positions),
        "exposure": {
            "target": {
                "long": target_long,
                "short": target_short,
                "gross": target_long + target_short,
                "net": target_long - target_short,
            },
            "currentDrifted": {
                "long": current_long,
                "short": current_short,
                "gross": current_gross,
                "net": current_long - current_short,
            },
        },
        "performance": {
            "ytdNet": ytd_net,
            "ytdGrossBeforeFinancing": _finite_number(vitals.get("ytdReturnGross")),
            "benchmarkYtd": benchmark_ytd,
            "activeReturnYtd": ytd_net - benchmark_ytd if ytd_net is not None and benchmark_ytd is not None else None,
            "annualizedJensenAlpha": _finite_number(vitals.get("ytdAlpha")),
            "compoundedCapmAlphaYtd": _finite_number(vitals.get("ytdAlphaRaw")),
            "betaYtd": _finite_number(vitals.get("ytdBeta")),
            "volatilityYtd": _finite_number(vitals.get("ytdVol")),
            "maxDrawdownYtd": _finite_number(vitals.get("ytdMaxDrawdown")),
            "financingCostYtd": _finite_number(vitals.get("ytdFinancingCost")),
        },
        "performanceRankings": {
            "realizedYtdContributionLeaders": ranked_values("ytdContribution", descending=True),
            "realizedYtdContributionLaggards": ranked_values("ytdContribution", descending=False),
            "sinceRebalanceContributionLeaders": ranked_values("sinceRebalanceContribution", descending=True),
            "sinceRebalanceContributionLaggards": ranked_values("sinceRebalanceContribution", descending=False),
            "calendarYtdSecurityReturnLeaders": ranked_values("ytd", nested="returns", descending=True),
            "calendarYtdSecurityReturnLaggards": ranked_values("ytd", nested="returns", descending=False),
            "sideAdjustedCalendarYtdLeaders": ranked_values("calendarYtdSecurity", nested="positionMomentum", descending=True),
            "sideAdjustedCalendarYtdLaggards": ranked_values("calendarYtdSecurity", nested="positionMomentum", descending=False),
            "methodology": {
                "realizedYtdContribution": "Dated-position ledger contribution actually earned during each holding period; use this for portfolio winners and detractors.",
                "calendarYtdSecurityReturn": "Underlying security adjusted-price return since year start, regardless of when the portfolio owned it.",
                "sideAdjustedCalendarYtd": "Calendar-YTD security return with shorts sign-flipped; hypothetical position direction, not realized contribution.",
                "sinceRebalanceContribution": "Realized contribution since the latest dated rebalance only.",
            },
        },
        "concentration": {
            "topFiveAbsoluteWeight": top_five_weight,
            "topFiveShareOfGross": top_five_weight / current_gross if current_gross else None,
            "largestPositions": [
                {"ticker": item["ticker"], "side": item["side"], "currentWeight": item["currentWeight"]}
                for item in positions[:5]
            ],
        },
        "momentum": {
            "leaders3mPositionAdjusted": [
                {"ticker": item["ticker"], "side": item["side"], "value": item["positionMomentum"]["3m"]}
                for item in momentum_ranked[:5]
            ],
            "laggards3mPositionAdjusted": [
                {"ticker": item["ticker"], "side": item["side"], "value": item["positionMomentum"]["3m"]}
                for item in reversed(momentum_ranked[-5:])
            ],
            "correlationSurges": momentum.get("corr_surges") or [],
            "methodology": momentum.get("methodology") or {
                "source": "Yahoo Finance adjusted close via yfinance",
                "priceMomentum": "Adjusted-price total return: P(t) / P(t-n sessions) - 1",
            },
        },
        "volumeMomentumScreen": {
            "reviewCandidates": [
                {
                    "ticker": item["ticker"],
                    "side": item["side"],
                    "currentWeight": item["currentWeight"],
                    **item.get("technical", {}),
                }
                for item in technical_ranked[:10]
            ],
            "partialSessionVolumeExcludedFor": partial_volume_tickers,
            "methodology": {
                "price": "Yahoo Finance adjusted prices converted to USD for cross-market comparability.",
                "momentum": "1m, 3m, 6m and 12-minus-1m total returns; shorts are sign-flipped only for position-health analysis.",
                "volume": "Completed sessions only: 5d/20d and 20d/63d relative volume, latest completed-volume z-score, 20d adverse/favorable-day volume ratio, normalized OBV pressure, and 20d average USD dollar volume.",
                "screen": "Seven transparent weakness flags. A trade is never recommended from the technical screen alone.",
            },
        },
        "risk": {
            "topContributors": [
                {
                    "ticker": item.get("ticker"),
                    "percentOfRisk": _finite_number(item.get("pctRisk")),
                    "marginalContribution": _finite_number(item.get("mctr")),
                    "weight": _finite_number(item.get("weight")),
                }
                for item in (payload.get("riskAttribution") or [])[:10]
                if isinstance(item, dict)
            ],
            "stressTests": [
                {
                    "scenario": item.get("scenario"),
                    "alphaNeutralImpact": _finite_number(item.get("impact")),
                    "linearImpact": _finite_number(item.get("linearImpact")),
                    "marketMove": _finite_number(item.get("marketMove")),
                }
                for item in (payload.get("stressTests") or [])
                if isinstance(item, dict)
            ],
        },
        "positions": positions,
    }


def _format_brain_portfolio_context(context: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        number = _finite_number(value)
        return "n/a" if number is None else f"{number:+.1%}"

    def ratio(value: Any) -> str:
        number = _finite_number(value)
        return "n/a" if number is None else f"{number:.2f}x"

    def dollars(value: Any) -> str:
        number = _finite_number(value)
        if number is None:
            return "n/a"
        if abs(number) >= 1_000_000_000:
            return f"${number / 1_000_000_000:.1f}bn"
        if abs(number) >= 1_000_000:
            return f"${number / 1_000_000:.1f}m"
        return f"${number:,.0f}"

    def sigma(value: Any) -> str:
        number = _finite_number(value)
        return "n/a" if number is None else f"{number:+.2f} sigma"

    exposure = context.get("exposure", {})
    target = exposure.get("target", {})
    if not context.get("marketDataAvailable"):
        lines = [
            f"Portfolio={context.get('portfolio', 'main')} | configuration-only outline; live market data was not requested for this question.",
            f"Target exposure: long {pct(target.get('long'))}, short {pct(target.get('short'))}, "
            f"gross {pct(target.get('gross'))}, net {pct(target.get('net'))}.",
            "No current prices, drifted weights, momentum, volume, performance, or risk metrics are present. Do not infer them.",
            "ACTIVE TARGET POSITIONS:",
        ]
        for item in context.get("positions", []):
            lines.append(
                f"{item.get('ticker')} {item.get('side')} | target {pct(item.get('targetWeight'))} | "
                f"{item.get('sector', 'Unknown')} | {item.get('country', 'Unknown')} | {item.get('currency', 'USD')}"
            )
        return "\n".join(lines)

    current = exposure.get("currentDrifted", {})
    performance = context.get("performance", {})
    concentration = context.get("concentration", {})
    lines = [
        f"Portfolio={context.get('portfolio', 'main')} | market data as of {context.get('dataAsOf') or 'unknown'} "
        f"(age {context.get('marketDataAgeDays') if context.get('marketDataAgeDays') is not None else 'unknown'} days) | "
        f"snapshot cache age={context.get('cacheAgeSeconds') if context.get('cacheAgeSeconds') is not None else 'unknown'}s | "
        f"fresh={context.get('fresh', False)}",
        f"Target exposure: long {pct(target.get('long'))}, short {pct(target.get('short'))}, "
        f"gross {pct(target.get('gross'))}, net {pct(target.get('net'))}.",
        f"Current drifted exposure: long {pct(current.get('long'))}, short {pct(current.get('short'))}, "
        f"gross {pct(current.get('gross'))}, net {pct(current.get('net'))}.",
        f"YTD: net {pct(performance.get('ytdNet'))}, gross before financing {pct(performance.get('ytdGrossBeforeFinancing'))}, "
        f"benchmark {pct(performance.get('benchmarkYtd'))}, active return {pct(performance.get('activeReturnYtd'))}, "
        f"compounded CAPM alpha {pct(performance.get('compoundedCapmAlphaYtd'))}, annualized Jensen alpha {pct(performance.get('annualizedJensenAlpha'))}, "
        f"beta {(_finite_number(performance.get('betaYtd')) or 0):.2f}, vol {pct(performance.get('volatilityYtd'))}, "
        f"max drawdown {pct(performance.get('maxDrawdownYtd'))}, financing {pct(performance.get('financingCostYtd'))}.",
        f"Concentration: top five absolute current position weights total {pct(concentration.get('topFiveAbsoluteWeight'))} of NAV/equity. "
        f"That is {pct(concentration.get('topFiveShareOfGross'))} of the portfolio's current gross exposure; do not confuse these two denominators.",
        "Position convention: underlying returns are security returns; position momentum flips the sign for shorts. "
        "Higher positive position momentum helps the book; lower negative position momentum hurts it. Current weight is absolute exposure versus NAV, "
        "drifted with performance, and distinct from target weight. Prices are adjusted and USD-converted for comparability.",
    ]
    momentum_context = context.get("momentum", {})
    leaders = momentum_context.get("leaders3mPositionAdjusted", [])
    laggards = momentum_context.get("laggards3mPositionAdjusted", [])
    if leaders:
        lines.append("Pre-ranked 3m position-adjusted leaders (helping the book): " + ", ".join(
            f"{item.get('ticker')} {item.get('side')} {pct(item.get('value'))}"
            for item in leaders
        ) + ".")
    if laggards:
        lines.append("Pre-ranked 3m position-adjusted laggards (hurting the book): " + ", ".join(
            f"{item.get('ticker')} {item.get('side')} {pct(item.get('value'))}"
            for item in laggards
        ) + ".")
    performance_rankings = context.get("performanceRankings", {})
    ranking_specs = (
        ("Realized YTD contribution leaders", "realizedYtdContributionLeaders"),
        ("Realized YTD contribution laggards", "realizedYtdContributionLaggards"),
        ("Since-rebalance contribution leaders", "sinceRebalanceContributionLeaders"),
        ("Since-rebalance contribution laggards", "sinceRebalanceContributionLaggards"),
        ("Raw calendar-YTD security-return leaders", "calendarYtdSecurityReturnLeaders"),
        ("Raw calendar-YTD security-return laggards", "calendarYtdSecurityReturnLaggards"),
    )
    for label, key in ranking_specs:
        items = performance_rankings.get(key, [])
        if items:
            lines.append(label + ": " + ", ".join(
                f"{item.get('ticker')} {item.get('side')} {pct(item.get('value'))}"
                for item in items
            ) + ".")
    if performance_rankings:
        lines.append(
            "Ranking guardrail: 'YTD portfolio winner/detractor' means realized dated-ledger YTD contribution. "
            "Raw calendar-YTD security return is a different market statistic, and since-rebalance contribution is a different holding period."
        )
        mandatory_rankings = []
        for label, key in (
            ("realized YTD contribution leader", "realizedYtdContributionLeaders"),
            ("realized YTD contribution laggard", "realizedYtdContributionLaggards"),
            ("since-rebalance contribution leader", "sinceRebalanceContributionLeaders"),
            ("since-rebalance contribution laggard", "sinceRebalanceContributionLaggards"),
            ("raw calendar-YTD security-return leader", "calendarYtdSecurityReturnLeaders"),
            ("raw calendar-YTD security-return laggard", "calendarYtdSecurityReturnLaggards"),
        ):
            items = performance_rankings.get(key, [])
            if items:
                item = items[0]
                mandatory_rankings.append(
                    f"{label}={item.get('ticker')} {item.get('side')} {pct(item.get('value'))}"
                )
        if mandatory_rankings:
            lines.append(
                "MANDATORY RANKING FACTS (copy these tickers, signs, and metric labels exactly when the user asks about performance): "
                + "; ".join(mandatory_rankings)
                + "."
            )
    technical_screen = context.get("volumeMomentumScreen", {})
    review_candidates = technical_screen.get("reviewCandidates", [])
    if review_candidates:
        lines.append("Pre-ranked technical weakness screen: " + ", ".join(
            f"{item.get('ticker')} {item.get('side')} status={item.get('screeningStatus')} "
            f"flags={item.get('weaknessSignalCount')} volume_confirmed={item.get('volumeConfirmsWeakness')}"
            for item in review_candidates
        ) + ".")
    partial_volume = technical_screen.get("partialSessionVolumeExcludedFor", [])
    if partial_volume:
        lines.append(
            "Incomplete current-session volume was excluded from rolling volume signals for: "
            + ", ".join(partial_volume)
            + "."
        )
    risk_context = context.get("risk", {})
    risk_contributors = risk_context.get("topContributors", [])
    if risk_contributors:
        lines.append("Top modeled risk contributors: " + ", ".join(
            f"{item.get('ticker')} {pct(item.get('percentOfRisk'))} of modeled risk"
            for item in risk_contributors[:5]
        ) + ".")
    stress_tests = risk_context.get("stressTests", [])
    if stress_tests:
        lines.append("Alpha-neutral stress impacts: " + ", ".join(
            f"{item.get('scenario')} {pct(item.get('alphaNeutralImpact'))}"
            for item in stress_tests
        ) + ".")
    lines.append("ACTIVE POSITIONS:")
    for item in context.get("positions", []):
        returns = item.get("returns", {})
        position_momentum = item.get("positionMomentum", {})
        volume = item.get("volume", {})
        technical = item.get("technical", {})
        side = item.get("side")
        side_interpretation = (
            f"SHORT INTERPRETATION: underlying 3m {pct(returns.get('3m'))} becomes BOOK EFFECT 3m "
            f"{pct(position_momentum.get('3m'))}; a positive stock return hurts this short and must never be called a book leader"
            if side == "Short"
            else f"LONG INTERPRETATION: BOOK EFFECT 3m {pct(position_momentum.get('3m'))}; positive helps and negative hurts the book"
        )
        lines.append(
            f"{item.get('ticker')} {side} | target {pct(item.get('targetWeight'))} | current {pct(item.get('currentWeight'))} | "
            f"underlying 1d {pct(returns.get('1d'))}, 1m {pct(returns.get('1m'))}, 3m {pct(returns.get('3m'))}, "
            f"6m {pct(returns.get('6m'))}, 12-1 {pct(returns.get('12mEx1m'))}, raw security YTD {pct(returns.get('ytd'))} | "
            f"position 3m {pct(position_momentum.get('3m'))}, position calendar-YTD {pct(position_momentum.get('calendarYtdSecurity'))}; "
            f"{side_interpretation} | "
            f"RS1m {pct(item.get('relativeStrength1m'))} "
            f"vs {item.get('relativeStrengthBenchmark') or 'n/a'} | 50d {pct(item.get('priceVs50d'))}, "
            f"200d {pct(item.get('priceVs200d'))}, 52wDD {pct(item.get('drawdown52w'))} | "
            f"realized YTD contribution {pct(item.get('ytdContribution'))}, since rebalance {pct(item.get('sinceRebalanceContribution'))} | "
            f"volume through {volume.get('dataThrough') or 'n/a'}: 5d/20d {ratio(volume.get('volume5dVs20d'))}, "
            f"20d/63d {ratio(volume.get('volume20dVs63d'))}, adverse/favorable {ratio(volume.get('adverseVolumeRatio20d'))}, "
            f"position volume pressure {pct(volume.get('positionVolumePressure20d'))}, completed-volume z {sigma(volume.get('latestCompletedVolumeZScore'))}, "
            f"20d ADV {dollars(volume.get('averageDollarVolume20d'))} | technical {technical.get('screeningStatus')} "
            f"flags={technical.get('weaknessSignalCount')} volume_confirmed={technical.get('volumeConfirmsWeakness')}."
        )
    return "\n".join(lines)


async def _load_brain_portfolio_context(portfolio: str = "main") -> dict[str, Any]:
    async with _brain_portfolio_context_lock:
        cache_key = f"{portfolio}_retail"
        cache_entry = _cache.get(cache_key, {})
        metrics_payload = await run_in_threadpool(
            lambda: asyncio.run(get_metrics(force=False, costTier="retail", portfolio=portfolio))
        )
        cache_entry = _cache.get(cache_key, cache_entry)
        return _build_brain_portfolio_context(
            metrics_payload,
            portfolio=portfolio,
            cache_timestamp=cache_entry.get("timestamp"),
        )


@app.get("/api/brain/portfolio-context")
async def get_brain_portfolio_context(portfolio: str = "main"):
    try:
        return await _load_brain_portfolio_context(portfolio)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Portfolio context is unavailable: {_clean_public_error(exc)[:240]}") from exc


@app.get("/api/brain/portfolio-outline")
async def get_brain_portfolio_outline(portfolio: str = "main"):
    return _build_brain_portfolio_outline(portfolio)


@app.post("/api/brain/analyze-company")
async def analyze_company_with_brain(payload: BrainCompanyAnalysisRequest):
    store = _brain_or_503()
    client = _gemini_or_503()
    started_at = time.perf_counter()
    timings: dict[str, Any] = {}

    ticker = (payload.ticker or "").strip().upper()
    question = (payload.question or "").strip() or (
        f"Analyze {ticker} using my investment brain. Focus on evidence, contradictions, risks, "
        "and what would change my mind."
        if ticker
        else "Analyze the strongest relevant evidence in my investment brain. Focus on evidence, contradictions, risks, and what would change my mind."
    )
    conversation_history = _format_conversation_history(payload.conversation)
    prior_user_questions = " ".join(
        re.sub(r"\s+", " ", turn.content).strip()[:280]
        for turn in payload.conversation[-6:]
        if turn.role.lower() == "user"
    )
    retrieval_query = f"{ticker} {prior_user_questions} {question}".strip()[:4000]
    market_data_intent = _brain_market_data_intent(retrieval_query)
    portfolio_started = time.perf_counter()
    portfolio_context = _build_brain_portfolio_outline("main")
    portfolio_context_task = (
        asyncio.create_task(_load_brain_portfolio_context("main"))
        if market_data_intent["requested"]
        else None
    )
    reference_sources_task = asyncio.create_task(_reference_sources_from_store(store))
    full_context_sources_task = asyncio.create_task(_full_context_sources_from_store(store))
    system_prompt_task = asyncio.create_task(_system_prompt_from_store(store))
    _, selected_reference_sources = await reference_sources_task
    _, selected_full_context_sources = await full_context_sources_task
    system_prompt = await system_prompt_task

    candidate_limit = min(payload.limit * 2, 20)
    retrieval_started = time.perf_counter()
    keyword_task = asyncio.create_task(
        _run_brain_step(
            "Keyword brain search",
            store.search,
            retrieval_query,
            limit=candidate_limit,
            timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
        )
    )
    memory_task = asyncio.create_task(
        _run_brain_step(
            "Memory search",
            store.list_memories,
            query=f"{ticker} {question}",
            limit=min(payload.limit, 4),
            timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
        )
    )

    keyword_results: list[dict[str, Any]] = []
    semantic_results: list[dict[str, Any]] = []
    query_embedding: list[float] | None = None
    semantic_available = False
    if payload.useSemantic:
        step_started = time.perf_counter()
        try:
            query_embedding = await _run_brain_step(
                "Semantic embedding",
                client.embed_text,
                retrieval_query,
                task_type="RETRIEVAL_QUERY",
                timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
            )
            raw_semantic_results = await _run_brain_step(
                "Supabase vector search",
                store.semantic_search_chunks,
                query_embedding,
                limit=candidate_limit,
                timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
            ) or []
            semantic_results = _filter_semantic_results(raw_semantic_results)
            semantic_available = True
        except Exception as e:
            timings["semanticError"] = _clean_public_error(e)[:240]
            semantic_results = []
        timings["semanticSearchMs"] = round((time.perf_counter() - step_started) * 1000, 1)
    else:
        timings["semanticSearchMs"] = 0.0

    try:
        keyword_results = await keyword_task
    except Exception as e:
        timings["keywordError"] = _clean_public_error(e)[:240]
        keyword_results = []
    timings["keywordSearchMs"] = round((time.perf_counter() - retrieval_started) * 1000, 1)

    try:
        memory_results = await memory_task
    except Exception as e:
        timings["memoryError"] = _clean_public_error(e)[:240]
        memory_results = []
    timings["memorySearchMs"] = round((time.perf_counter() - retrieval_started) * 1000, 1)

    context_items = _merge_retrieval_results(
        semantic_results,
        keyword_results,
        limit=payload.limit,
    )
    context_items = await _attach_source_references(store, context_items)

    step_started = time.perf_counter()
    deep_sources_task = asyncio.create_task(_run_brain_step(
        "Deep source expansion",
        _expand_semantic_hits_into_sources,
        store,
        context_items,
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    ))
    reference_context_task = asyncio.create_task(_build_reference_context(
        store,
        selected_reference_sources,
        query_embedding=query_embedding,
    ))
    full_document_context_task = asyncio.create_task(_build_full_document_context(
        store,
        selected_full_context_sources,
    ))
    deep_sources = await deep_sources_task
    reference_context, reference_semantic_hits = await reference_context_task
    full_document_context = await full_document_context_task
    timings["deepSourceExpansionMs"] = round((time.perf_counter() - step_started) * 1000, 1)

    if portfolio_context_task is not None:
        try:
            portfolio_context = await portfolio_context_task
        except Exception as exc:
            timings["portfolioContextError"] = _clean_public_error(exc)[:240]
            portfolio_context = _build_brain_portfolio_outline("main")
    timings["portfolioContextMs"] = round((time.perf_counter() - portfolio_started) * 1000, 1)

    portfolio_context_title = (
        "Authoritative live portfolio and market context from the dashboard risk engine"
        if portfolio_context.get("marketDataAvailable")
        else "Authoritative portfolio composition from the dated configuration (market data not fetched)"
    )
    market_data_guidance = (
        """Use the live portfolio context whenever the question concerns holdings, sizing, momentum, volume, concentration, exposure, contribution, portfolio risk, or potential action. Always distinguish target weight from current drifted weight. A positive underlying return helps a long but hurts a short. Position-adjusted momentum is already side-corrected: higher values help the book and lower values hurt it. When ranking momentum, use the supplied pre-ranked position-adjusted lists across both sides; never classify a rising adverse short as a leader. For every short, copy the signed BOOK EFFECT rather than the underlying stock return when discussing portfolio momentum. Keep raw calendar-YTD security return, side-adjusted calendar-YTD return, realized YTD contribution, and since-rebalance contribution separate. A 'YTD portfolio winner/detractor' must be ranked by realized YTD contribution. If the question asks to distinguish performance measures, explicitly report the MANDATORY RANKING FACTS before interpreting technical signals. Keep NAV weight and share of gross exposure as separate denominators. Completed-session volume only is used in rolling volume diagnostics. Treat the volume/momentum screen as a review queue, not a trade instruction: do not recommend selling or covering solely from technical signals; require thesis/valuation/catalyst evidence, or explicitly label the conclusion 'technical review candidate'. Describe market data as live portfolio context as of its stated date, not as a numbered document citation. If fresh=false or the as-of date is unknown, explicitly warn that the market snapshot may be stale."""
        if portfolio_context.get("marketDataAvailable")
        else "Live market data was intentionally not fetched because this question did not require it. Use target composition when relevant, but do not invent current weights, prices, momentum, volume, performance, contribution, or risk."
    )

    prompt = f"""
Use the provided research context to answer the investment question. Separate evidence from inference.
Do not pretend missing information is present.
When deep source context is available, treat it as the main evidence base: semantic search found a relevant chunk, then the backend expanded into the surrounding file chunks.
Prefer specific source titles and chunk numbers when explaining evidence.

Company/ticker context: {ticker or "Not specified; infer the relevant subject from the user's question and retrieved sources."}
User question: {question}

Previous conversation in this same brain thread:
{conversation_history or "No previous turns in this thread."}

{portfolio_context_title}:
{_format_brain_portfolio_context(portfolio_context)}

Personal memories:
{_format_context_block(memory_results, max_chars=900) or "No matching memories."}

Persistent reference layer injected into this model context:
{_format_reference_context(reference_context) or "No persistent reference sources are selected."}

Full-document context injected into this model context:
{_format_full_document_context(full_document_context) or "No full-document sources are selected."}

Retrieved source context:
{_format_context_block(context_items, max_chars=1200) or "No retrieved source context."}

Deep source expansion:
{_format_deep_source_context(deep_sources) or "No deep source expansion. This usually means no embedded chunks/files matched semantically yet."}

Write the answer in this structure:
1. Evidence from my brain
2. Interpretation
3. Contradictions / risks
4. What would change my mind
5. Decision note worth retaining

If there is previous conversation, answer as a continuation: avoid repeating earlier framing unless it is needed, say what changed or what the new evidence adds, and preserve the thread's context.
Be concise but not shallow: maximum 5 short sections, maximum 3 bullets per section. If there is no retrieved or expanded source context, say that clearly.
When relying on a numbered item from Retrieved source context, cite it compactly as [1], [2], and so on. Never invent citations or claim a source says more than the supplied excerpt.
Persistent reference sources are investor-selected frameworks. Use them as an always-on lens, but do not mistake a framework for company-specific evidence. Cite them as [R1], [R2], and so on when they materially shape the reasoning, and surface any tension with current company evidence.
Full-document sources are investor-selected primary context. They contain the full text reconstructed from the indexed file, subject to any stated extraction or context cap. Cite them as [F1], [F2], and so on when they materially support the answer. Never imply an [F] source was fully available when its label says a cap was reached.
{market_data_guidance}
""".strip()

    step_started = time.perf_counter()
    generation_timeout = (
        FULL_CONTEXT_GENERATION_TIMEOUT_SECONDS
        if full_document_context
        else min(BRAIN_ANALYSIS_TIMEOUT_SECONDS, 7.0)
    )
    try:
        answer = await _run_brain_step(
            "Gemini analysis",
            client.generate_text,
            prompt,
            system_instruction=system_prompt,
            temperature=0.2,
            max_output_tokens=1100,
            timeout_seconds=generation_timeout,
            timeout=generation_timeout + 1.0,
        )
    except Exception as e:
        timings["generationError"] = _public_exception_reason(e)[:300]
        timings["generationMs"] = round((time.perf_counter() - step_started) * 1000, 1)
        timings["totalMs"] = round((time.perf_counter() - started_at) * 1000, 1)
        return {
            "ticker": ticker,
            "question": question,
            "model": client.generation_model,
            "embeddingModel": client.embedding_model,
            "answer": _format_retrieval_fallback_answer(
                error=e,
                memory_results=memory_results,
                context_items=context_items,
                deep_sources=deep_sources,
            ),
            "timings": timings,
            "retrieval": {
                "semanticHits": len(semantic_results),
                "keywordHits": len(keyword_results),
                "mergedHits": len(context_items),
                "expandedFiles": len(deep_sources),
                "semanticAvailable": semantic_available,
                "referenceSources": len(reference_context),
                "referenceSemanticHits": reference_semantic_hits,
                "fullDocuments": len(full_document_context),
                "fullContextChars": sum(item["charsIncluded"] for item in full_document_context),
                "portfolioPositions": portfolio_context.get("positionCount", 0),
                "portfolioDataAsOf": portfolio_context.get("dataAsOf"),
                "portfolioFresh": portfolio_context.get("fresh"),
                "marketDataRequested": market_data_intent.get("requested", False),
                "marketDataReasons": market_data_intent.get("reasons", []),
                "marketDataAvailable": portfolio_context.get("marketDataAvailable", False),
            },
            "context": {
                "memories": memory_results,
                "retrieved": context_items,
                "deepSources": deep_sources,
                "references": reference_context,
                "fullDocuments": _public_full_document_context(full_document_context),
                "portfolio": portfolio_context,
            },
        }

    timings["generationMs"] = round((time.perf_counter() - step_started) * 1000, 1)
    timings["totalMs"] = round((time.perf_counter() - started_at) * 1000, 1)

    return {
        "ticker": ticker,
        "question": question,
        "model": client.generation_model,
        "embeddingModel": client.embedding_model,
        "answer": answer,
        "timings": timings,
        "retrieval": {
            "semanticHits": len(semantic_results),
            "keywordHits": len(keyword_results),
            "mergedHits": len(context_items),
            "expandedFiles": len(deep_sources),
            "semanticAvailable": semantic_available,
            "referenceSources": len(reference_context),
            "referenceSemanticHits": reference_semantic_hits,
            "fullDocuments": len(full_document_context),
            "fullContextChars": sum(item["charsIncluded"] for item in full_document_context),
            "portfolioPositions": portfolio_context.get("positionCount", 0),
            "portfolioDataAsOf": portfolio_context.get("dataAsOf"),
            "portfolioFresh": portfolio_context.get("fresh"),
            "marketDataRequested": market_data_intent.get("requested", False),
            "marketDataReasons": market_data_intent.get("reasons", []),
            "marketDataAvailable": portfolio_context.get("marketDataAvailable", False),
        },
        "context": {
            "memories": memory_results,
            "retrieved": context_items,
            "deepSources": deep_sources,
            "references": reference_context,
            "fullDocuments": _public_full_document_context(full_document_context),
            "portfolio": portfolio_context,
        },
    }

@app.get("/api/metrics")
async def get_metrics(force: bool = False, costTier: str = 'retail', portfolio: str = 'main'):
    global _cache
    
    if not risk:
        return {"error": "risk.py not found or failed to import"}
        
    cache_key = f"{portfolio}_{costTier}"
    if cache_key not in _cache:
        _cache[cache_key] = {"data": None, "timestamp": 0}
        
    tier_cache = _cache[cache_key]
    
    # Return cached response if fresh (unless force=True)
    if force:
        # Invalidate all tier caches
        for k in _cache:
            _cache[k] = {"data": None, "timestamp": 0}
    elif tier_cache["data"] and (time.time() - tier_cache["timestamp"]) < CACHE_TTL:
        print(f"Returning cached response for {cache_key} (age: {int(time.time() - tier_cache['timestamp'])}s)")
        return tier_cache["data"]

    try:
        print(f"Calculating metrics for tier: {costTier}...")
        
        # Determine rates based on costTier
        if costTier == 'institutional':
            margin_rate = 0.055
            borrow_fee = 0.010
        elif costTier == 'none':
            margin_rate = 0.0
            borrow_fee = 0.0
        else: # retail
            margin_rate = 0.120
            borrow_fee = 0.025
            
        # 1. Fetch market data (shared cache — same data for all tiers)
        usd_prices, fx_rates, volume_data, raw_prices = _get_cached_market_data(force, portfolio_name=portfolio)
        
        # 2. Calculate risk metrics with tier-specific rates
        metrics = risk.calculate_risk_metrics(
            usd_prices, 
            volume_data, 
            fx_rates,
            margin_rate=margin_rate,
            borrow_fee=borrow_fee,
            portfolio_name=portfolio
        )
        
        if metrics is None:
             print("Error: Metrics calculation returned None (insufficient data).")
             # Return a valid structure with nulls/zeros to allow frontend to render empty state
             # rather than crashing with 500
             return {
                "error": "Insufficient data to calculate metrics. (Likely Yahoo Finance rate limit or connection issue).",
                "vitals": { k: 0 for k in ["beta", "annualReturn", "annualVol", "sharpe", "sortino", "maxDrawdown", "cvar95", "rolling1mVol"] }, # Partial fallback
                "riskAttribution": [],
                "stressTests": [],
                "periodicReturns": [],
                "history": [],
                "analyticsHistory": [],
                "leverage": {}
             }

        # 2. Run Advanced Models
        stress_results = risk.stress_test_portfolio(metrics)
            
        periodic_rets = risk.calculate_periodic_returns(usd_prices, portfolio_name=portfolio)

        # 3. Format Response
        import math
        def to_float(val):
            if val is None: return None
            try:
                f = float(val)
                # Return None for NaN/Inf to avoid JSON serialization errors
                if math.isnan(f) or math.isinf(f):
                    return None
                return f
            except:
                return None

        # 3. Format Response
        response = {
            "vitals": {
                "beta": to_float(metrics.get('YTD_Beta')),
                "longOnlyBeta": to_float(metrics.get('YTD_Long_Only_Beta')),
                "shortOnlyBeta": to_float(metrics.get('YTD_Short_Only_Beta')),
                "annualReturn": to_float(metrics.get('YTD_Annual_Return')),
                "annualVol": to_float(metrics.get('YTD_Vol')),
                "sharpe": to_float(metrics.get('YTD_Sharpe')),
                "sortino": to_float(metrics.get('YTD_Sortino')),
                "maxDrawdown": to_float(metrics.get('YTD_Max_Drawdown')),
                "rolling1mVol": to_float(metrics.get('YTD_Rolling_1M_Vol')),
                "rolling1mVolBenchmark": to_float(metrics.get('Benchmark_YTD_Rolling_1M_Vol')),
                "cvar95": to_float(metrics.get('YTD_CVaR_95')),
                "jensensAlpha": to_float(metrics.get('YTD_Alpha')),
                "periodInfo": metrics.get('YTD_Period_Info'),
                
                # New YTD Fields
                "ytdReturn": to_float(metrics.get('YTD_Return')),
                "ytdAlpha": to_float(metrics.get('YTD_Alpha')),
                "ytdAlphaRaw": to_float(metrics.get('YTD_Alpha_Raw')),
                "benchmarkYtd": to_float(metrics.get('Benchmark_YTD')),
                "ytdBeta": to_float(metrics.get('YTD_Beta')),
                "ytdCorrelation": to_float(metrics.get('YTD_Correlation')),
                "ytdMaxDrawdown": to_float(metrics.get('YTD_Max_Drawdown')),
                "benchmarkYtdMaxDrawdown": to_float(metrics.get('Benchmark_YTD_Max_Drawdown')),
                "ytdReturnGross": to_float(metrics.get('YTD_Return_Gross')),
                "ytdSecurityGrossContribution": to_float(metrics.get('YTD_Security_Gross_Contribution')),
                "ytdFinancingCost": to_float(metrics.get('YTD_Financing_Cost')),
                "ytdDirectFinancingCost": to_float(metrics.get('YTD_Direct_Financing_Cost')),
                "annualFinancingCost": to_float(metrics.get('Annual_Financing_Cost')),
                "ytdCapmExpectedReturn": to_float(metrics.get('YTD_CAPM_Expected_Return')),
                "performanceScope": metrics.get('Performance_Methodology', {}).get('realisedScope'),
                "contributionScope": metrics.get('Performance_Methodology', {}).get('contributionScope'),
                "financingScope": metrics.get('Performance_Methodology', {}).get('financingScope'),
                
                # Standardized Sharpe Metrics
                "ytdSharpe": to_float(metrics.get('YTD_Sharpe')),           # Previously riskEfficiencyVol
                "benchmarkYtdSharpe": to_float(metrics.get('Benchmark_YTD_Sharpe')), 
                "benchmarkHistSharpe": to_float(metrics.get('Benchmark_Hist_Sharpe')), # For Hist Avg comparison
                "ytdVol": to_float(metrics.get('YTD_Vol')),
                "benchmarkYtdVol": to_float(metrics.get('Benchmark_YTD_Vol')),
                "ytdReturnPln": to_float(metrics.get('YTD_Return_PLN')),
                "wigYtd": to_float(metrics.get('WIG_YTD')),
                "msciYtd": to_float(metrics.get('MSCI_YTD')),
                "ytdLongsContrib": to_float(metrics.get('YTD_Longs_Contrib')),
                "ytdShortsContrib": to_float(metrics.get('YTD_Shorts_Contrib')),
                "fxWatchlist": metrics.get('Fx_Watchlist', {}),
                "currencyExposure": {}, # Will be populated below
                "periodLabel": metrics.get('Period_Label')
            },
            "leverage": metrics['Leverage_Stats'],
            "talebMetrics": metrics.get('Taleb_Metrics'),
            "riskAttribution": [],
            "stressTests": [],
            "periodicReturns": [],
            "history": [],
            "historyScope": "Static current-target-weight replay; not realised portfolio history",
            "analyticsHistory": [],
            "currentBookScenario": None,
        }

        current_book_scenario = metrics.get('Current_Book_Scenario')
        if current_book_scenario:
            response["currentBookScenario"] = {
                "scope": current_book_scenario.get("scope"),
                "period": current_book_scenario.get("period", {}),
                "beta": to_float(current_book_scenario.get("beta")),
                "annualReturn": to_float(current_book_scenario.get("annualReturn")),
                "annualVolatility": to_float(current_book_scenario.get("annualVolatility")),
                "sharpe": to_float(current_book_scenario.get("sharpe")),
                "sortino": to_float(current_book_scenario.get("sortino")),
                "maxDrawdown": to_float(current_book_scenario.get("maxDrawdown")),
                "var95Daily": to_float(current_book_scenario.get("var95Daily")),
                "cvar95Daily": to_float(current_book_scenario.get("cvar95Daily")),
            }

        # Format Convexity Metrics
        convexity = metrics.get('Convexity_Metrics')
        if convexity:
            response["convexity"] = {
                "upsideCapture": to_float(convexity.get('Upside_Capture')),
                "downsideCapture": to_float(convexity.get('Downside_Capture')),
                "captureSpread": to_float(convexity.get('Capture_Spread')),
                "quadraticCoeffs": [to_float(c) for c in convexity.get('Quadratic_Coeffs', [0,0,0])],
                "linearCoeffs": [to_float(c) for c in convexity.get('Linear_Coeffs', [0,0])],
                "rSquared": to_float(convexity.get('R_Squared')),
                "isConvex": bool(convexity.get('Is_Convex', False)),
                "scatterData": convexity.get('Scatter_Data', []),
            }
        else:
            response["convexity"] = None
            
        # Format Momentum Metrics
        momentum = metrics.get('Momentum_Metrics')
        if momentum:
            response["momentum"] = {
                "top_rs": momentum.get('top_rs', []),
                "bot_rs": momentum.get('bot_rs', []),
                "all_rs": momentum.get('all_rs', []),
                "corr_surges": momentum.get('corr_surges', []),
                "methodology": {
                    **momentum.get('methodology', {}),
                    "priceMomentum": "Adjusted-price total return: P(t) / P(t-n sessions) - 1",
                    "horizonSessions": {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "12M": 252},
                    "twelveMinusOne": "P(t-21 sessions) / P(t-252 sessions) - 1",
                    "trend": "Current USD-adjusted price relative to trailing 50-session and 200-session means",
                },
            }
        else:
            response["momentum"] = None

        # Format Risk Attribution
        for ticker, stats in metrics['Risk_Attribution'].items():
            response["riskAttribution"].append({
                "ticker": ticker,
                "weight": stats['Weight'],
                "pctRisk": stats['Pct_Risk'],
                "mctr": stats['MCTR']
            })
        response["riskAttribution"].sort(key=lambda x: x["pctRisk"], reverse=True)

        # Format Stress Tests (non-linear)
        for scenario, result in stress_results.items():
            if isinstance(result, dict):
                response["stressTests"].append({
                    "scenario": scenario,
                    "impact": to_float(result.get('alpha_neutral', result.get('nonlinear', 0))),
                    "linearImpact": to_float(result.get('linear', 0)),
                    "fittedImpact": to_float(result.get('fitted_with_alpha', result.get('nonlinear', 0))),
                    "shapeEffect": to_float(result.get('shape_effect', 0)),
                    "alphaEffect": to_float(result.get('alpha_effect', 0)),
                    "modelCurve": to_float(result.get('model_curve', 0)),
                    "modelSlope": to_float(result.get('model_slope', 0)),
                    "modelIntercept": to_float(result.get('model_intercept', 0)),
                    "marketMove": to_float(result.get('market_move', 0)),
                    "stressDays": result.get('stress_days'),
                    "dailyMarketMove": to_float(result.get('daily_market_move')),
                })
            else:
                # Fallback for old format
                response["stressTests"].append({
                    "scenario": scenario,
                    "impact": to_float(result),
                    "linearImpact": to_float(result),
                    "marketMove": None,
                })
        # Current exposure book is separate from historical snapshots used for YTD contribution.
        portfolio_config = risk.get_effective_portfolio_config(portfolio)
        all_position_config = risk.get_all_position_configs(portfolio)
        target_config = risk.load_portfolio_config(portfolio)
        ytd_position_contributions = metrics.get('YTD_Position_Contributions', {}) or {}
        since_rebalance_contributions = metrics.get('Since_Rebalance_Position_Contributions', {}) or {}
        since_rebalance_contributions_ytd_basis = metrics.get('Since_Rebalance_Position_Contributions_YTD_Basis', {}) or {}
        latest_rebalance_start_date = metrics.get('Latest_Rebalance_Start_Date')
        ytd_current_weights = metrics.get('YTD_Current_Weights', {}) or {}
        rebalance_events = metrics.get('Rebalance_Events', []) or []
        response["rebalance"] = {
            "mode": metrics.get('Rebalance_Mode', 'static'),
            "events": rebalance_events,
            "eventCount": len(rebalance_events),
            "history": _build_rebalance_change_history(portfolio, raw_prices, ytd_position_contributions),
        }

        # Calculate Currency Exposure using portfolio_config.
        # Net exposure is the signed currency risk as a share of equity;
        # gross exposure is the absolute book size in that currency.
        curr_exposure_net = {}
        curr_exposure_gross = {}
        total_gross = 0
        if portfolio_config:
            for ticker, info in portfolio_config.items():
                curr = info.get('currency', 'USD')
                weight = info.get('weight', 0)
                direction = 1 if info.get('type', 'Long') == 'Long' else -1
                curr_exposure_net[curr] = curr_exposure_net.get(curr, 0) + weight * direction
                curr_exposure_gross[curr] = curr_exposure_gross.get(curr, 0) + weight
                total_gross += weight
        
        curr_exposure_gross_share = {}
        if total_gross > 0:
            curr_exposure_gross_share = {
                curr: gross / total_gross
                for curr, gross in curr_exposure_gross.items()
            }
        
        response["vitals"]["currencyExposure"] = curr_exposure_net
        response["vitals"]["currencyExposureNet"] = curr_exposure_net
        response["vitals"]["currencyExposureGross"] = curr_exposure_gross
        response["vitals"]["currencyExposureGrossShare"] = curr_exposure_gross_share

        # Calculate Country Allocation for World Map
        country_allocation = {}
        if all_position_config:
            for ticker, info in all_position_config.items():
                country = info.get('country', 'USA')  # Default to USA if not specified
                current_info = portfolio_config.get(ticker)
                weight = current_info.get('weight', 0) if current_info else 0
                pos_type = info.get('type', 'Long')
                direction = 1 if pos_type == 'Long' else -1
                
                if ticker in ytd_position_contributions:
                    contribution = ytd_position_contributions.get(ticker) or 0
                else:
                    # Get YTD Return for active-book contribution fallback
                    ytd_ret = 0
                    if ticker in periodic_rets.index:
                        val = periodic_rets.loc[ticker, 'YTD']
                        if not pd.isna(val):
                            ytd_ret = val
                    contribution = weight * ytd_ret * direction

                if country not in country_allocation:
                    country_allocation[country] = {'long': 0, 'short': 0, 'contribution': 0, 'tickers': []}
                
                if current_info:
                    if pos_type == 'Long':
                        country_allocation[country]['long'] += weight
                    else:
                        country_allocation[country]['short'] += weight
                
                country_allocation[country]['contribution'] += contribution
                
                country_allocation[country]['tickers'].append({
                    'ticker': ticker,
                    'weight': weight,
                    'type': pos_type,
                    'contribution': contribution,
                    'status': "Active" if current_info else ("Planned" if ticker in target_config else "Exited")
                })
        
        response["countryAllocation"] = country_allocation

        # Format Periodic Returns
        # Periodic returns is a DataFrame: index=ticker, columns=['YTD', '1Y', '3Y', '5Y']
        # We need to add 1M returns and YTD contribution
        portfolio_ytd = to_float(metrics.get('YTD_Return')) or 0.0
        
        display_tickers = list(all_position_config.keys())
        for ticker in ytd_position_contributions.keys():
            if ticker not in all_position_config:
                display_tickers.append(ticker)

        for ticker in display_tickers:
            ticker_config = all_position_config.get(ticker, {})
            current_config = portfolio_config.get(ticker)
            is_planned = current_config is None and ticker in target_config
            weight = current_config.get('weight', 0) if current_config else 0
            direction = ticker_config.get('type', None)  # 'Long' or 'Short'
            is_active = current_config is not None
            status = "Active" if is_active else ("Planned" if is_planned else "Exited")
            
            # Check if this ticker is in periodic_rets
            has_rets = (periodic_rets is not None) and (ticker in periodic_rets.index)
            row = periodic_rets.loc[ticker] if has_rets else None
            
            # Calculate YTD contribution: weight * ytd_return * direction
            ytd_ret = row['YTD'] if (row is not None and 'YTD' in row and not pd.isna(row['YTD'])) else None
            dir_multiplier = 1 if direction == 'Long' else (-1 if direction == 'Short' else 0)
            if ticker in ytd_position_contributions:
                ytd_contribution = ytd_position_contributions.get(ticker)
            else:
                ytd_contribution = weight * ytd_ret * dir_multiplier if weight and ytd_ret is not None else None

            since_rebalance_contribution = since_rebalance_contributions.get(ticker)
            since_rebalance_contribution_ytd_basis = since_rebalance_contributions_ytd_basis.get(ticker)
            
            # Calculate current drifted weight
            if ticker in ytd_current_weights:
                current_weight = ytd_current_weights.get(ticker)
            elif is_active and weight and ytd_ret is not None:
                current_weight = float(weight * (1 + ytd_ret) / (1 + portfolio_ytd))
            elif not is_active:
                current_weight = 0.0
            else:
                current_weight = None
            
            # Calculate Returns and Contributions
            r1d = None
            r1m = None
            r7d = None
            r3m = None
            r6m = None
            r12m = None
            momentum_12_1 = None
            prior_1m_return = None
            momentum_acceleration_1m = None
            price_vs_50d = None
            price_vs_200d = None
            drawdown_52w = None
            trend_signal = None
            last_price = None
            volatility = None
            currency = ticker_config.get('currency', 'USD') if ticker_config else 'USD'
            sector = ticker_config.get('sector', 'Unknown') if ticker_config else 'Unknown'
            country = ticker_config.get('country', 'Unknown') if ticker_config else 'Unknown'
            
            # Get last price from raw_prices (original currency)
            if ticker in raw_prices.columns:
                raw_series = raw_prices[ticker].dropna()
                if len(raw_series) > 0:
                    last_price = float(raw_series.iloc[-1])
            
            # Volume diagnostics use completed sessions only. Intraday volume is exposed
            # separately and never mixed into rolling comparisons.
            completed_vol_series = None
            latest_session_volume = None
            latest_session_volume_complete = False
            volume_data_through = None
            vol_7d_avg = None
            vol_5d_avg = None
            vol_20d_avg = None
            vol_63d_avg = None
            vol_ytd_avg = None
            volume_indicator = None  # ratio: >1 means higher recent volume
            volume_5d_vs_20d = None
            volume_20d_vs_63d = None
            latest_volume_vs_20d = None
            latest_completed_volume_zscore = None
            average_dollar_volume_20d = None
            down_up_volume_ratio_20d = None
            adverse_volume_ratio_20d = None
            obv_pressure_20d = None
            position_volume_pressure_20d = None
            price_volume_correlation_20d = None
            position_price_volume_correlation_20d = None
            volume_observations = 0
            if volume_data is not None and ticker in volume_data.columns:
                all_volumes = volume_data[ticker].dropna()
                if len(all_volumes) > 0:
                    latest_session_volume = _finite_number(all_volumes.iloc[-1])
                    latest_session_volume_complete = bool(
                        latest_session_volume
                        and latest_session_volume > 0
                        and _market_session_is_complete(all_volumes.index[-1], country)
                    )
                    completed_vol_series = all_volumes[all_volumes > 0]
                    if not latest_session_volume_complete and len(completed_vol_series) and completed_vol_series.index[-1] == all_volumes.index[-1]:
                        completed_vol_series = completed_vol_series.iloc[:-1]

                if completed_vol_series is not None and len(completed_vol_series) > 0:
                    volume_observations = len(completed_vol_series)
                    volume_data_through = completed_vol_series.index[-1].strftime('%Y-%m-%d')
                    vol_5d_avg = float(completed_vol_series.iloc[-5:].mean()) if len(completed_vol_series) >= 5 else None
                    vol_7d_avg = float(completed_vol_series.iloc[-7:].mean()) if len(completed_vol_series) >= 7 else None
                    vol_20d_avg = float(completed_vol_series.iloc[-20:].mean()) if len(completed_vol_series) >= 20 else None
                    vol_63d_avg = float(completed_vol_series.iloc[-63:].mean()) if len(completed_vol_series) >= 63 else None
                    # YTD volume average
                    ytd_start = pd.Timestamp(datetime.now().year, 1, 1)
                    ytd_vol = completed_vol_series[completed_vol_series.index >= ytd_start]
                    if len(ytd_vol) > 0:
                        vol_ytd_avg = float(ytd_vol.mean())
                        if vol_ytd_avg > 0 and vol_7d_avg is not None:
                            volume_indicator = vol_7d_avg / vol_ytd_avg
                    if vol_5d_avg is not None and vol_20d_avg and vol_20d_avg > 0:
                        volume_5d_vs_20d = vol_5d_avg / vol_20d_avg
                    if vol_20d_avg is not None and vol_63d_avg and vol_63d_avg > 0:
                        volume_20d_vs_63d = vol_20d_avg / vol_63d_avg
                    if latest_session_volume_complete and vol_20d_avg and vol_20d_avg > 0:
                        latest_volume_vs_20d = latest_session_volume / vol_20d_avg
                    if len(completed_vol_series) >= 21:
                        baseline = completed_vol_series.iloc[-61:-1] if len(completed_vol_series) >= 61 else completed_vol_series.iloc[:-1]
                        baseline_std = baseline.std(ddof=1)
                        if len(baseline) >= 20 and baseline_std and np.isfinite(baseline_std) and baseline_std > 0:
                            latest_completed_volume_zscore = (completed_vol_series.iloc[-1] - baseline.mean()) / baseline_std

            if usd_prices is not None and ticker in usd_prices.columns:
                series = usd_prices[ticker].dropna()

                def trailing_return(sessions):
                    if len(series) <= sessions:
                        return None
                    base = series.iloc[-sessions - 1]
                    return (series.iloc[-1] - base) / base if base != 0 else None

                # 1D return
                r1d = trailing_return(1)

                # 7D return
                r7d = trailing_return(5)

                # 1M return
                r1m = trailing_return(21)
                r3m = trailing_return(63)
                r6m = trailing_return(126)
                r12m = trailing_return(252)
                if len(series) > 42:
                    prior_1m_base = series.iloc[-43]
                    prior_1m_end = series.iloc[-22]
                    prior_1m_return = (prior_1m_end - prior_1m_base) / prior_1m_base if prior_1m_base != 0 else None
                    momentum_acceleration_1m = r1m - prior_1m_return if r1m is not None and prior_1m_return is not None else None
                if len(series) > 252:
                    twelve_month_base = series.iloc[-253]
                    one_month_ago = series.iloc[-22]
                    momentum_12_1 = (one_month_ago - twelve_month_base) / twelve_month_base if twelve_month_base != 0 else None

                current_usd = series.iloc[-1] if len(series) else None
                if current_usd is not None and len(series) >= 50:
                    sma_50 = series.iloc[-50:].mean()
                    price_vs_50d = (current_usd - sma_50) / sma_50 if sma_50 != 0 else None
                if current_usd is not None and len(series) >= 200:
                    sma_200 = series.iloc[-200:].mean()
                    price_vs_200d = (current_usd - sma_200) / sma_200 if sma_200 != 0 else None
                if current_usd is not None and len(series) >= 2:
                    high_52w = series.iloc[-min(252, len(series)):].max()
                    drawdown_52w = (current_usd - high_52w) / high_52w if high_52w != 0 else None
                if price_vs_50d is not None and price_vs_200d is not None:
                    if price_vs_50d > 0 and price_vs_200d > 0:
                        trend_signal = "above_50d_and_200d"
                    elif price_vs_50d < 0 and price_vs_200d < 0:
                        trend_signal = "below_50d_and_200d"
                    else:
                        trend_signal = "mixed_trend"
                
                # Annualized volatility (std dev of daily returns * sqrt(252))
                if len(series) > 20:
                    daily_returns = series.pct_change().dropna()
                    if len(daily_returns) > 0:
                        volatility = float(daily_returns.std() * np.sqrt(252))

                if completed_vol_series is not None and len(completed_vol_series) >= 5:
                    aligned_volume = pd.concat(
                        [series.pct_change().rename('return'), completed_vol_series.rename('volume')],
                        axis=1,
                        join='inner',
                    ).dropna().iloc[-20:]
                    if len(aligned_volume) >= 5:
                        up_volume = aligned_volume.loc[aligned_volume['return'] > 0, 'volume'].mean()
                        down_volume = aligned_volume.loc[aligned_volume['return'] < 0, 'volume'].mean()
                        if pd.notna(up_volume) and pd.notna(down_volume) and up_volume > 0 and down_volume > 0:
                            down_up_volume_ratio_20d = down_volume / up_volume
                            adverse_volume_ratio_20d = down_up_volume_ratio_20d if direction == 'Long' else 1 / down_up_volume_ratio_20d
                        total_volume = aligned_volume['volume'].sum()
                        if total_volume > 0:
                            obv_pressure_20d = float((np.sign(aligned_volume['return']) * aligned_volume['volume']).sum() / total_volume)
                            position_volume_pressure_20d = obv_pressure_20d * dir_multiplier
                        if len(aligned_volume) >= 10 and aligned_volume['volume'].nunique() > 1:
                            price_volume_correlation_20d = aligned_volume['return'].corr(np.log1p(aligned_volume['volume']))
                            if pd.notna(price_volume_correlation_20d):
                                price_volume_correlation_20d = float(price_volume_correlation_20d)
                                position_price_volume_correlation_20d = price_volume_correlation_20d * dir_multiplier

                    dollar_volume = pd.concat(
                        [series.rename('price'), completed_vol_series.rename('volume')],
                        axis=1,
                        join='inner',
                    ).dropna().iloc[-20:]
                    if len(dollar_volume) >= 5:
                        average_dollar_volume_20d = float((dollar_volume['price'] * dollar_volume['volume']).mean())
            
            # Daily/Weekly contribution uses CURRENT (drifted) weight, not initial.
            r1d_contribution = current_weight * r1d * dir_multiplier if is_active and current_weight and r1d is not None else None
            r7d_contribution = current_weight * r7d * dir_multiplier if is_active and current_weight and r7d is not None else None

            item = {
                "ticker": ticker,
                "sector": sector,
                "ytd": ytd_ret,
                "r1d": to_float(r1d),
                "r7d": to_float(r7d),
                "r1m": to_float(r1m),
                "r3m": to_float(r3m),
                "r6m": to_float(r6m),
                "r12m": to_float(r12m),
                "r12mEx1m": to_float(momentum_12_1),
                "prior1m": to_float(prior_1m_return),
                "momentumAcceleration1m": to_float(momentum_acceleration_1m),
                "r1y": row['1Y'] if (row is not None and '1Y' in row and not pd.isna(row['1Y'])) else to_float(r12m),
                "priceVs50d": to_float(price_vs_50d),
                "priceVs200d": to_float(price_vs_200d),
                "drawdown52w": to_float(drawdown_52w),
                "trendSignal": trend_signal,
                "ytdContribution": to_float(ytd_contribution),
                "sinceRebalanceContribution": to_float(since_rebalance_contribution),
                "sinceRebalanceContributionYtdBasis": to_float(since_rebalance_contribution_ytd_basis),
                "sinceRebalanceStartDate": latest_rebalance_start_date,
                "r1dContribution": to_float(r1d_contribution),
                "r7dContribution": to_float(r7d_contribution),
                "weight": to_float(weight) if weight else None,
                "currentWeight": to_float(current_weight) if current_weight is not None else to_float(weight),
                "direction": direction,
                "status": status,
                "lastPrice": last_price,
                "entryPrice": ticker_config.get('entry_price', None) if ticker_config else None,
                "currency": currency,
                "country": country,
                "volatility": volatility,
                "volumeIndicator": to_float(volume_indicator),
                "volumeDataThrough": volume_data_through,
                "latestSessionVolume": to_float(latest_session_volume),
                "latestSessionVolumeComplete": latest_session_volume_complete,
                "volumeObservations": volume_observations,
                "volume5dVs20d": to_float(volume_5d_vs_20d),
                "volume20dVs63d": to_float(volume_20d_vs_63d),
                "latestVolumeVs20d": to_float(latest_volume_vs_20d),
                "latestCompletedVolumeZScore": to_float(latest_completed_volume_zscore),
                "averageDollarVolume20d": to_float(average_dollar_volume_20d),
                "downUpVolumeRatio20d": to_float(down_up_volume_ratio_20d),
                "adverseVolumeRatio20d": to_float(adverse_volume_ratio_20d),
                "obvPressure20d": to_float(obv_pressure_20d),
                "positionVolumePressure20d": to_float(position_volume_pressure_20d),
                "priceVolumeCorrelation20d": to_float(price_volume_correlation_20d),
                "positionPriceVolumeCorrelation20d": to_float(position_price_volume_correlation_20d),
            }
            response["periodicReturns"].append(item)

            
        # Format History (Cumulative 1000 base)
        portfolio_cum = (1 + metrics['Returns_Stream']).cumprod() * 1000
        benchmark_cum = (1 + metrics['Benchmark_Stream']).cumprod() * 1000
        drawdown_stream = metrics['Drawdown_Stream']
        
        # Align indexes
        common_idx = portfolio_cum.index
        
        # We'll limit history to optimize payload if needed, but for now send full
        for date in common_idx:
            date_str = date.strftime('%Y-%m-%d')
            response["history"].append({
                "date": date_str,
                "portfolio": to_float(portfolio_cum.loc[date]),
                "benchmark": to_float(benchmark_cum.loc[date]),
                "drawdown": to_float(drawdown_stream.loc[date])
            })

        # Format YTD History (Base 100k)
        response["ytdHistory"] = []
        if metrics.get('YTD_Stream') is not None:
            ytd_port = metrics['YTD_Stream']
            ytd_port_gross = metrics.get('YTD_Gross_Stream')
            # Reconstruct YTD Benchmark Value Series (Start=1.0)
            ytd_bench_ret = metrics.get('YTD_Benchmark_Stream')
            
            if ytd_port is not None and not ytd_port.empty:
                 # Benchmark might be returns series, need convert to price index starting 1.0
                if ytd_bench_ret is not None and not ytd_bench_ret.empty:
                    ytd_bench_vals = (1 + ytd_bench_ret).cumprod()

                ytd_beta_hist = metrics.get('YTD_Beta_History')
                
                # Align dates
                for date in ytd_port.index:
                    date_str = date.strftime('%Y-%m-%d')
                    port_val = ytd_port.loc[date] * 100000
                    gross_val = None
                    if ytd_port_gross is not None and date in ytd_port_gross.index:
                        gross_val = ytd_port_gross.loc[date] * 100000
                    
                    beta_val = None
                    if ytd_beta_hist is not None and date in ytd_beta_hist.index:
                        beta_val = ytd_beta_hist.loc[date]
                    
                    response["ytdHistory"].append({
                        "date": date_str,
                        "portfolio": to_float(port_val),
                        "portfolioGross": to_float(gross_val),
                        "benchmark": None, # calculated below
                        "beta": to_float(beta_val)
                    })

                # Proper Benchmark Index Calculation
                if ytd_bench_ret is not None and not ytd_bench_ret.empty:
                    # Align to portfolio dates
                    aligned_bench = ytd_bench_ret.reindex(ytd_port.index).fillna(0)
                    bench_curve = (1 + aligned_bench).cumprod() * 100000
                    
                    for i, item in enumerate(response["ytdHistory"]):
                        date = item["date"]
                        # Map back
                        if i < len(bench_curve):
                             item["benchmark"] = to_float(bench_curve.iloc[i])

        for row in metrics.get("YTD_Historical_Diagnostics", []) or []:
            response["analyticsHistory"].append({
                "date": row.get("date"),
                "portfolio": to_float(row.get("portfolio")),
                "drawdown": to_float(row.get("drawdown")),
                "variance": to_float(row.get("variance")),
                "volatility": to_float(row.get("volatility")),
                "beta": to_float(row.get("beta")),
                "battingAverage": to_float(row.get("battingAverage")),
                "winnersCount": row.get("winnersCount", 0),
                "losersCount": row.get("losersCount", 0),
                "positionsCount": row.get("positionsCount", 0),
                "profitFactor": to_float(row.get("profitFactor")),
            })

        # Sanitize stress tests
        for st in response["stressTests"]:
            for key in (
                "impact",
                "linearImpact",
                "fittedImpact",
                "shapeEffect",
                "alphaEffect",
                "modelCurve",
                "modelSlope",
                "modelIntercept",
                "marketMove",
                "dailyMarketMove",
            ):
                if key in st:
                    st[key] = to_float(st[key])
        
        # Sanitize risk attribution
        for ra in response["riskAttribution"]:
            ra["weight"] = to_float(ra["weight"])
            ra["pctRisk"] = to_float(ra["pctRisk"])
            ra["mctr"] = to_float(ra["mctr"])

        # Store in cache
        tier_cache["data"] = response
        tier_cache["timestamp"] = time.time()
        print(f"Response cached at {tier_cache['timestamp']}")

        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

# ==========================================
# Portfolio Details API (lightweight, no market data fetch)
# ==========================================

@app.get("/api/portfolio")
async def get_portfolio(portfolio: str = 'main'):
    """Return the full portfolio composition from config."""
    if not risk:
        return {"error": "Risk module not loaded"}

    portfolio_config = risk.get_effective_portfolio_config(portfolio)
    benchmark = getattr(risk, 'BENCHMARK', 'SPY')

    positions = []
    long_exposure = 0.0
    short_exposure = 0.0

    for ticker, info in portfolio_config.items():
        position = {
            "ticker": ticker,
            "weight": info.get('weight', 0),
            "type": info.get('type', 'Long'),
            "currency": info.get('currency', 'USD'),
            "country": info.get('country', 'USA'),
            "sector": info.get('sector', 'Unknown'),
        }
        if 'entry_price' in info:
            position['entry_price'] = info['entry_price']
            
        positions.append(position)
        if info.get('type') == 'Long':
            long_exposure += info.get('weight', 0)
        else:
            short_exposure += info.get('weight', 0)

    return {
        "positions": positions,
        "leverage": {
            "longExposure": round(long_exposure, 4),
            "shortExposure": round(short_exposure, 4),
            "grossExposure": round(long_exposure + short_exposure, 4),
            "netExposure": round(long_exposure - short_exposure, 4),
        },
        "benchmark": benchmark,
        "positionCount": len(positions),
    }


@app.get("/api/portfolio/allocation")
async def get_portfolio_allocation(portfolio: str = 'main'):
    """Return portfolio allocation breakdowns by sector, country, currency, and direction."""
    if not risk:
        return {"error": "Risk module not loaded"}

    portfolio_config = risk.get_effective_portfolio_config(portfolio)

    by_sector = {}
    by_country = {}
    by_currency = {}
    by_direction = {"Long": 0.0, "Short": 0.0}

    for ticker, info in portfolio_config.items():
        weight = info.get('weight', 0)
        sector = info.get('sector', 'Unknown')
        country = info.get('country', 'USA')
        currency = info.get('currency', 'USD')
        direction = info.get('type', 'Long')

        by_sector[sector] = round(by_sector.get(sector, 0) + weight, 4)
        by_country[country] = round(by_country.get(country, 0) + weight, 4)
        by_currency[currency] = round(by_currency.get(currency, 0) + weight, 4)
        by_direction[direction] = round(by_direction.get(direction, 0) + weight, 4)

    return {
        "bySector": dict(sorted(by_sector.items(), key=lambda x: x[1], reverse=True)),
        "byCountry": dict(sorted(by_country.items(), key=lambda x: x[1], reverse=True)),
        "byCurrency": dict(sorted(by_currency.items(), key=lambda x: x[1], reverse=True)),
        "byDirection": by_direction,
    }


try:
    from portfolio_tracker import PortfolioTracker
except ImportError:
    PortfolioTracker = None

tracker = PortfolioTracker() if PortfolioTracker else None

# Pydantic Models
class PositionRequest(BaseModel):
    ticker: str
    shares: float
    price: float
    date: str
    currency: str = "USD"
    type: str = "Long"

@app.get("/api/tracker")
async def get_portfolio_tracker():
    if not tracker:
        return {"error": "Portfolio Tracker module not loaded"}
    try:
        # For now return raw DB data, heavy calc later
        return tracker.get_portfolio()
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/tracker/summary")
async def get_portfolio_summary():
    if not tracker:
        return {"error": "Portfolio Tracker module not loaded"}
    try:
        # This triggers live price fetch
        return tracker.get_summary()
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/tracker/position")
async def add_position(pos: PositionRequest):
    if not tracker:
        return {"error": "Portfolio Tracker module not loaded"}
    try:
        tracker.add_position(
            pos.ticker, 
            pos.shares, 
            pos.price, 
            pos.date, 
            pos.currency, 
            pos.type
        )
        return {"status": "success", "message": f"Added {pos.ticker}"}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/api/tracker/position/{ticker}")
async def remove_position(ticker: str):
    if not tracker:
        return {"error": "Portfolio Tracker module not loaded"}
    try:
        tracker.remove_position(ticker)
        return {"status": "success", "message": f"Removed {ticker}"}
    except Exception as e:
        return {"error": str(e)}

# ==========================================
# Stock Autocomplete API
# ==========================================

@app.get("/api/lookup/suggest")
async def suggest_tickers(query: str):
    """
    Returns autocomplete suggestions using Yahoo Finance's search endpoint.
    """
    import httpx
    if not query or len(query.strip()) < 1:
        return []
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {
            "q": query,
            "quotesCount": 7,
            "newsCount": 0,
            "listsCount": 0,
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            data = resp.json()
        quotes = data.get("quotes", [])
        return [
            {
                "symbol":   q.get("symbol", ""),
                "name":     q.get("longname") or q.get("shortname", ""),
                "exchange": q.get("exchange", ""),
                "type":     q.get("quoteType", ""),
            }
            for q in quotes
            if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF")
        ]
    except Exception as e:
        return []


# ==========================================
# Stock Lookup API
# ==========================================

@app.get("/api/lookup")
async def lookup_stock(query: str):
    """
    Fetch price returns and valuation metrics for any ticker via yfinance.
    Returns: 1D, 7D, 1M, YTD, 1Y returns + TTM P/E + (FCF-SBC)/EV yield.
    """
    import math

    def safe_float(val):
        try:
            f = float(val)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except:
            return None

    try:
        ticker_str = query.strip().upper()
        t = yf.Ticker(ticker_str)

        # --- Fetch price history for returns ---
        hist = t.history(period="2y", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return {"error": f"No price data found for '{query}'. Please check the ticker symbol."}

        close = hist["Close"].dropna()
        now = close.index[-1]
        current_price = float(close.iloc[-1])

        def period_return(days=None, ytd=False):
            if ytd:
                year_start = pd.Timestamp(f"{now.year}-01-01", tz=close.index.tz)
                sub = close[close.index >= year_start]
                if len(sub) < 1:
                    return None
                # Find prev year close
                prev = close[close.index < year_start]
                base = float(prev.iloc[-1]) if not prev.empty else float(sub.iloc[0])
                return (float(sub.iloc[-1]) - base) / base if base != 0 else None
            else:
                # Find approx trading days back
                if len(close) <= days:
                    return None
                base = float(close.iloc[-days - 1])
                return (current_price - base) / base if base != 0 else None

        r1d  = period_return(days=1)
        r7d  = period_return(days=5)    # ~1 trading week
        r1m  = period_return(days=21)   # ~1 trading month
        r1y  = period_return(days=252)
        r_ytd = period_return(ytd=True)

        # --- Fetch info dict for valuation ---
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        name     = info.get("longName") or info.get("shortName") or ticker_str
        currency = info.get("currency", "USD")

        # TTM P/E
        pe = safe_float(info.get("trailingPE"))

        # (FCF - SBC) / EV
        fcf = safe_float(info.get("freeCashflow"))
        ev  = safe_float(info.get("enterpriseValue"))

        # Try to get SBC from cashflow statement
        sbc = None
        sbc_estimated = False
        try:
            cf = t.cashflow  # columns = years, index = line items
            if cf is not None and not cf.empty:
                # yfinance labels vary — try a few
                for label in ["Stock Based Compensation", "StockBasedCompensation", "Share Based Compensation Expense"]:
                    if label in cf.index:
                        sbc_val = safe_float(cf.loc[label].iloc[0])  # most recent year
                        if sbc_val is not None:
                            sbc = abs(sbc_val)  # cashflow statements show SBC as positive outflow
                            break
        except Exception:
            pass

        if sbc is None:
            sbc = 0.0
            sbc_estimated = True

        # Compute (FCF - SBC) / EV yield
        fcf_sbc_yield = None
        if fcf is not None and ev is not None and ev != 0:
            fcf_sbc_yield = (fcf - sbc) / ev  # expressed as decimal, rendered as % on frontend

        return {
            "ticker":        ticker_str,
            "name":          name,
            "currency":      currency,
            "currentPrice":  current_price,
            "r1d":           safe_float(r1d),
            "r7d":           safe_float(r7d),
            "r1m":           safe_float(r1m),
            "rYtd":          safe_float(r_ytd),
            "r1y":           safe_float(r1y),
            "pe":            pe,
            "fcfSbcYield":   safe_float(fcf_sbc_yield),
            "sbc_estimated": sbc_estimated,
            "error":         None,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


# ==========================================
# Business Quality API  — "Munger Lens"
# ==========================================

_quality_cache: dict = {}
QUALITY_TTL = 3600  # 1 hour – fundamental data doesn't change daily

@app.get("/api/quality")
async def get_quality(portfolio: str = 'main'):
    """
    Return Munger-style business quality metrics for every holding.
    Metrics: ROIC proxy (ROE as fallback), gross margin, debt/equity,
             FCF yield (FCF/EV), owner earnings yield ((FCF-SBC)/EV),
    All sourced from yfinance .info – cached 1 hour.
    """
    import math

    now = time.time()
    if portfolio in _quality_cache:
        entry = _quality_cache[portfolio]
        if (now - entry["ts"]) < QUALITY_TTL:
            print(f"[quality] Returning cached data for {portfolio}")
            return entry["data"]

    if not risk:
        return {"error": "Risk module not loaded"}

    portfolio_config = risk.get_effective_portfolio_config(portfolio)

    def sf(val):
        """Safe float – returns None for NaN/Inf/missing."""
        try:
            f = float(val)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except:
            return None

    results = []

    for ticker, cfg in portfolio_config.items():
        print(f"[quality] Fetching {ticker}…")
        try:
            t = yf.Ticker(ticker)
            info = {}
            try:
                info = t.info or {}
            except Exception:
                pass

            # ── Core quality metrics ──────────────────────────────
            roe          = sf(info.get("returnOnEquity"))      # proxy for ROIC when no debt breakdown
            roic_approx  = sf(info.get("returnOnAssets"))      # more conservative ROIC proxy
            gross_margin = sf(info.get("grossMargins"))
            op_margin    = sf(info.get("operatingMargins"))
            net_margin   = sf(info.get("profitMargins"))
            debt_equity  = sf(info.get("debtToEquity"))        # as ratio (e.g. 0.5 = 50%)
            rev_growth   = sf(info.get("revenueGrowth"))       # trailing 12m vs prior year
            current_ratio= sf(info.get("currentRatio"))
            peg          = sf(info.get("pegRatio"))
            pe           = sf(info.get("trailingPE"))
            pb           = sf(info.get("priceToBook"))

            # ── Owner Earnings (FCF − SBC) / EV ──────────────────
            fcf          = sf(info.get("freeCashflow"))
            ev           = sf(info.get("enterpriseValue"))

            sbc = None
            try:
                cf = t.cashflow
                if cf is not None and not cf.empty:
                    for label in ["Stock Based Compensation", "StockBasedCompensation",
                                  "Share Based Compensation Expense"]:
                        if label in cf.index:
                            v = sf(cf.loc[label].iloc[0])
                            if v is not None:
                                sbc = abs(v)
                                break
            except Exception:
                pass

            fcf_ev_yield = (fcf / ev) if (fcf is not None and ev and ev != 0) else None
            owner_earnings = (fcf - (sbc or 0)) if fcf is not None else None
            oe_yield = (owner_earnings / ev) if (owner_earnings is not None and ev and ev != 0) else None

            # ── Munger quality score (0-100) ──────────────────────
            # Each criterion contributes points; no single factor dominates.
            score = 0
            flags = []

            if gross_margin is not None:
                if gross_margin >= 0.50:  score += 25; flags.append("✓ Pricing power")
                elif gross_margin >= 0.30: score += 12
                else: flags.append("✗ Thin margins")

            if roic_approx is not None:
                if roic_approx >= 0.15:   score += 25; flags.append("✓ High ROIC")
                elif roic_approx >= 0.08:  score += 12
                else: flags.append("✗ Low ROIC")

            if oe_yield is not None:
                if oe_yield >= 0.05:   score += 20; flags.append("✓ Cheap on OE")
                elif oe_yield >= 0.02: score += 10
                elif oe_yield < 0:     flags.append("✗ Negative OE yield")

            if debt_equity is not None:
                # yfinance returns D/E as percent (e.g. 45.2 means 45.2%)
                de_ratio = debt_equity / 100 if debt_equity > 5 else debt_equity
                if de_ratio <= 0.30:   score += 15; flags.append("✓ Fortress balance sheet")
                elif de_ratio <= 0.80: score += 7
                else: flags.append("✗ High leverage")

            if rev_growth is not None:
                if rev_growth >= 0.10:  score += 15; flags.append("✓ Revenue growth")
                elif rev_growth >= 0.0:  score += 7
                else: flags.append("✗ Revenue shrinking")

            score = min(score, 100)

            # ── Inversion: biggest risk to the thesis ─────────────
            inversion_risks = []
            if gross_margin is not None and gross_margin < 0.20:
                inversion_risks.append("Commodity-like pricing — margin compression risk")
            if debt_equity is not None:
                de_ratio = debt_equity / 100 if debt_equity > 5 else debt_equity
                if de_ratio > 1.0:
                    inversion_risks.append("High debt — rising rates could stress coverage")
            if pe is not None and pe > 40:
                inversion_risks.append("Rich valuation — growth disappointment = large de-rating")
            if rev_growth is not None and rev_growth < 0:
                inversion_risks.append("Declining revenue — business in structural decline?")
            if oe_yield is not None and oe_yield < 0:
                inversion_risks.append("Burning cash after SBC — not self-financing")
            if not inversion_risks:
                inversion_risks.append("No obvious red flags in available data")

            results.append({
                "ticker":        ticker,
                "direction":     cfg.get("type", "Long"),
                "weight":        cfg.get("weight", 0),
                "sector":        cfg.get("sector", "Unknown"),
                "country":       cfg.get("country", "USA"),
                "name":          info.get("longName") or info.get("shortName") or ticker,
                # Quality metrics
                "grossMargin":   sf(gross_margin),
                "roic":          sf(roic_approx),   # ROA as ROIC proxy
                "roe":           sf(roe),
                "debtEquity":    sf(debt_equity),
                "revenueGrowth": sf(rev_growth),
                "currentRatio":  sf(current_ratio),
                "opMargin":      sf(op_margin),
                "netMargin":     sf(net_margin),
                "pe":            sf(pe),
                "pb":            sf(pb),
                "peg":           sf(peg),
                "fcfEvYield":    sf(fcf_ev_yield),
                "ownerEarningsYield": sf(oe_yield),
                "sbcEstimated":  sbc is None,
                # Munger lens
                "qualityScore":  score,
                "qualityFlags":  flags,
                "inversionRisks": inversion_risks,
            })

        except Exception as e:
            print(f"[quality] Error fetching {ticker}: {e}")
            results.append({
                "ticker": ticker,
                "direction": cfg.get("type", "Long"),
                "weight": cfg.get("weight", 0),
                "sector": cfg.get("sector", "Unknown"),
                "error": str(e),
                "qualityScore": None,
                "qualityFlags": [],
                "inversionRisks": ["Data unavailable"],
            })

    payload = {"portfolio": portfolio, "positions": results}
    _quality_cache[portfolio] = {"data": payload, "ts": now}
    return payload


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

