import hashlib
import html
import io
import os
import re
import zipfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

import httpx

from brain_ingestion import chunk_text, normalize_text, stable_hash
from brain_indexer import SUPPORTED_EXTENSIONS, strip_html

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
REFRESH_TOKEN_SETTING = "google_drive_refresh_token"

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_WORKSPACE_EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
}
MIME_EXTENSION_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "application/json": ".json",
    "application/x-ndjson": ".jsonl",
    "text/html": ".html",
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


def parse_drive_folder_id(value: str | None = None) -> str | None:
    raw = (value or os.environ.get("GOOGLE_DRIVE_FOLDER_ID") or "").strip()
    if not raw:
        return None

    match = re.search(r"/folders/([^/?#]+)", raw)
    if match:
        return match.group(1)

    return raw.split("?")[0].strip().strip("/")


def drive_folder_url(folder_id: str | None) -> str | None:
    return f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else None


def configured_redirect_uri(default_redirect_uri: str | None = None) -> str | None:
    return (
        os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
        or os.environ.get("GOOGLE_DRIVE_REDIRECT_URI")
        or default_redirect_uri
    )


def google_drive_auth_url(redirect_uri: str) -> str:
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_DRIVE_CLIENT_ID")
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID is required")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DRIVE_READONLY_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    state = os.environ.get("GOOGLE_OAUTH_STATE")
    if state:
        params["state"] = state
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def extract_docx_bytes(data: bytes) -> tuple[str, dict[str, Any]]:
    paragraphs: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        with archive.open("word/document.xml") as document:
            tree = ElementTree.parse(document)

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in tree.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs), {"paragraphs": len(paragraphs), "extractor": "docx-xml"}


def extract_pdf_bytes(data: bytes) -> tuple[str, dict[str, Any]]:
    if PdfReader is None:
        raise RuntimeError("PDF extraction requires pypdf. Install backend requirements first.")

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(f"[Page {index}]\n{page_text.strip()}")

    return "\n\n".join(parts), {"pages": len(reader.pages), "extractor": "pypdf"}


