import hashlib
import html
import io
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from brain_ingestion import chunk_text, normalize_text, stable_hash
from brain_indexer import SUPPORTED_EXTENSIONS, strip_html
from office_extract import _Budget, extract_docx, extract_pptx, extract_xlsx

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_SCOPES = f"{DRIVE_READONLY_SCOPE} {DRIVE_FILE_SCOPE}"
REFRESH_TOKEN_SETTING = "google_drive_refresh_token"
# Google returns the scopes it actually granted on both the code exchange and
# every refresh. Requesting DRIVE_SCOPES is not proof of holding them: a token
# authorised before drive.file was requested keeps working for reads and fails
# only at upload time, so the granted string is persisted and reported.
GRANTED_SCOPE_SETTING = "google_drive_granted_scope"

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
# Native Workspace files are exported before extraction, and the export format
# decides how much survives. A Sheet exported as text/csv keeps only the first
# tab, and a Slides deck exported as text/plain drops every speaker note, so both
# now export as OOXML and go through the extractors in office_extract.
# Drive caps an export at roughly 10 MB; anything larger is reported by
# /api/brain/drive/coverage instead of failing quietly.
GOOGLE_WORKSPACE_EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
}
MIME_EXTENSION_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
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
# Extraction is unlimited by default. A partly read document still answers
# questions, it just answers them from whichever fraction happened to fit, and it
# never says so. 0 means no limit for all three of these.
#
# The byte limit is the exception and is a real number rather than 0, because
# download_file holds the whole file in memory before extraction. An unbounded
# download would take the Render instance down instead of skipping one file.
# Anything over the limit is reported by /api/brain/drive/coverage rather than
# being silently dropped.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_PDF_PAGES = 0
DEFAULT_MAX_EXTRACTED_CHARS = 0
CONVERSATION_TRANSCRIPT_PREFIX = "investment brain/conversations/"
# Set on every file the agent import uploads, so the folder sync can tell its own
# artifacts from documents the owner put in Drive by hand.
AGENT_UPLOAD_PROPERTY = "investmentBrainAgentUpload"
AGENT_DOWNLOAD_FOLDER_NAME = "agent downloads"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_drive_folder_id(value: str | None = None) -> str | None:
    raw = (value or os.environ.get("GOOGLE_DRIVE_FOLDER_ID") or "").strip()
    if not raw:
        return None

    match = re.search(r"/folders/([^/?#]+)", raw)
    if match:
        return match.group(1)

    return raw.split("?")[0].strip().strip("/")


def is_brain_conversation_transcript(file: dict[str, Any]) -> bool:
    relative_path = str(file.get("relativePath") or file.get("name") or "").replace("\\", "/").strip("/").casefold()
    return relative_path.startswith(CONVERSATION_TRANSCRIPT_PREFIX)


def is_agent_managed_upload(file: dict[str, Any]) -> bool:
    """True for artifacts the agent import wrote to Drive and already indexed.

    Every agent import indexes its text directly under an agent-url identity, so
    letting the folder sync index the same file again under a google-drive
    identity puts the same passage in the retrieval set twice. Two signals are
    checked because neither alone is complete: the app property is exact but only
    present on uploads made after it was introduced, and the folder name catches
    everything written before that.
    """
    properties = file.get("appProperties")
    if isinstance(properties, dict) and str(properties.get(AGENT_UPLOAD_PROPERTY) or "").strip():
        return True
    relative_path = str(file.get("relativePath") or "").replace("\\", "/").strip("/").casefold()
    segments = relative_path.split("/")[:-1]
    return AGENT_DOWNLOAD_FOLDER_NAME in segments


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
        "scope": DRIVE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    state = os.environ.get("GOOGLE_OAUTH_STATE")
    if state:
        params["state"] = state
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def extract_docx_bytes(data: bytes, *, max_chars: int = DEFAULT_MAX_EXTRACTED_CHARS) -> tuple[str, dict[str, Any]]:
    return extract_docx(data, max_chars=max_chars)


