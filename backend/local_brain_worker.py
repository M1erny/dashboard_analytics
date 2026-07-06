import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from brain_indexer import (
    DEFAULT_LOCAL_MAX_BYTES,
    DEFAULT_LOCAL_MAX_EXTRACTED_CHARS,
    DEFAULT_LOCAL_MAX_PDF_PAGES,
    index_local_library,
    indexer_status,
)
from brain_store import create_brain_store
from gemini_client import GeminiClient, load_backend_env


DEFAULT_EMBED_BATCH_SIZE = 10
DEFAULT_EMBED_MAX_CHUNKS = 250


def parse_bytes(value: str | int | None, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value

    raw = str(value).strip().lower().replace(" ", "")
    if not raw:
        return default

    match = re.fullmatch(r"(\d+(?:\.\d+)?)(b|kb|mb|gb)?", raw)
    if not match:
        raise argparse.ArgumentTypeError(f"Invalid byte size: {value}")

    number = float(match.group(1))
    unit = match.group(2) or "b"
    multiplier = {
        "b": 1,
        "kb": 1024,
        "mb": 1024 * 1024,
        "gb": 1024 * 1024 * 1024,
    }[unit]
    return max(1, int(number * multiplier))


def clean_error(error: Exception | str) -> str:
    text = str(error)
    text = re.sub(r"postgres(?:ql)?://[^\s]+", "postgresql://<redacted>", text)
    text = re.sub(r"key=([^&\s]+)", "key=<redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(api[_-]?key|secret|token)=([^\s&]+)", r"\1=<redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def require_cloud_database(allow_sqlite: bool) -> None:
    database_url = os.environ.get("BRAIN_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if database_url or allow_sqlite:
        return

    raise RuntimeError(
        "Set DATABASE_URL or BRAIN_DATABASE_URL before running the local brain worker. "
        "Use --allow-sqlite only for local testing; Supabase/Postgres is required for the cloud dashboard."
    )


def default_root() -> str | None:
    return (
        os.environ.get("BRAIN_LOCAL_LIBRARY_DIR")
        or os.environ.get("BRAIN_LIBRARY_DIR")
    )


def run_index(args: argparse.Namespace, store) -> dict[str, Any]:
    root = args.root or default_root()
    if not root:
        raise RuntimeError("Set --root or BRAIN_LOCAL_LIBRARY_DIR to your synced Google Drive folder.")

    os.environ["BRAIN_ALLOW_CUSTOM_LOCAL_PATHS"] = "1"
    result = index_local_library(
        store,
        root_path=root,
        extensions=args.extensions,
        limit_files=args.limit_files,
        max_bytes=args.max_bytes,
        max_pdf_pages=args.max_pdf_pages,
        max_extracted_chars=args.max_extracted_chars,
        changed_files_limit=args.changed_files_limit,
        force=args.force,
    )
    return result


def run_embedding_backfill(args: argparse.Namespace, store) -> dict[str, Any]:
    client = GeminiClient()
    if not client.configured:
        return {
            "embedded": 0,
            "errors": [{
                "id": None,
                "title": "configuration",
                "error": "Set GOOGLE_AI_API_KEY or GEMINI_API_KEY before embedding chunks.",
            }],
            "stopped": "missing_api_key",
            "model": client.embedding_model,
            "seconds": 0,
            "embeddings": store.embedding_stats() if hasattr(store, "embedding_stats") else None,
        }

    max_chunks = max(1, int(args.embed_max_chunks))
    batch_size = max(1, min(int(args.embed_batch_size), 50))
    sleep_seconds = max(0.0, float(args.embed_sleep))
    embedded = 0
    errors: list[dict[str, Any]] = []
    started = time.perf_counter()

    while embedded < max_chunks:
        limit = min(batch_size, max_chunks - embedded)
        chunks = store.list_chunks_for_embedding(limit=limit, force=args.embed_force)
        if not chunks:
            break

        made_progress = False
        for chunk in chunks:
            if embedded >= max_chunks:
                break
            chunk_id = int(chunk["id"])
            title = str(chunk.get("title") or f"chunk {chunk_id}")
            body = str(chunk.get("body") or "")
            try:
                embedding = client.embed_text(body, task_type="RETRIEVAL_DOCUMENT")
                store.update_chunk_embedding(
                    chunk_id,
                    embedding_model=client.embedding_model,
                    embedding=embedding,
                )
                embedded += 1
                made_progress = True
                if not args.quiet:
                    print(f"Embedded {embedded}/{max_chunks}: {title[:110]}")
                if sleep_seconds:
                    time.sleep(sleep_seconds)
            except Exception as exc:
                errors.append({
                    "id": chunk_id,
                    "title": title[:160],
                    "error": clean_error(exc),
                })
                if not args.quiet:
                    print(f"Embedding failed for {chunk_id}: {clean_error(exc)}", file=sys.stderr)
                if len(errors) >= args.max_errors:
                    return {
                        "embedded": embedded,
                        "errors": errors,
                        "stopped": "too_many_errors",
                        "model": client.embedding_model,
                        "seconds": round(time.perf_counter() - started, 2),
                        "embeddings": store.embedding_stats() if hasattr(store, "embedding_stats") else None,
                    }

        if not made_progress and errors:
            break

    return {
        "embedded": embedded,
        "errors": errors,
        "stopped": None,
        "model": client.embedding_model,
        "seconds": round(time.perf_counter() - started, 2),
        "embeddings": store.embedding_stats() if hasattr(store, "embedding_stats") else None,
    }


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    load_backend_env()
    require_cloud_database(args.allow_sqlite)

    store = create_brain_store()
    output: dict[str, Any] = {"mode": args.mode}

    if args.mode == "status":
        os.environ["BRAIN_ALLOW_CUSTOM_LOCAL_PATHS"] = "1"
        root = args.root or default_root()
        output["indexer"] = indexer_status(root)
        output["counts"] = store.counts()
        if hasattr(store, "embedding_stats"):
            output["embeddings"] = store.embedding_stats()
        return output

    if args.mode in {"index", "all"}:
        output["index"] = run_index(args, store)

    if args.mode in {"embed", "all"}:
        output["embedding"] = run_embedding_backfill(args, store)

    output["counts"] = store.counts()
    if hasattr(store, "embedding_stats"):
        output["embeddings"] = store.embedding_stats()
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local investment brain worker: index a synced Drive folder into Supabase and backfill embeddings.",
    )
    parser.add_argument("--mode", choices=["all", "index", "embed", "status"], default="all")
    parser.add_argument("--root", default=None, help="Local synced Google Drive folder path.")
    parser.add_argument("--extensions", nargs="*", default=None, help="Optional extensions, e.g. .pdf .docx .md")
    parser.add_argument("--limit-files", type=int, default=5000)
    parser.add_argument("--changed-files-limit", type=int, default=25)
    parser.add_argument("--max-bytes", type=lambda value: parse_bytes(value, DEFAULT_LOCAL_MAX_BYTES), default=DEFAULT_LOCAL_MAX_BYTES)
    parser.add_argument("--max-pdf-pages", type=int, default=DEFAULT_LOCAL_MAX_PDF_PAGES)
    parser.add_argument("--max-extracted-chars", type=int, default=DEFAULT_LOCAL_MAX_EXTRACTED_CHARS)
    parser.add_argument("--force", action="store_true", help="Re-index files even if their hash has not changed.")
    parser.add_argument("--embed-max-chunks", type=int, default=DEFAULT_EMBED_MAX_CHUNKS)
    parser.add_argument("--embed-batch-size", type=int, default=DEFAULT_EMBED_BATCH_SIZE)
    parser.add_argument("--embed-sleep", type=float, default=0.05, help="Pause between embedding calls.")
    parser.add_argument("--embed-force", action="store_true", help="Re-embed existing embedded chunks too.")
    parser.add_argument("--max-errors", type=int, default=3)
    parser.add_argument("--watch-minutes", type=float, default=0.0, help="Repeat forever every N minutes.")
    parser.add_argument("--allow-sqlite", action="store_true", help="Allow local SQLite fallback for testing only.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.watch_minutes <= 0:
            result = run_once(args)
            print_json(result) if args.json else print_human(result)
            return 0

        interval = max(60.0, args.watch_minutes * 60.0)
        while True:
            result = run_once(args)
            print_json(result) if args.json else print_human(result)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped.")
        return 130
    except Exception as exc:
        print(f"Local brain worker failed: {clean_error(exc)}", file=sys.stderr)
        return 1


def print_human(result: dict[str, Any]) -> None:
    print(f"Brain worker mode: {result.get('mode')}")

    index = result.get("index")
    if isinstance(index, dict):
        summary = index.get("summary", {})
        print(
            "Indexed: "
            f"{summary.get('indexed', 0)} indexed, "
            f"{summary.get('skipped', 0)} skipped, "
            f"{summary.get('errors', 0)} errors, "
            f"{summary.get('deferred', 0)} deferred."
        )

    embedding = result.get("embedding")
    if isinstance(embedding, dict):
        print(
            "Embeddings: "
            f"{embedding.get('embedded', 0)} embedded, "
            f"{len(embedding.get('errors', []) or [])} errors, "
            f"model {embedding.get('model') or 'unknown'}."
        )
        for error in (embedding.get("errors") or [])[:3]:
            print(f"  error {error.get('id')}: {error.get('error')}")

    counts = result.get("counts") or {}
    if counts:
        print(
            "Store: "
            f"{counts.get('sources', 0)} sources, "
            f"{counts.get('chunks', 0)} chunks, "
            f"{counts.get('memories', 0)} memories."
        )

    embeddings = result.get("embeddings") or {}
    if embeddings:
        print(
            "Coverage: "
            f"{embeddings.get('embedded', 0)}/{embeddings.get('total', 0)} chunks embedded."
        )


if __name__ == "__main__":
    raise SystemExit(main())
