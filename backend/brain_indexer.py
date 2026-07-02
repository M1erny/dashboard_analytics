import hashlib
import html
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


def extract_pdf_text(path: Path) -> tuple[str, dict[str, Any]]:
    if PdfReader is None:
        raise RuntimeError("PDF extraction requires pypdf. Install backend requirements first.")

    reader = PdfReader(str(path))
    parts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(f"[Page {index}]\n{page_text.strip()}")

    return "\n\n".join(parts), {"pages": len(reader.pages), "extractor": "pypdf"}


def extract_docx_text(path: Path) -> tuple[str, dict[str, Any]]:
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as document:
            tree = ElementTree.parse(document)

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in tree.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs), {"paragraphs": len(paragraphs), "extractor": "docx-xml"}


def extract_file_text(path: Path) -> tuple[str, dict[str, Any]]:
    suffix = path.suffix.lower()
    metadata: dict[str, Any] = {"extractor": "plain-text"}

    if suffix in TEXT_EXTENSIONS:
        return read_text_file(path), metadata
    if suffix in {".html", ".htm"}:
        return strip_html(read_text_file(path)), {"extractor": "html-stripper"}
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix == ".docx":
        return extract_docx_text(path)

    raise RuntimeError(f"Unsupported file extension: {suffix}")


def iter_library_files(root: Path, extensions: set[str], limit_files: int) -> list[Path]:
    files: list[Path] = []
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
            if path.suffix.lower() not in extensions:
                continue
            files.append(path)
            if len(files) >= limit_files:
                return files

    return sorted(files)


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
    max_bytes: int = 50 * 1024 * 1024,
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
    max_bytes = max(1024, int(max_bytes))
    indexed_at = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []

    for path in iter_library_files(root, allowed_extensions, limit_files):
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
            existing = store.get_file_source_by_identity(file_identity)
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

            extracted_text, extraction_metadata = extract_file_text(path)
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

            title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
            title = title[:300]
            tags = ["local-file", path.suffix.lower().lstrip(".")]
            metadata = {
                "sourceType": "local_file",
                "fileIdentity": file_identity,
                "fileHash": file_hash,
                "fileName": path.name,
                "relativePath": relative_path,
                "absolutePath": str(path.resolve()),
                "extension": path.suffix.lower(),
                "bytes": stat.st_size,
                "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "indexedAt": indexed_at,
                "storageMode": "source_preview_chunks_full_text",
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
    }
    return {
        "root": str(root),
        "extensions": sorted(allowed_extensions),
        "summary": summary,
        "results": results,
        "counts": store.counts(),
    }