def extract_pdf_bytes(
    data: bytes,
    *,
    max_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_chars: int = DEFAULT_MAX_EXTRACTED_CHARS,
) -> tuple[str, dict[str, Any]]:
    if PdfReader is None:
        raise RuntimeError("PDF extraction requires pypdf. Install backend requirements first.")

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    pages_read = 0
    budget = _Budget(max_chars)
    page_limit = max_pages if max_pages and max_pages > 0 else None
    truncated = False
    for index, page in enumerate(reader.pages, start=1):
        if page_limit is not None and pages_read >= page_limit:
            truncated = True
            break
        page_text = page.extract_text() or ""
        if page_text.strip():
            allowed = budget.take(f"[Page {index}]\n{page_text.strip()}")
            if allowed is None:
                break
            parts.append(allowed)
        pages_read = index

    truncated = truncated or budget.truncated
    return "\n\n".join(parts), {
        "pages": len(reader.pages),
        "pagesRead": pages_read,
        "extractor": "pypdf",
        "truncated": truncated,
        "maxPdfPages": max_pages,
        "maxExtractedChars": max_chars,
    }


def _clip(text: str, max_chars: int) -> str:
    """Apply a character cap, where 0 or less means no cap."""
    if max_chars and max_chars > 0:
        return text[:max_chars]
    return text


