import hashlib
import html
import multiprocessing
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from brain_ingestion import chunk_text, normalize_text, stable_hash
from brain_store import BrainStore

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


DEFAULT_LIBRARY_DIR = Path(__file__).with_name("brain_library")
SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
}
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
}
DEFAULT_LOCAL_MAX_BYTES = 250 * 1024 * 1024
DEFAULT_LOCAL_MAX_PDF_PAGES = 2000
DEFAULT_LOCAL_MAX_EXTRACTED_CHARS = 5_000_000
DEFAULT_PDF_EXTRACTION_TIMEOUT_SECONDS = 90


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def custom_paths_allowed() -> bool:
    return os.environ.get("BRAIN_ALLOW_CUSTOM_LOCAL_PATHS", "").strip().lower() in {"1", "true", "yes", "on"}


def get_default_library_root() -> Path:
    configured = os.environ.get("BRAIN_LIBRARY_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_LIBRARY_DIR.resolve()


def resolve_library_root(root_path: str | None = None) -> Path:
    default_root = get_default_library_root()
    requested = Path(root_path).expanduser().resolve() if root_path else default_root

    if requested != default_root and not custom_paths_allowed():
        raise ValueError(
            "Custom local paths are disabled. Set BRAIN_LIBRARY_DIR on the backend or "
            "enable BRAIN_ALLOW_CUSTOM_LOCAL_PATHS=1 for local-only development."
        )

    requested.mkdir(parents=True, exist_ok=True)
    return requested


def indexer_status(root_path: str | None = None) -> dict[str, Any]:
    root = resolve_library_root(root_path)
    return {
        "configuredRoot": str(root),
        "exists": root.exists(),
        "customPathsAllowed": custom_paths_allowed(),
        "supportedExtensions": sorted(SUPPORTED_EXTENSIONS),
        "pdfAvailable": PdfReader is not None,
        "storageMode": "metadata_and_extracted_text_chunks",
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_text_file(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(text)


def _extract_pdf_text_direct(
    path_value: str,
    *,
    max_pages: int = DEFAULT_LOCAL_MAX_PDF_PAGES,
    max_chars: int = DEFAULT_LOCAL_MAX_EXTRACTED_CHARS,
) -> tuple[str, dict[str, Any]]:
    if PdfReader is None:
        raise RuntimeError("PDF extraction requires pypdf. Install backend requirements first.")

    # Some investor-relations PDFs have imperfect cross-reference tables. Strict
    # parsing rejects files that pypdf can still read safely in tolerant mode.
    reader = PdfReader(path_value, strict=False)
    parts: list[str] = []
    pages_read = 0
    chars = 0
    truncated = False
    for index, page in enumerate(reader.pages, start=1):
        if pages_read >= max_pages:
            truncated = True
            break
        page_text = page.extract_text() or ""
        if page_text.strip():
            page_part = f"[Page {index}]\n{page_text.strip()}"
            remaining = max_chars - chars
            if remaining <= 0:
                truncated = True
                break
            if len(page_part) > remaining:
                page_part = page_part[:remaining]
                truncated = True
            parts.append(page_part)
            chars += len(page_part)
        pages_read = index

    return "\n\n".join(parts), {
        "pages": len(reader.pages),
        "pagesRead": pages_read,
        "extractor": "pypdf",
        "truncated": truncated,
        "maxPdfPages": max_pages,
        "maxExtractedChars": max_chars,
    }


def _extract_pdf_worker(
    connection,
    path_value: str,
    max_pages: int,
    max_chars: int,
) -> None:
    """Run pypdf out of process so one bad PDF cannot stall a sync indefinitely."""
    try:
        text, metadata = _extract_pdf_text_direct(
            path_value,
            max_pages=max_pages,
            max_chars=max_chars,
        )
        connection.send({"ok": True, "text": text, "metadata": metadata})
    except Exception as exc:
        connection.send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        connection.close()


def extract_pdf_text(
    path: Path,
    *,
    max_pages: int = DEFAULT_LOCAL_MAX_PDF_PAGES,
    max_chars: int = DEFAULT_LOCAL_MAX_EXTRACTED_CHARS,
    timeout_seconds: int | None = None,
) -> tuple[str, dict[str, Any]]:
    if PdfReader is None:
        raise RuntimeError("PDF extraction requires pypdf. Install backend requirements first.")

    configured_timeout = _env_int("BRAIN_PDF_EXTRACTION_TIMEOUT_SECONDS", DEFAULT_PDF_EXTRACTION_TIMEOUT_SECONDS)
    timeout = max(5, int(timeout_seconds or configured_timeout))
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_extract_pdf_worker,
        args=(child_connection, str(path), max_pages, max_chars),
        daemon=True,
    )
    process.start()
    child_connection.close()

    try:
        if not parent_connection.poll(timeout):
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            raise RuntimeError(f"PDF extraction timed out after {timeout} seconds")

        result = parent_connection.recv()
    finally:
        parent_connection.close()
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    if not result.get("ok"):
        raise RuntimeError(f"PDF extraction failed: {result.get('error') or 'unknown error'}")

    return str(result["text"]), dict(result["metadata"])


def extract_docx_text(
    path: Path,
    *,
    max_chars: int = DEFAULT_LOCAL_MAX_EXTRACTED_CHARS,
) -> tuple[str, dict[str, Any]]:
    paragraphs: list[str] = []
    chars = 0
    truncated = False
    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as document:
            tree = ElementTree.parse(document)

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in tree.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            remaining = max_chars - chars
            if remaining <= 0:
                truncated = True
                break
            if len(text) > remaining:
                text = text[:remaining]
                truncated = True
            paragraphs.append(text)
            chars += len(text)

    return "\n\n".join(paragraphs), {
        "paragraphs": len(paragraphs),
        "extractor": "docx-xml",
        "truncated": truncated,
        "maxExtractedChars": max_chars,
    }


def extract_file_text(
    path: Path,
    *,
    extension: str | None = None,
    max_pdf_pages: int = DEFAULT_LOCAL_MAX_PDF_PAGES,
    max_extracted_chars: int = DEFAULT_LOCAL_MAX_EXTRACTED_CHARS,
) -> tuple[str, dict[str, Any]]:
    suffix = (extension or path.suffix).lower()
    metadata: dict[str, Any] = {"extractor": "plain-text"}

    if suffix in TEXT_EXTENSIONS:
        text = read_text_file(path)
        return text[:max_extracted_chars], {
            **metadata,
            "truncated": len(text) > max_extracted_chars,
            "maxExtractedChars": max_extracted_chars,
        }
    if suffix in {".html", ".htm"}:
        text = strip_html(read_text_file(path))
        return text[:max_extracted_chars], {
            "extractor": "html-stripper",
            "truncated": len(text) > max_extracted_chars,
            "maxExtractedChars": max_extracted_chars,
        }
    if suffix == ".pdf":
        return extract_pdf_text(path, max_pages=max_pdf_pages, max_chars=max_extracted_chars)
    if suffix == ".docx":
        return extract_docx_text(path, max_chars=max_extracted_chars)

    raise RuntimeError(f"Unsupported file extension: {suffix}")


def detect_supported_extension(path: Path) -> str | None:
    """Infer a supported format for synced Drive files without an extension."""
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS:
        return suffix

    try:
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        return None
    if header.startswith(b"%PDF-"):
        return ".pdf"
    if header.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as archive:
                if "word/document.xml" in archive.namelist():
                    return ".docx"
        except (OSError, zipfile.BadZipFile):
            return None
    return None


def iter_library_files(root: Path, extensions: set[str], limit_files: int) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for current_root, dirs, names in os.walk(root):
        dirs[:] = [
            directory
            for directory in dirs
            if directory not in SKIP_DIRS and not directory.startswith(".")
        ]

        for name in names:
            if name.startswith("."):
                continue
            path = Path(current_root) / name
            extension = detect_supported_extension(path)
            if extension not in extensions:
                continue
            files.append((path, extension))
            if len(files) >= limit_files:
                return files

    return sorted(files, key=lambda item: item[0].as_posix().lower())


def source_preview(path: Path, relative_path: str, text: str) -> str:
    preview = normalize_text(text)[:4000]
    return (
        f"File: {path.name}\n"
        f"Relative path: {relative_path}\n"
        f"Indexed preview:\n\n{preview}"
    ).strip()


def index_local_library(
    store: BrainStore,
    *,
    root_path: str | None = None,
    extensions: list[str] | None = None,
    limit_files: int = 250,
    max_bytes: int = DEFAULT_LOCAL_MAX_BYTES,
    max_pdf_pages: int | None = None,
    max_extracted_chars: int | None = None,
    changed_files_limit: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    root = resolve_library_root(root_path)
    allowed_extensions = {
        ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        for ext in (extensions or sorted(SUPPORTED_EXTENSIONS))
    }
    allowed_extensions = allowed_extensions.intersection(SUPPORTED_EXTENSIONS)
    if not allowed_extensions:
        raise ValueError("No supported extensions selected")

    limit_files = max(1, min(int(limit_files), 5000))
    max_bytes = max(1024, int(max_bytes or _env_int("BRAIN_LOCAL_MAX_BYTES", DEFAULT_LOCAL_MAX_BYTES)))
    max_pdf_pages = max(1, min(int(max_pdf_pages or _env_int("BRAIN_LOCAL_MAX_PDF_PAGES", DEFAULT_LOCAL_MAX_PDF_PAGES)), 10000))
    max_extracted_chars = max(20_000, min(int(max_extracted_chars or _env_int("BRAIN_LOCAL_MAX_EXTRACTED_CHARS", DEFAULT_LOCAL_MAX_EXTRACTED_CHARS)), 25_000_000))
    changed_files_limit = (
        max(1, min(int(changed_files_limit), 5000))
        if changed_files_limit is not None
        else None
    )
    indexed_at = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    changed_files_started = 0
    existing_sources = store.list_file_source_lookup() if hasattr(store, "list_file_source_lookup") else []
    sources_by_identity = {
        str((source.get("metadata") or {}).get("fileIdentity") or ""): source
        for source in existing_sources
        if (source.get("metadata") or {}).get("fileIdentity")
    }
    sources_by_hash = {
        str((source.get("metadata") or {}).get("fileHash") or ""): source
        for source in existing_sources
        if (source.get("metadata") or {}).get("fileHash")
    }

    for path, detected_extension in iter_library_files(root, allowed_extensions, limit_files):
        relative_path = path.relative_to(root).as_posix()
        try:
            stat = path.stat()
            if stat.st_size > max_bytes:
                results.append({
                    "path": str(path),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": f"File exceeds maxBytes ({stat.st_size} > {max_bytes})",
                    "bytes": stat.st_size,
                })
                continue

            file_identity = f"local-file:{str(path.resolve()).lower()}"
            file_hash = file_sha256(path)
            existing = sources_by_identity.get(file_identity)
            existing_hash = (existing or {}).get("metadata", {}).get("fileHash") if existing else None
            if existing and existing_hash == file_hash and not force:
                results.append({
                    "path": str(path),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "unchanged",
                    "sourceId": existing["id"],
                    "bytes": stat.st_size,
                })
                continue

            matching_source = sources_by_hash.get(file_hash) if not existing else None
            if matching_source:
                results.append({
                    "path": str(path),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "duplicate of indexed file content",
                    "sourceId": matching_source["id"],
                    "bytes": stat.st_size,
                })
                continue

            if changed_files_limit is not None and changed_files_started >= changed_files_limit:
                results.append({
                    "path": str(path),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "deferred to next batch",
                    "bytes": stat.st_size,
                })
                continue

            changed_files_started += 1
            extracted_text, extraction_metadata = extract_file_text(
                path,
                extension=detected_extension,
                max_pdf_pages=max_pdf_pages,
                max_extracted_chars=max_extracted_chars,
            )
            clean_text = normalize_text(extracted_text)
            if not clean_text:
                results.append({
                    "path": str(path),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "no extractable text",
                    "bytes": stat.st_size,
                })
                continue

            title_source = path.stem if path.suffix.lower() == detected_extension else path.name
            title = title_source.replace("_", " ").replace("-", " ").strip() or path.name
            title = title[:300]
            tags = ["local-file", detected_extension.lstrip(".")]
            metadata = {
                "sourceType": "local_file",
                "fileIdentity": file_identity,
                "fileHash": file_hash,
                "fileName": path.name,
                "relativePath": relative_path,
                "absolutePath": str(path.resolve()),
                "extension": detected_extension,
                "extensionDetected": path.suffix.lower() != detected_extension,
                "bytes": stat.st_size,
                "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "indexedAt": indexed_at,
                "storageMode": "source_preview_chunks_full_text",
                "localWorkerLimits": {
                    "maxBytes": max_bytes,
                    "maxPdfPages": max_pdf_pages,
                    "maxExtractedChars": max_extracted_chars,
                },
                **extraction_metadata,
            }
            source, changed = store.upsert_file_source(
                title=title,
                body=source_preview(path, relative_path, clean_text),
                tags=tags,
                metadata=metadata,
                force=force,
            )

            chunks = chunk_text(
                clean_text,
                source_title=title,
                tags=tags,
                chunk_words=900,
                overlap_words=120,
            )
            for chunk in chunks:
                chunk_metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
                chunk["metadata"] = {
                    **chunk_metadata,
                    "fileIdentity": file_identity,
                    "relativePath": relative_path,
                    "sourceHash": file_hash,
                }
                chunk["contentHash"] = stable_hash(file_hash, str(chunk["ordinal"]), chunk["body"])

            saved_chunks = store.add_chunks(source["id"], chunks) if changed else []
            results.append({
                "path": str(path),
                "relativePath": relative_path,
                "status": "indexed",
                "reason": "updated" if existing else "created",
                "sourceId": source["id"],
                "chunks": len(saved_chunks),
                "bytes": stat.st_size,
            })
        except Exception as exc:
            results.append({
                "path": str(path),
                "relativePath": relative_path,
                "status": "error",
                "reason": str(exc),
            })

    summary = {
        "found": len(results),
        "indexed": sum(1 for item in results if item["status"] == "indexed"),
        "skipped": sum(1 for item in results if item["status"] == "skipped"),
        "errors": sum(1 for item in results if item["status"] == "error"),
        "deferred": sum(1 for item in results if item.get("reason") == "deferred to next batch"),
        "maxBytes": max_bytes,
        "maxPdfPages": max_pdf_pages,
        "maxExtractedChars": max_extracted_chars,
    }
    return {
        "root": str(root),
        "extensions": sorted(allowed_extensions),
        "summary": summary,
        "results": results,
        "counts": store.counts(),
    }