def read_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def extract_drive_file_text(data: bytes, extension: str) -> tuple[str, dict[str, Any]]:
    suffix = extension.lower()
    if suffix in TEXT_EXTENSIONS:
        return read_text_bytes(data), {"extractor": "plain-text"}
    if suffix in {".html", ".htm"}:
        return strip_html(read_text_bytes(data)), {"extractor": "html-stripper"}
    if suffix == ".pdf":
        return extract_pdf_bytes(data)
    if suffix == ".docx":
        return extract_docx_bytes(data)
    raise RuntimeError(f"Unsupported Drive file extension: {html.escape(suffix)}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extension_for_file(file: dict[str, Any]) -> str | None:
    mime_type = str(file.get("mimeType") or "")
    if mime_type in GOOGLE_WORKSPACE_EXPORTS:
        return GOOGLE_WORKSPACE_EXPORTS[mime_type][1]

    mime_extension = MIME_EXTENSION_MAP.get(mime_type)
    if mime_extension:
        return mime_extension

    name = str(file.get("name") or "")
    if "." in name:
        suffix = "." + name.rsplit(".", 1)[-1].lower()
        if suffix in SUPPORTED_EXTENSIONS:
            return suffix

    return None


class GoogleDriveClient:
    def __init__(self, store=None):
        self.store = store
        self.client_id = os.environ.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_DRIVE_CLIENT_ID")
        self.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET")
        self.env_refresh_token = os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN") or os.environ.get("GOOGLE_REFRESH_TOKEN")
        self.access_token = os.environ.get("GOOGLE_DRIVE_ACCESS_TOKEN")

    @property
    def auth_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def stored_refresh_token(self) -> str | None:
        if not self.store or not hasattr(self.store, "get_setting"):
            return None
        try:
            return self.store.get_setting(REFRESH_TOKEN_SETTING)
        except Exception:
            return None

    def refresh_token_source(self) -> str | None:
        if self.env_refresh_token:
            return "env"
        if self.stored_refresh_token():
            return "database"
        if self.access_token:
            return "access_token"
        return None

    def status(self, folder_id: str | None = None) -> dict[str, Any]:
        clean_folder_id = parse_drive_folder_id(folder_id)
        return {
            "configured": bool(clean_folder_id),
            "folderId": clean_folder_id,
            "folderUrl": drive_folder_url(clean_folder_id),
            "authConfigured": self.auth_configured,
            "connected": bool(self.refresh_token_source()),
            "tokenSource": self.refresh_token_source(),
            "scope": DRIVE_READONLY_SCOPE,
            "supportedExtensions": sorted(SUPPORTED_EXTENSIONS),
            "pdfAvailable": PdfReader is not None,
            "storageMode": "drive_metadata_extracted_text_chunks_embeddings_ready",
        }

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        if not self.auth_configured:
            raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")

        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        with httpx.Client(timeout=30) as client:
            response = client.post(GOOGLE_TOKEN_URL, data=payload)
            response.raise_for_status()
            data = response.json()

        refresh_token = data.get("refresh_token")
        if refresh_token and self.store and hasattr(self.store, "set_setting"):
            self.store.set_setting(REFRESH_TOKEN_SETTING, refresh_token)

        return {
            "hasAccessToken": bool(data.get("access_token")),
            "hasRefreshToken": bool(refresh_token),
            "expiresIn": data.get("expires_in"),
            "scope": data.get("scope"),
            "tokenType": data.get("token_type"),
        }

    def get_access_token(self) -> str:
        if self.access_token:
            return self.access_token

        refresh_token = self.env_refresh_token or self.stored_refresh_token()
        if not refresh_token:
            raise RuntimeError("Google Drive is not connected. Add GOOGLE_DRIVE_REFRESH_TOKEN or connect OAuth.")
        if not self.auth_configured:
            raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required to refresh Drive access.")

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        with httpx.Client(timeout=30) as client:
            response = client.post(GOOGLE_TOKEN_URL, data=payload)
            response.raise_for_status()
            data = response.json()

        token = data.get("access_token")
        if not token:
            raise RuntimeError("Google token refresh did not return an access token")
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    def list_children(self, folder_id: str, *, page_token: str | None = None) -> dict[str, Any]:
        query = f"'{folder_id}' in parents and trashed = false"
        params = {
            "q": query,
            "pageSize": "100",
            "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,webViewLink)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token

        with httpx.Client(timeout=60) as client:
            response = client.get(f"{DRIVE_API_BASE}/files", headers=self._headers(), params=params)
            response.raise_for_status()
            return response.json()

    def iter_files(self, folder_id: str, *, limit_files: int) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        folders: list[tuple[str, str]] = [(folder_id, "")]
        seen_folders = set()

        while folders and len(files) < limit_files:
            current_folder_id, current_path = folders.pop(0)
            if current_folder_id in seen_folders:
                continue
            seen_folders.add(current_folder_id)

            page_token = None
            while len(files) < limit_files:
                payload = self.list_children(current_folder_id, page_token=page_token)
                for item in payload.get("files", []):
                    name = str(item.get("name") or "Untitled")
                    relative_path = f"{current_path}/{name}".strip("/")
                    item["relativePath"] = relative_path

                    if item.get("mimeType") == FOLDER_MIME_TYPE:
                        folders.append((item["id"], relative_path))
                        continue

                    files.append(item)
                    if len(files) >= limit_files:
                        break

                page_token = payload.get("nextPageToken")
                if not page_token:
                    break

        return files

    def download_file(self, file: dict[str, Any]) -> tuple[bytes, str, dict[str, Any]]:
        file_id = file["id"]
        mime_type = str(file.get("mimeType") or "")
        extension = extension_for_file(file)
        if not extension or extension not in SUPPORTED_EXTENSIONS:
            raise RuntimeError(f"Unsupported Drive file type: {mime_type or file.get('name')}")

        if mime_type in GOOGLE_WORKSPACE_EXPORTS:
            export_mime, export_extension = GOOGLE_WORKSPACE_EXPORTS[mime_type]
            extension = export_extension
            url = f"{DRIVE_API_BASE}/files/{file_id}/export"
            params = {"mimeType": export_mime}
            download_mode = "export"
        else:
            url = f"{DRIVE_API_BASE}/files/{file_id}"
            params = {"alt": "media", "supportsAllDrives": "true"}
            download_mode = "download"

        with httpx.Client(timeout=120, follow_redirects=True) as client:
            response = client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            return response.content, extension, {"downloadMode": download_mode}


def source_preview(file: dict[str, Any], text: str) -> str:
    preview = normalize_text(text)[:4000]
    return (
        f"Drive file: {file.get('name')}\n"
        f"Relative path: {file.get('relativePath')}\n"
        f"Google Drive URL: {file.get('webViewLink') or ''}\n"
        f"Indexed preview:\n\n{preview}"
    ).strip()


def index_drive_folder(
    store,
    *,
    folder_id: str | None = None,
    limit_files: int = 100,
    max_bytes: int = 5 * 1024 * 1024,
    force: bool = False,
    changed_files_limit: int | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    clean_folder_id = parse_drive_folder_id(folder_id)
    if not clean_folder_id:
        raise ValueError("GOOGLE_DRIVE_FOLDER_ID or folderId is required")

    client = GoogleDriveClient(store=store)
    limit_files = max(1, min(int(limit_files), 2000))
    max_bytes = max(1024, int(max_bytes))
    changed_files_limit = (
        max(1, min(int(changed_files_limit), 100))
        if changed_files_limit is not None
        else None
    )
    indexed_at = datetime.now(timezone.utc).isoformat()

    results: list[dict[str, Any]] = []
    files = client.iter_files(clean_folder_id, limit_files=limit_files)
    changed_files_started = 0

    def emit_progress(current_file: str | None = None) -> None:
        if not progress_callback:
            return
        summary = {
            "found": len(results),
            "indexed": sum(1 for item in results if item["status"] == "indexed"),
            "skipped": sum(1 for item in results if item["status"] == "skipped"),
            "errors": sum(1 for item in results if item["status"] == "error"),
            "deferred": sum(1 for item in results if item.get("reason") == "deferred to next batch"),
            "limitFiles": limit_files,
            "limitReached": len(files) >= limit_files,
        }
        progress_callback({
            "processed": len(results),
            "total": len(files),
            "currentFile": current_file,
            "summary": summary,
        })

    emit_progress()

    for file in files:
        relative_path = file.get("relativePath") or file.get("name") or file["id"]
        try:
            extension = extension_for_file(file)
            if not extension or extension not in SUPPORTED_EXTENSIONS:
                results.append({
                    "id": file["id"],
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "unsupported file type",
                    "mimeType": file.get("mimeType"),
                })
                emit_progress(relative_path)
                continue

            size = int(file.get("size") or 0)
            if size and size > max_bytes:
                results.append({
                    "id": file["id"],
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": f"File exceeds maxBytes ({size} > {max_bytes})",
                    "bytes": size,
                })
                emit_progress(relative_path)
                continue

            file_identity = f"google-drive:{file['id']}"
            revision_identity = str(file.get("md5Checksum") or file.get("modifiedTime") or "")
            existing = store.get_file_source_by_identity(file_identity)
            existing_revision = (existing or {}).get("metadata", {}).get("driveRevisionIdentity") if existing else None
            if existing and existing_revision == revision_identity and not force:
                results.append({
                    "id": file["id"],
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "unchanged",
                    "sourceId": existing["id"],
                    "bytes": size or None,
                })
                emit_progress(relative_path)
                continue

            if changed_files_limit is not None and changed_files_started >= changed_files_limit:
                results.append({
                    "id": file["id"],
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "deferred to next batch",
                    "bytes": size or None,
                })
                emit_progress(relative_path)
                continue

            changed_files_started += 1
            data, downloaded_extension, download_metadata = client.download_file(file)
            if len(data) > max_bytes:
                results.append({
                    "id": file["id"],
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": f"Downloaded file exceeds maxBytes ({len(data)} > {max_bytes})",
                    "bytes": len(data),
                })
                emit_progress(relative_path)
                continue

            file_hash = sha256_bytes(data)
            extracted_text, extraction_metadata = extract_drive_file_text(data, downloaded_extension)
            clean_text = normalize_text(extracted_text)
            if not clean_text:
                results.append({
                    "id": file["id"],
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "no extractable text",
                    "bytes": len(data),
                })
                emit_progress(relative_path)
                continue

            title = str(file.get("name") or file["id"]).rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
            title = (title or str(file.get("name") or file["id"]))[:300]
            tags = ["google-drive", downloaded_extension.lstrip(".")]
            metadata = {
                "sourceType": "google_drive",
                "fileIdentity": file_identity,
                "fileHash": file_hash,
                "driveRevisionIdentity": revision_identity or file_hash,
                "driveFileId": file["id"],
                "driveFolderId": clean_folder_id,
                "fileName": file.get("name"),
                "relativePath": relative_path,
                "extension": downloaded_extension,
                "mimeType": file.get("mimeType"),
                "bytes": len(data),
                "driveSize": size or None,
                "modifiedAt": file.get("modifiedTime"),
                "indexedAt": indexed_at,
                "webViewLink": file.get("webViewLink"),
                "storageMode": "drive_metadata_source_preview_chunks_full_text",
                **download_metadata,
                **extraction_metadata,
            }
            source, changed = store.upsert_file_source(
                title=title,
                body=source_preview(file, clean_text),
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
                    "driveFileId": file["id"],
                    "relativePath": relative_path,
                    "webViewLink": file.get("webViewLink"),
                    "sourceHash": file_hash,
                }
                chunk["contentHash"] = stable_hash(file_hash, str(chunk["ordinal"]), chunk["body"])

            saved_chunks = store.add_chunks(source["id"], chunks) if changed else []
            results.append({
                "id": file["id"],
                "name": file.get("name"),
                "relativePath": relative_path,
                "status": "indexed",
                "reason": "updated" if existing else "created",
                "sourceId": source["id"],
                "chunks": len(saved_chunks),
                "bytes": len(data),
                "webViewLink": file.get("webViewLink"),
            })
            emit_progress(relative_path)
        except Exception as exc:
            results.append({
                "id": file.get("id"),
                "name": file.get("name"),
                "relativePath": relative_path,
                "status": "error",
                "reason": str(exc),
            })
            emit_progress(relative_path)

    summary = {
        "found": len(results),
        "indexed": sum(1 for item in results if item["status"] == "indexed"),
        "skipped": sum(1 for item in results if item["status"] == "skipped"),
        "errors": sum(1 for item in results if item["status"] == "error"),
        "deferred": sum(1 for item in results if item.get("reason") == "deferred to next batch"),
        "limitFiles": limit_files,
        "limitReached": len(files) >= limit_files,
    }
    return {
        "folderId": clean_folder_id,
        "folderUrl": drive_folder_url(clean_folder_id),
        "summary": summary,
        "results": results,
        "counts": store.counts(),
    }