def read_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1250", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def extract_drive_file_text(
    data: bytes,
    extension: str,
    *,
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_extracted_chars: int = DEFAULT_MAX_EXTRACTED_CHARS,
) -> tuple[str, dict[str, Any]]:
    suffix = extension.lower()
    if suffix in TEXT_EXTENSIONS:
        text = read_text_bytes(data)
        kept = _clip(text, max_extracted_chars)
        return kept, {
            "extractor": "plain-text",
            "truncated": len(kept) < len(text),
            "maxExtractedChars": max_extracted_chars,
        }
    if suffix in {".html", ".htm"}:
        text = strip_html(read_text_bytes(data))
        kept = _clip(text, max_extracted_chars)
        return kept, {
            "extractor": "html-stripper",
            "truncated": len(kept) < len(text),
            "maxExtractedChars": max_extracted_chars,
        }
    if suffix == ".pdf":
        return extract_pdf_bytes(data, max_pages=max_pdf_pages, max_chars=max_extracted_chars)
    if suffix == ".docx":
        return extract_docx_bytes(data, max_chars=max_extracted_chars)
    if suffix == ".xlsx":
        return extract_xlsx(data, max_chars=max_extracted_chars)
    if suffix == ".pptx":
        return extract_pptx(data, max_chars=max_extracted_chars)
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

    def granted_scope(self) -> str | None:
        if not self.store or not hasattr(self.store, "get_setting"):
            return None
        try:
            return self.store.get_setting(GRANTED_SCOPE_SETTING)
        except Exception:
            return None

    def _record_granted_scope(self, scope: Any) -> None:
        clean = str(scope or "").strip()
        if not clean or not self.store or not hasattr(self.store, "set_setting"):
            return
        try:
            self.store.set_setting(GRANTED_SCOPE_SETTING, clean)
        except Exception:
            # Losing the record only costs visibility; never fail a token call for it.
            pass

    def scope_status(self) -> dict[str, Any]:
        granted = self.granted_scope()
        scopes = (granted or "").split()
        return {
            "requestedScope": DRIVE_SCOPES,
            "grantedScope": granted,
            # None means "Google has not told us yet", which is not the same as
            # "read only" - the UI must not claim saving is broken on a guess.
            "writeScope": (DRIVE_FILE_SCOPE in scopes) if granted else None,
        }

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
            "scope": DRIVE_SCOPES,
            **self.scope_status(),
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
        self._record_granted_scope(data.get("scope"))

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
            if response.is_error:
                try:
                    error_payload = response.json()
                except ValueError:
                    error_payload = {}
                error_code = str(error_payload.get("error") or "").strip()
                error_description = str(error_payload.get("error_description") or "").strip()
                if error_code == "invalid_grant":
                    raise RuntimeError(
                        "Google rejected the stored Drive refresh token (invalid_grant). "
                        "Remove GOOGLE_DRIVE_REFRESH_TOKEN / GOOGLE_REFRESH_TOKEN from Render if set, "
                        "then reconnect Drive using the same Google OAuth client."
                    )
                detail = ": ".join(part for part in (error_code, error_description) if part)
                raise RuntimeError(f"Google could not refresh the Drive access token{f' ({detail})' if detail else ''}.")
            data = response.json()

        token = data.get("access_token")
        if not token:
            raise RuntimeError("Google token refresh did not return an access token")
        self._record_granted_scope(data.get("scope"))
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    @staticmethod
    def _escape_drive_query(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def list_children(self, folder_id: str, *, page_token: str | None = None) -> dict[str, Any]:
        query = f"'{folder_id}' in parents and trashed = false"
        params = {
            "q": query,
            "pageSize": "100",
            "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,createdTime,modifiedTime,webViewLink,appProperties)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token

        with httpx.Client(timeout=60) as client:
            response = client.get(f"{DRIVE_API_BASE}/files", headers=self._headers(), params=params)
            response.raise_for_status()
            return response.json()

    def find_child_folder(self, parent_id: str, name: str) -> dict[str, Any] | None:
        safe_name = self._escape_drive_query(name)
        safe_parent = self._escape_drive_query(parent_id)
        query = (
            f"'{safe_parent}' in parents and trashed = false "
            f"and mimeType = '{FOLDER_MIME_TYPE}' and name = '{safe_name}'"
        )
        params = {
            "q": query,
            "pageSize": "10",
            "fields": "files(id,name,mimeType,webViewLink)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        with httpx.Client(timeout=60) as client:
            response = client.get(f"{DRIVE_API_BASE}/files", headers=self._headers(), params=params)
            response.raise_for_status()
            files = response.json().get("files", [])
        return files[0] if files else None

    def find_file_by_app_property(self, parent_id: str, key: str, value: str) -> dict[str, Any] | None:
        files = self.list_files_by_app_property(parent_id, key, value, limit=1)
        return files[0] if files else None

    def list_files_by_app_property(
        self,
        parent_id: str,
        key: str,
        value: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        safe_parent = self._escape_drive_query(parent_id)
        safe_key = self._escape_drive_query(key)
        safe_value = self._escape_drive_query(value)
        query = (
            f"'{safe_parent}' in parents and trashed = false and "
            f"appProperties has {{ key='{safe_key}' and value='{safe_value}' }}"
        )
        params = {
            "q": query,
            "pageSize": str(max(1, min(int(limit), 100))),
            "orderBy": "modifiedTime desc",
            "fields": "files(id,name,mimeType,size,webViewLink,createdTime,modifiedTime,appProperties)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        with httpx.Client(timeout=60) as client:
            response = client.get(f"{DRIVE_API_BASE}/files", headers=self._headers(), params=params)
            response.raise_for_status()
            files = response.json().get("files", [])
        return files

    def create_folder(self, parent_id: str, name: str) -> dict[str, Any]:
        payload = {
            "name": name,
            "mimeType": FOLDER_MIME_TYPE,
            "parents": [parent_id],
        }
        params = {
            "fields": "id,name,mimeType,webViewLink",
            "supportsAllDrives": "true",
        }
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{DRIVE_API_BASE}/files",
                headers={**self._headers(), "Content-Type": "application/json"},
                params=params,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    def ensure_folder(self, parent_id: str, name: str) -> dict[str, Any]:
        existing = self.find_child_folder(parent_id, name)
        if existing:
            return existing
        return self.create_folder(parent_id, name)

    def upload_file(
        self,
        *,
        name: str,
        data: bytes,
        mime_type: str,
        folder_id: str | None = None,
        description: str | None = None,
        app_properties: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {"name": name}
        if folder_id:
            metadata["parents"] = [folder_id]
        if description:
            metadata["description"] = description[:4000]
        if app_properties:
            metadata["appProperties"] = {str(key): str(value) for key, value in app_properties.items()}

        files = {
            "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (name, data, mime_type),
        }
        params = {
            "uploadType": "multipart",
            "supportsAllDrives": "true",
            "fields": "id,name,mimeType,size,webViewLink,webContentLink,createdTime,modifiedTime",
        }
        with httpx.Client(timeout=120) as client:
            response = client.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                headers=self._headers(),
                params=params,
                files=files,
            )
            response.raise_for_status()
            return response.json()

    def update_file(
        self,
        file_id: str,
        *,
        name: str,
        data: bytes,
        mime_type: str,
        description: str | None = None,
        app_properties: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {"name": name}
        if description:
            metadata["description"] = description[:4000]
        if app_properties:
            metadata["appProperties"] = {str(key): str(value) for key, value in app_properties.items()}
        files = {
            "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (name, data, mime_type),
        }
        params = {
            "uploadType": "multipart",
            "supportsAllDrives": "true",
            "fields": "id,name,mimeType,size,webViewLink,webContentLink,createdTime,modifiedTime,appProperties",
        }
        with httpx.Client(timeout=120) as client:
            response = client.patch(
                f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
                headers=self._headers(),
                params=params,
                files=files,
            )
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

    def download_file(self, file: dict[str, Any], *, max_bytes: int | None = None) -> tuple[bytes, str, dict[str, Any]]:
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

        content = bytearray()
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            with client.stream("GET", url, headers=self._headers(), params=params) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    content.extend(chunk)
                    if max_bytes is not None and len(content) > max_bytes:
                        raise RuntimeError(f"Downloaded file exceeds maxBytes ({len(content)} > {max_bytes})")
        return bytes(content), extension, {"downloadMode": download_mode}


def source_preview(file: dict[str, Any], text: str) -> str:
    preview = normalize_text(text)[:4000]
    return (
        f"Drive file: {file.get('name')}\n"
        f"Relative path: {file.get('relativePath')}\n"
        f"Google Drive URL: {file.get('webViewLink') or ''}\n"
        f"Indexed preview:\n\n{preview}"
    ).strip()


def _canonical_drive_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _drive_match_parts(relative_path: Any, extension: Any = None) -> tuple[str, str, str, str]:
    clean_path = str(relative_path or "").replace("\\", "/").strip("/")
    parts = [part for part in clean_path.split("/") if part]
    file_name = parts[-1] if parts else clean_path
    parent = "/".join(parts[:-1])
    clean_extension = str(extension or "").strip().casefold()
    if clean_extension and not clean_extension.startswith("."):
        clean_extension = f".{clean_extension}"
    if not clean_extension and "." in file_name:
        clean_extension = f".{file_name.rsplit('.', 1)[-1].casefold()}"
    stem = file_name[:-len(clean_extension)] if clean_extension and file_name.casefold().endswith(clean_extension) else file_name
    return (
        _canonical_drive_text(clean_path),
        _canonical_drive_text(parent),
        _canonical_drive_text(stem),
        clean_extension,
    )


def match_legacy_sources_to_drive(
    source_lookup: list[dict[str, Any]],
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match locally indexed Drive files to cloud IDs without re-reading their contents."""
    drive_candidates: list[dict[str, Any]] = []
    for file in files:
        file_id = str(file.get("id") or "").strip()
        relative_path = file.get("relativePath") or file.get("name")
        if not file_id or not relative_path:
            continue
        extension = extension_for_file(file)
        full_key, parent_key, stem_key, clean_extension = _drive_match_parts(relative_path, extension)
        try:
            size = int(file.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        drive_candidates.append({
            "file": file,
            "fullKey": full_key,
            "parentKey": parent_key,
            "stemKey": stem_key,
            "extension": clean_extension,
            "size": size,
        })

    matches: list[dict[str, Any]] = []
    for source in source_lookup:
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        identity = str(metadata.get("fileIdentity") or "")
        if metadata.get("driveFileId") or not (
            metadata.get("sourceType") == "local_file" or identity.startswith("local-file:")
        ):
            continue

        relative_path = metadata.get("relativePath") or metadata.get("fileName")
        if not relative_path:
            continue
        full_key, parent_key, stem_key, clean_extension = _drive_match_parts(
            relative_path,
            metadata.get("extension"),
        )
        try:
            source_size = int(metadata.get("bytes") or 0)
        except (TypeError, ValueError):
            source_size = 0

        scored: list[tuple[int, str, dict[str, Any]]] = []
        for candidate in drive_candidates:
            same_extension = bool(clean_extension and clean_extension == candidate["extension"])
            same_parent = bool(parent_key and parent_key == candidate["parentKey"])
            same_stem = bool(stem_key and stem_key == candidate["stemKey"])
            same_size = bool(source_size and source_size == candidate["size"])
            if full_key and full_key == candidate["fullKey"]:
                scored.append((100, "exact_relative_path", candidate))
            elif same_parent and same_extension and same_size:
                scored.append((90, "folder_size_extension", candidate))
            elif same_parent and same_extension and same_stem:
                scored.append((80, "folder_filename", candidate))
            elif same_extension and same_size and same_stem:
                scored.append((70, "filename_size_extension", candidate))

        if not scored:
            continue
        best_score = max(item[0] for item in scored)
        best = [item for item in scored if item[0] == best_score]
        if len(best) != 1:
            continue
        _, match_type, candidate = best[0]
        matches.append({
            "sourceId": int(source["id"]),
            "file": candidate["file"],
            "matchType": match_type,
        })
    return matches


def reconcile_legacy_source_drive_links(
    store: Any,
    files: list[dict[str, Any]],
    *,
    folder_id: str,
    linked_at: str,
) -> list[dict[str, Any]]:
    if not hasattr(store, "list_file_source_lookup") or not hasattr(store, "update_source_metadata"):
        return []

    matches = match_legacy_sources_to_drive(store.list_file_source_lookup(), files)
    linked: list[dict[str, Any]] = []
    for match in matches:
        file = match["file"]
        file_id = str(file.get("id") or "").strip()
        web_view_link = file.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
        updated = store.update_source_metadata(match["sourceId"], {
            "driveFileId": file_id,
            "driveFolderId": folder_id,
            "driveRelativePath": file.get("relativePath") or file.get("name"),
            "webViewLink": web_view_link,
            "driveLinkedAt": linked_at,
            "driveLinkMatch": match["matchType"],
        })
        if updated:
            linked.append({
                "sourceId": match["sourceId"],
                "driveFileId": file_id,
                "webViewLink": web_view_link,
                "matchType": match["matchType"],
            })
    return linked


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
    limit_files = max(1, min(int(limit_files), 20_000))
    max_bytes = max(1024, int(max_bytes or _env_int("BRAIN_DRIVE_MAX_BYTES", DEFAULT_MAX_BYTES)))
    # No upper ceiling on either extraction limit: a ceiling here would silently
    # override an operator who asked for the whole document. 0 means unlimited.
    max_pdf_pages = max(0, _env_int("BRAIN_DRIVE_MAX_PDF_PAGES", DEFAULT_MAX_PDF_PAGES) or 0)
    max_extracted_chars = max(0, _env_int("BRAIN_DRIVE_MAX_EXTRACTED_CHARS", DEFAULT_MAX_EXTRACTED_CHARS) or 0)
    changed_files_limit = (
        max(1, min(int(changed_files_limit), 20_000))
        if changed_files_limit is not None
        else None
    )
    indexed_at = datetime.now(timezone.utc).isoformat()

    results: list[dict[str, Any]] = []
    files = client.iter_files(clean_folder_id, limit_files=limit_files)
    linked_legacy_sources = reconcile_legacy_source_drive_links(
        store,
        [file for file in files if not is_brain_conversation_transcript(file)],
        folder_id=clean_folder_id,
        linked_at=indexed_at,
    )
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
            if is_brain_conversation_transcript(file):
                removed_source_id = None
                if hasattr(store, "get_file_source_by_identity") and hasattr(store, "delete_source"):
                    existing_transcript_source = store.get_file_source_by_identity(f"google-drive:{file['id']}")
                    if existing_transcript_source:
                        removed_source_id = int(existing_transcript_source["id"])
                        store.delete_source(removed_source_id)
                results.append({
                    "id": file["id"],
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "Brain conversation transcript excluded from retrieval index",
                    "mimeType": file.get("mimeType"),
                    "removedSourceId": removed_source_id,
                })
                emit_progress(relative_path)
                continue
            if is_agent_managed_upload(file):
                # Skipped, never deleted: if the agent-url source is ever missing
                # this file is the only copy of the text, so removing it here
                # could lose the document outright.
                results.append({
                    "id": file["id"],
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": "agent import already indexed this document",
                    "mimeType": file.get("mimeType"),
                })
                emit_progress(relative_path)
                continue
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
            data, downloaded_extension, download_metadata = client.download_file(file, max_bytes=max_bytes)

            file_hash = sha256_bytes(data)
            extracted_text, extraction_metadata = extract_drive_file_text(
                data,
                downloaded_extension,
                max_pdf_pages=max_pdf_pages,
                max_extracted_chars=max_extracted_chars,
            )
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
                "uploadedAt": file.get("createdTime"),
                "modifiedAt": file.get("modifiedTime"),
                "indexedAt": indexed_at,
                "webViewLink": file.get("webViewLink"),
                "storageMode": "drive_metadata_source_preview_chunks_full_text",
                "renderSafeLimits": {
                    "maxBytes": max_bytes,
                    "maxPdfPages": max_pdf_pages,
                    "maxExtractedChars": max_extracted_chars,
                },
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
            if "exceeds maxBytes" in str(exc):
                results.append({
                    "id": file.get("id"),
                    "name": file.get("name"),
                    "relativePath": relative_path,
                    "status": "skipped",
                    "reason": str(exc),
                    "bytes": size or None,
                })
                emit_progress(relative_path)
                continue

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
        "maxBytes": max_bytes,
        "maxPdfPages": max_pdf_pages,
        "maxExtractedChars": max_extracted_chars,
        "linkedLegacySources": len(linked_legacy_sources),
    }
    return {
        "folderId": clean_folder_id,
        "folderUrl": drive_folder_url(clean_folder_id),
        "summary": summary,
        "results": results,
        "linkedLegacySources": linked_legacy_sources,
        "counts": store.counts(),
    }
