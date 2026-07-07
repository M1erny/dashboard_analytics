import sys
import os
import html
import re
import asyncio

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

# Import risk.py (Now local)
try:
    import risk
except ImportError as e:
    print(f"Error importing risk.py: {e}")
    risk = None

try:
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


BRAIN_SEARCH_TIMEOUT_SECONDS = _env_float("BRAIN_SEARCH_TIMEOUT_SECONDS", 18.0)
BRAIN_ANALYSIS_TIMEOUT_SECONDS = _env_float("BRAIN_ANALYSIS_TIMEOUT_SECONDS", 8.0)
BRAIN_INDEX_TIMEOUT_SECONDS = _env_float("BRAIN_INDEX_TIMEOUT_SECONDS", 240.0)

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
    drive_file_id = metadata.get("driveFileId")
    web_url = (
        metadata.get("webViewLink")
        or metadata.get("driveWebViewLink")
        or (f"https://drive.google.com/file/d/{drive_file_id}/view" if drive_file_id else None)
    )
    local_path = metadata.get("absolutePath") or metadata.get("localPath")
    relative_path = metadata.get("relativePath")

    return {
        "id": source.get("id"),
        "title": source.get("title"),
        "kind": source.get("kind"),
        "tags": source.get("tags", []),
        "sourceType": metadata.get("sourceType"),
        "fileName": metadata.get("fileName"),
        "relativePath": relative_path,
        "webUrl": web_url,
        "localPath": local_path,
        "driveFileId": drive_file_id,
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


class BrainConversationTurn(BaseModel):
    role: str = Field(..., min_length=1, max_length=20)
    content: str = Field(..., min_length=1, max_length=5000)


class BrainCompanyAnalysisRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=40)
    question: str | None = None
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
    ]
    if _local_indexing_enabled():
        capabilities.append("local_file_indexing")

    return {
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
    return await _run_brain_step("Drive index status", client.status, folder_id)


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


@app.get("/api/brain/search")
async def search_brain(q: str, limit: int = 50, entity_type: str | None = None):
    store = _brain_or_503()
    started_at = time.perf_counter()
    results = await _run_brain_step(
        "Keyword brain search",
        store.search,
        query=q,
        limit=limit,
        entity_type=entity_type,
    )
    results = await _attach_source_references(store, results)
    counts = await _run_brain_step("Brain counts", store.counts)
    return {
        "query": q,
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
async def semantic_brain_search(q: str, limit: int = 10):
    store = _brain_or_503()
    client = _gemini_or_503()
    started_at = time.perf_counter()
    try:
        query_embedding = await _run_brain_step(
            "Semantic embedding",
            client.embed_text,
            q,
            task_type="RETRIEVAL_QUERY",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=_semantic_error_detail(e))

    embedding_ms = round((time.perf_counter() - started_at) * 1000, 1)
    search_started_at = time.perf_counter()
    try:
        chunks = await _run_brain_step(
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
        }
        for chunk in chunks
    ])
    return {
        "query": q,
        "model": client.embedding_model,
        "results": results,
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
    window: int = 4,
    max_source_chunks: int = 80,
    max_chunks_per_source: int = 10,
    max_chars_per_chunk: int = 900,
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    source_ids: list[int] = []
    hit_ordinals: dict[int, list[int]] = {}

    for item in hits:
        source_id = _source_id_from_context(item)
        if source_id is None:
            continue
        if source_id not in source_ids:
            source_ids.append(source_id)
        ordinal = item.get("ordinal")
        if isinstance(ordinal, int):
            hit_ordinals.setdefault(source_id, []).append(ordinal)
        if len(source_ids) >= max_sources:
            break

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


@app.post("/api/brain/analyze-company")
async def analyze_company_with_brain(payload: BrainCompanyAnalysisRequest):
    store = _brain_or_503()
    client = _gemini_or_503()
    started_at = time.perf_counter()
    timings: dict[str, Any] = {}

    ticker = payload.ticker.strip().upper()
    question = (payload.question or "").strip() or (
        f"Analyze {ticker} using my investment brain. Focus on evidence, contradictions, risks, "
        "and what would change my mind."
    )
    conversation_history = _format_conversation_history(payload.conversation)
    prior_user_questions = " ".join(
        re.sub(r"\s+", " ", turn.content).strip()[:280]
        for turn in payload.conversation[-6:]
        if turn.role.lower() == "user"
    )
    retrieval_query = f"{ticker} {prior_user_questions} {question}".strip()[:4000]

    step_started = time.perf_counter()
    keyword_results = await _run_brain_step(
        "Keyword brain search",
        store.search,
        retrieval_query,
        limit=payload.limit,
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    timings["keywordSearchMs"] = round((time.perf_counter() - step_started) * 1000, 1)

    semantic_results = []
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
            semantic_results = await _run_brain_step(
                "Supabase vector search",
                store.semantic_search_chunks,
                query_embedding,
                limit=payload.limit,
                timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
            ) or []
        except Exception as e:
            timings["semanticError"] = _clean_public_error(e)[:240]
            semantic_results = []
        timings["semanticSearchMs"] = round((time.perf_counter() - step_started) * 1000, 1)

    step_started = time.perf_counter()
    memory_results = await _run_brain_step(
        "Memory search",
        store.list_memories,
        query=ticker,
        limit=payload.limit,
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    if not memory_results:
        memory_results = await _run_brain_step(
            "Memory search",
            store.list_memories,
            query=question,
            limit=min(payload.limit, 6),
            timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
        )
    timings["memorySearchMs"] = round((time.perf_counter() - step_started) * 1000, 1)

    context_items = []
    seen = set()
    for item in semantic_results + keyword_results:
        key = (item.get("entityType", "chunk"), item.get("id") or item.get("entityId"))
        if key in seen:
            continue
        seen.add(key)
        context_items.append(item)
        if len(context_items) >= payload.limit:
            break
    context_items = await _attach_source_references(store, context_items)

    step_started = time.perf_counter()
    deep_sources = await _run_brain_step(
        "Deep source expansion",
        _expand_semantic_hits_into_sources,
        store,
        semantic_results or context_items,
        timeout=BRAIN_SEARCH_TIMEOUT_SECONDS,
    )
    timings["deepSourceExpansionMs"] = round((time.perf_counter() - step_started) * 1000, 1)

    prompt = f"""
You are an investment research assistant for one investor's private dashboard.
Use the provided brain context, but separate evidence from inference.
Do not pretend missing information is present.
When deep source context is available, treat it as the main evidence base: semantic search found a relevant chunk, then the backend expanded into the surrounding file chunks.
Prefer specific source titles and chunk numbers when explaining evidence.

Company/ticker: {ticker}
User question: {question}

Previous conversation in this same brain thread:
{conversation_history or "No previous turns in this thread."}

Personal memories:
{_format_context_block(memory_results, max_chars=900) or "No matching memories."}

Retrieved source context:
{_format_context_block(context_items, max_chars=1200) or "No retrieved source context."}

Deep source expansion:
{_format_deep_source_context(deep_sources) or "No deep source expansion. This usually means no embedded chunks/files matched semantically yet."}

Write the answer in this structure:
1. Evidence from my brain
2. Interpretation
3. Contradictions / risks
4. What would change my mind
5. Memory worth saving

If there is previous conversation, answer as a continuation: avoid repeating earlier framing unless it is needed, say what changed or what the new evidence adds, and preserve the thread's context.
Be concise but not shallow: maximum 5 short sections, maximum 3 bullets per section. If there is no retrieved or expanded source context, say that clearly.
""".strip()

    step_started = time.perf_counter()
    try:
        answer = await _run_brain_step(
            "Gemini analysis",
            client.generate_text,
            prompt,
            temperature=0.2,
            max_output_tokens=850,
            timeout=BRAIN_ANALYSIS_TIMEOUT_SECONDS,
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
            "context": {
                "memories": memory_results,
                "retrieved": context_items,
                "deepSources": deep_sources,
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
        "context": {
            "memories": memory_results,
            "retrieved": context_items,
            "deepSources": deep_sources,
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
                "beta": to_float(metrics['Beta']),
                "longOnlyBeta": to_float(metrics.get('YTD_Long_Only_Beta')),
                "shortOnlyBeta": to_float(metrics.get('YTD_Short_Only_Beta')),
                "annualReturn": to_float(metrics['Annual_Return']),
                "annualVol": to_float(metrics['Annual_Vol']),
                "sharpe": to_float(metrics['Sharpe']),
                "sortino": to_float(metrics['Sortino']),
                "maxDrawdown": to_float(metrics['Max_Drawdown']),
                "rolling1mVol": to_float(metrics.get('Rolling_1M_Vol')),
                "rolling1mVolBenchmark": to_float(metrics.get('Benchmark_Rolling_1M_Vol')),
                "cvar95": to_float(metrics['CVaR_95']),
                "jensensAlpha": to_float(metrics.get('Jensens_Alpha')),
                "periodInfo": metrics.get('Period_Info'),
                
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
                "ytdFinancingCost": to_float(metrics.get('YTD_Financing_Cost')),
                "annualFinancingCost": to_float(metrics.get('Annual_Financing_Cost')),
                
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
            "analyticsHistory": []
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
                "corr_surges": momentum.get('corr_surges', [])
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
            last_price = None
            volatility = None
            currency = ticker_config.get('currency', 'USD') if ticker_config else 'USD'
            sector = ticker_config.get('sector', 'Unknown') if ticker_config else 'Unknown'
            
            # Get last price from raw_prices (original currency)
            if ticker in raw_prices.columns:
                raw_series = raw_prices[ticker].dropna()
                if len(raw_series) > 0:
                    last_price = float(raw_series.iloc[-1])
            
            # Volume indicator: 7d avg vs YTD avg
            vol_7d_avg = None
            vol_ytd_avg = None
            volume_indicator = None  # ratio: >1 means higher recent volume
            if volume_data is not None and ticker in volume_data.columns:
                vol_series = volume_data[ticker].dropna()
                if len(vol_series) > 7:
                    vol_7d_avg = float(vol_series.iloc[-7:].mean())
                    # YTD volume average
                    ytd_start = pd.Timestamp(datetime.now().year, 1, 1)
                    ytd_vol = vol_series[vol_series.index >= ytd_start]
                    if len(ytd_vol) > 0:
                        vol_ytd_avg = float(ytd_vol.mean())
                        if vol_ytd_avg > 0:
                            volume_indicator = vol_7d_avg / vol_ytd_avg

            if usd_prices is not None and ticker in usd_prices.columns:
                series = usd_prices[ticker].dropna()
                
                # 1D return
                if len(series) > 1:
                    current = series.iloc[-1]
                    past_1d = series.iloc[-2]
                    r1d = (current - past_1d) / past_1d if past_1d != 0 else None

                # 7D return
                if len(series) > 5:  # ~1 week of trading days
                    current = series.iloc[-1]
                    past_7d = series.iloc[-6]
                    r7d = (current - past_7d) / past_7d if past_7d != 0 else None
                
                # 1M return
                if len(series) > 21:  # ~1 month of trading days
                    current = series.iloc[-1]
                    past = series.iloc[-22]
                    r1m = (current - past) / past if past != 0 else None
                
                # Annualized volatility (std dev of daily returns * sqrt(252))
                if len(series) > 20:
                    daily_returns = series.pct_change().dropna()
                    if len(daily_returns) > 0:
                        volatility = float(daily_returns.std() * np.sqrt(252))
            
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
                "r1y": row['1Y'] if (row is not None and '1Y' in row and not pd.isna(row['1Y'])) else None,
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
                "volatility": volatility,
                "volumeIndicator": to_float(volume_indicator),
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
                    
                    beta_val = None
                    if ytd_beta_hist is not None and date in ytd_beta_hist.index:
                        beta_val = ytd_beta_hist.loc[date]
                    
                    response["ytdHistory"].append({
                        "date": date_str,
                        "portfolio": to_float(port_val),
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

