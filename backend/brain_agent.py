import ipaddress
import json
import mimetypes
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from brain_indexer import SUPPORTED_EXTENSIONS
from brain_ingestion import chunk_text, normalize_text, stable_hash
from drive_indexer import (
    AGENT_UPLOAD_PROPERTY,
    GoogleDriveClient,
    MIME_EXTENSION_MAP,
    drive_folder_url,
    extract_drive_file_text,
    parse_drive_folder_id,
    sha256_bytes,
)


from espi_sources import POLISH_OFFICIAL_DOMAINS


DEFAULT_AGENT_MAX_BYTES = 15 * 1024 * 1024
DEFAULT_AGENT_DOWNLOAD_FOLDER = "Agent Downloads"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
# Official or exchange-operated disclosure sources. Poland has no SEC-style API,
# so its filings arrive from PAP's ESPI/EBI listing and the two exchange sites;
# they are as authoritative for a Warsaw issuer as sec.gov is for a US one, and a
# trusted import has to accept them or the Polish half of the book cannot be
# sourced at all.
TRUSTED_OFFICIAL_DOMAINS = {
    "sec.gov",
    "www.sec.gov",
    "data.sec.gov",
} | POLISH_OFFICIAL_DOMAINS
COMMON_COMPANY_TICKERS = {
    "netflix": "NFLX",
    "nvidia": "NVDA",
    "meta": "META",
    "facebook": "META",
    "amazon": "AMZN",
    "oracle": "ORCL",
    "affirm": "AFRM",
    "roblox": "RBLX",
    "duolingo": "DUOL",
    "walmart": "WMT",
    "microsoft": "MSFT",
}
CORE_SEC_FORMS = {"10-K", "10-Q", "8-K", "6-K", "20-F", "40-F"}
QUERYABLE_SEC_FORMS = CORE_SEC_FORMS | {"DEF 14A", "S-1", "S-3", "13F-HR", "SC 13D", "SC 13G"}
RESULTS_WINDOW_MAX_DAYS = 75
SEC_JSON_CACHE_SECONDS = 5 * 60


@dataclass
class DownloadedDocument:
    url: str
    final_url: str
    filename: str
    extension: str
    mime_type: str
    data: bytes


def _agent_user_agent() -> str:
    return os.environ.get(
        "BRAIN_AGENT_USER_AGENT",
        "InvestmentBrainResearchAgent/1.0; private research dashboard",
    )


def _domain_matches(hostname: str, domains: set[str]) -> bool:
    host = hostname.lower().strip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _validate_public_http_url(url: str, *, allowed_domains: set[str] | None = None) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs can be imported.")
    if not parsed.hostname:
        raise ValueError("URL is missing a hostname.")

    hostname = parsed.hostname.lower()
    if allowed_domains and not _domain_matches(hostname, allowed_domains):
        raise ValueError(f"Domain is not allowlisted for this agent action: {hostname}")

    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve URL host: {hostname}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError("URL resolves to a private or unsafe network address.")


def _extension_from_url(url: str) -> str | None:
    path = PurePosixPath(unquote(urlparse(url).path))
    suffix = path.suffix.lower()
    return suffix if suffix in SUPPORTED_EXTENSIONS else None


def _extension_from_content_type(content_type: str | None) -> str | None:
    clean_type = (content_type or "").split(";", 1)[0].strip().lower()
    if clean_type in MIME_EXTENSION_MAP:
        return MIME_EXTENSION_MAP[clean_type]
    if clean_type in {"text/html", "application/xhtml+xml"}:
        return ".html"
    guessed = mimetypes.guess_extension(clean_type) if clean_type else None
    if guessed == ".htm":
        guessed = ".html"
    return guessed if guessed in SUPPORTED_EXTENSIONS else None


def _mime_type_for_extension(extension: str, fallback: str | None = None) -> str:
    clean_fallback = (fallback or "").split(";", 1)[0].strip()
    if clean_fallback:
        return clean_fallback
    return mimetypes.types_map.get(extension.lower(), "application/octet-stream")


def _safe_filename(name: str, extension: str) -> str:
    cleaned = re.sub(r"[^\w.\-() ]+", " ", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:160].strip(" .")
    if not cleaned:
        cleaned = f"source-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    if not cleaned.lower().endswith(extension.lower()):
        cleaned += extension
    return cleaned


def _filename_from_response(url: str, content_disposition: str | None, extension: str) -> str:
    if content_disposition:
        match = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?", content_disposition, flags=re.I)
        if match:
            return _safe_filename(unquote(match.group(1) or match.group(2) or ""), extension)

    path_name = PurePosixPath(unquote(urlparse(url).path)).name
    if path_name:
        return _safe_filename(path_name, extension)
    return _safe_filename(urlparse(url).hostname or "source", extension)


# Formats whose extracted text loses layout a reader needs: a financial table in
# a PDF or a spreadsheet flattens into prose, so the original is kept beside the
# Markdown. HTML and plain text are excluded deliberately - the Markdown is
# strictly more readable than raw markup, so a second copy would buy nothing.
LAYOUT_BEARING_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def _filename_stem(filename: str, extension: str) -> str:
    clean_name = PurePosixPath(filename).name
    if extension and clean_name.lower().endswith(extension.lower()):
        clean_name = clean_name[: -len(extension)]
    return clean_name or "source"


def _markdown_filename(filename: str, original_extension: str) -> str:
    """Return the Drive filename for the canonical, AI-readable source."""
    return _safe_filename(_filename_stem(filename, original_extension), ".md")


def _original_filename(filename: str, original_extension: str) -> str:
    """Name the preserved original so it sorts next to its Markdown twin."""
    return _safe_filename(_filename_stem(filename, original_extension), original_extension or ".bin")


def keeps_original_upload(extension: str) -> bool:
    return str(extension or "").strip().lower() in LAYOUT_BEARING_EXTENSIONS


def _markdown_body(text: str) -> str:
    """Keep extracted text readable while giving PDF page boundaries Markdown structure."""
    clean_text = normalize_text(text)
    return re.sub(r"(?m)^\[Page\s+(\d+)\]\s*$", r"## Page \1", clean_text)


def _canonical_markdown_document(
    document: DownloadedDocument,
    *,
    title: str,
    source_url: str,
    retrieved_at: str,
    extracted_text: str,
    agent_task: str | None = None,
    original_file_url: str | None = None,
) -> bytes:
    """Create the durable, AI-readable Drive artifact for a web-acquired source.

    This Markdown is what the Brain indexes and retrieves from. For formats that
    carry layout the extraction cannot (see LAYOUT_BEARING_EXTENSIONS) the
    untouched original is uploaded beside it and linked from here, so a reader
    who needs the real table can reach it in one click. The original URL and
    source-format details stay in the front matter either way, so the conversion
    remains auditable even when no copy was kept.
    """
    front_matter = {
        "title": title,
        "source_url": source_url,
        "resolved_url": document.final_url,
        "retrieved_at_utc": retrieved_at,
        "original_filename": document.filename,
        "original_extension": document.extension,
        "original_mime_type": document.mime_type,
        "conversion": "extracted text normalized to markdown by Investment Brain",
    }
    if original_file_url:
        front_matter["original_file_drive_url"] = original_file_url
    if agent_task:
        front_matter["research_task"] = agent_task

    metadata_lines = [f"{key}: {json.dumps(value, ensure_ascii=True)}" for key, value in front_matter.items()]
    body = _markdown_body(extracted_text)
    markdown = "\n".join([
        "---",
        *metadata_lines,
        "---",
        "",
        f"# {title}",
        "",
        "## Source",
        "",
        f"- Original URL: <{source_url}>",
        f"- Resolved URL: <{document.final_url}>",
        f"- Retrieved: {retrieved_at}",
        f"- Converted from: `{document.extension.lstrip('.') or 'unknown'}` to Markdown for indexing and retrieval.",
        *([f"- Original file kept on Drive: <{original_file_url}>"] if original_file_url else []),
        "",
        "## Extracted Content",
        "",
        body,
        "",
    ])
    return markdown.encode("utf-8")


def download_public_document(
    url: str,
    *,
    max_bytes: int = DEFAULT_AGENT_MAX_BYTES,
    allowed_domains: set[str] | None = None,
) -> DownloadedDocument:
    current_url = url.strip()
    max_bytes = max(1024, min(int(max_bytes), 75 * 1024 * 1024))
    headers = {
        "User-Agent": _agent_user_agent(),
        "Accept": "text/html,application/pdf,application/json,text/plain,*/*",
    }

    with httpx.Client(timeout=60, follow_redirects=False, headers=headers) as client:
        for _ in range(6):
            _validate_public_http_url(current_url, allowed_domains=allowed_domains)
            with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise RuntimeError("Redirect response did not include a destination.")
                    current_url = urljoin(current_url, location)
                    continue

                response.raise_for_status()
                final_url = str(response.url)
                _validate_public_http_url(final_url, allowed_domains=allowed_domains)
                content_type = response.headers.get("content-type")
                extension = _extension_from_url(final_url) or _extension_from_content_type(content_type)
                if not extension or extension not in SUPPORTED_EXTENSIONS:
                    raise RuntimeError(f"Unsupported document type: {content_type or final_url}")

                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise RuntimeError(f"Downloaded file exceeds maxBytes ({len(content)} > {max_bytes})")

                return DownloadedDocument(
                    url=url,
                    final_url=final_url,
                    filename=_filename_from_response(final_url, response.headers.get("content-disposition"), extension),
                    extension=extension,
                    mime_type=_mime_type_for_extension(extension, content_type),
                    data=bytes(content),
                )

    raise RuntimeError("Too many redirects while downloading document.")


def _source_preview(title: str, document: DownloadedDocument, text: str, drive_file: dict[str, Any] | None) -> str:
    preview = normalize_text(text)[:4000]
    return (
        f"Agent source: {title}\n"
        f"Original URL: {document.final_url}\n"
        f"Drive URL: {(drive_file or {}).get('webViewLink') or ''}\n"
        f"Indexed preview:\n\n{preview}"
    ).strip()


def import_document_into_brain(
    store: Any,
    document: DownloadedDocument,
    *,
    title: str | None = None,
    tags: list[str] | None = None,
    source_url: str | None = None,
    source_label: str | None = None,
    upload_to_drive: bool = True,
    drive_folder_id: str | None = None,
    drive_subfolder: str = DEFAULT_AGENT_DOWNLOAD_FOLDER,
    force: bool = False,
    agent_task: str | None = None,
    keep_original: bool = True,
) -> dict[str, Any]:
    indexed_at = datetime.now(timezone.utc).isoformat()
    file_hash = sha256_bytes(document.data)
    original_url = source_url or document.final_url
    file_identity = f"agent-url:{stable_hash(original_url)}"
    existing = store.get_file_source_by_identity(file_identity) if hasattr(store, "get_file_source_by_identity") else None

    if existing and existing.get("metadata", {}).get("fileHash") == file_hash and not force:
        return {
            "status": "skipped",
            "reason": "unchanged",
            "source": existing,
            "chunks": [],
            "driveFile": None,
            "counts": store.counts(),
        }

    text, extraction_metadata = extract_drive_file_text(document.data, document.extension)
    clean_text = normalize_text(text)
    if not clean_text:
        raise RuntimeError("Downloaded document had no extractable text.")

    source_title = re.sub(r"\s+", " ", (title or source_label or document.filename.rsplit(".", 1)[0])).strip()[:300]
    canonical_filename = _markdown_filename(document.filename, document.extension)
    original_filename = _original_filename(document.filename, document.extension)
    keeps_original = bool(keep_original and upload_to_drive and keeps_original_upload(document.extension))

    drive_file = None
    original_drive_file = None
    upload_error = None
    original_upload_error = None
    clean_drive_folder_id = parse_drive_folder_id(drive_folder_id)
    client = None
    target_folder_id = None
    if upload_to_drive:
        try:
            client = GoogleDriveClient(store=store)
            parent_id = clean_drive_folder_id or parse_drive_folder_id()
            target_folder_id = parent_id
            if parent_id and drive_subfolder:
                target_folder_id = client.ensure_folder(parent_id, drive_subfolder)["id"]
        except Exception as exc:
            upload_error = str(exc)[:500]
            raise RuntimeError(
                "Drive upload failed. Reconnect Google Drive with file-write permission, then retry. "
                f"Google said: {upload_error}"
            ) from exc

    # The original goes up first so the Markdown can link to it, and its failure
    # is recorded rather than raised: the Markdown is what the Brain retrieves
    # from, so losing the reading copy must not lose the indexed source.
    if keeps_original:
        try:
            original_drive_file = client.upload_file(
                name=original_filename,
                data=document.data,
                mime_type=document.mime_type or "application/octet-stream",
                folder_id=target_folder_id,
                description=(
                    f"Original {document.extension.lstrip('.') or 'file'} downloaded by Investment Brain agent "
                    f"from {document.final_url}. Kept for reading; the Markdown twin is what is indexed."
                ),
                app_properties={AGENT_UPLOAD_PROPERTY: "original"},
            )
        except Exception as exc:
            original_upload_error = str(exc)[:500]

    canonical_data = _canonical_markdown_document(
        document,
        title=source_title,
        source_url=original_url,
        retrieved_at=indexed_at,
        extracted_text=clean_text,
        agent_task=agent_task,
        original_file_url=(original_drive_file or {}).get("webViewLink"),
    )
    canonical_hash = sha256_bytes(canonical_data)

    if upload_to_drive:
        try:
            drive_file = client.upload_file(
                name=canonical_filename,
                data=canonical_data,
                mime_type="text/markdown; charset=utf-8",
                folder_id=target_folder_id,
                description=(
                    f"Markdown conversion created by Investment Brain agent from {document.final_url}. "
                    f"Original format: {document.extension}."
                ),
                app_properties={AGENT_UPLOAD_PROPERTY: "markdown"},
            )
        except Exception as exc:
            upload_error = str(exc)[:500]
            raise RuntimeError(
                "Drive upload failed. Reconnect Google Drive with file-write permission, then retry. "
                f"Google said: {upload_error}"
            ) from exc

    clean_tags = ["agent-import", "markdown", document.extension.lstrip(".")]
    for tag in tags or []:
        if tag and tag not in clean_tags:
            clean_tags.append(tag)

    metadata = {
        "sourceType": "agent_import",
        "fileIdentity": file_identity,
        "fileHash": file_hash,
        "sourceUrl": original_url,
        "finalUrl": document.final_url,
        "sourceLabel": source_label,
        "agentTask": agent_task,
        "fileName": canonical_filename,
        "extension": ".md",
        "mimeType": "text/markdown",
        "bytes": len(canonical_data),
        "canonicalFileName": canonical_filename,
        "canonicalFileHash": canonical_hash,
        "canonicalExtension": ".md",
        "canonicalMimeType": "text/markdown",
        "originalFileName": document.filename,
        "originalExtension": document.extension,
        "originalMimeType": document.mime_type,
        "originalBytes": len(document.data),
        "indexedAt": indexed_at,
        "storageMode": "agent_download_markdown_drive_metadata_source_preview_chunks_full_text",
        "driveFolderId": clean_drive_folder_id,
        "driveSubfolder": drive_subfolder if upload_to_drive else None,
        "uploadError": upload_error,
        "originalKept": bool(original_drive_file),
        "originalUploadError": original_upload_error,
        **extraction_metadata,
    }
    if original_drive_file:
        metadata.update({
            "originalDriveFileId": original_drive_file.get("id"),
            "originalWebViewLink": original_drive_file.get("webViewLink"),
            "originalDriveFileName": original_drive_file.get("name"),
        })
    if drive_file:
        metadata.update({
            "driveFileId": drive_file.get("id"),
            "webViewLink": drive_file.get("webViewLink"),
            "driveFileName": drive_file.get("name"),
            "driveMimeType": drive_file.get("mimeType"),
            "driveCreatedTime": drive_file.get("createdTime"),
        })

    source, changed = store.upsert_file_source(
        title=source_title,
        body=_source_preview(source_title, document, clean_text, drive_file),
        tags=clean_tags,
        metadata=metadata,
        force=force,
    )
    chunks = chunk_text(
        clean_text,
        source_title=source_title,
        tags=clean_tags,
        chunk_words=900,
        overlap_words=120,
    )
    for chunk in chunks:
        chunk_metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        chunk["metadata"] = {
            **chunk_metadata,
            "fileIdentity": file_identity,
            "sourceUrl": original_url,
            "finalUrl": document.final_url,
            "webViewLink": (drive_file or {}).get("webViewLink"),
            "driveFileId": (drive_file or {}).get("id"),
            "sourceHash": file_hash,
        }
        chunk["contentHash"] = stable_hash(file_hash, str(chunk["ordinal"]), chunk["body"])
    saved_chunks = store.add_chunks(source["id"], chunks) if changed else []

    return {
        "status": "indexed",
        "reason": "updated" if existing else "created",
        "source": source,
        "chunks": saved_chunks,
        "driveFile": drive_file,
        "driveFolderUrl": drive_folder_url(clean_drive_folder_id),
        "counts": store.counts(),
        "document": {
            "url": document.url,
            "finalUrl": document.final_url,
            "filename": canonical_filename,
            "extension": ".md",
            "mimeType": "text/markdown",
            "bytes": len(canonical_data),
            "convertedToMarkdown": True,
            "original": {
                "filename": document.filename,
                "extension": document.extension,
                "mimeType": document.mime_type,
                "bytes": len(document.data),
                "keptOnDrive": bool(original_drive_file),
                "driveFileId": (original_drive_file or {}).get("id"),
                "webViewLink": (original_drive_file or {}).get("webViewLink"),
                "driveFileName": (original_drive_file or {}).get("name"),
                "uploadError": original_upload_error,
            },
        },
        "originalDriveFile": original_drive_file,
    }


def _target_years_from_query(query: str) -> set[str]:
    years = {match.group(0) for match in re.finditer(r"\b20\d{2}\b", query)}
    return years


def _base_sec_form(form: str | None) -> str:
    clean = str(form or "").strip().upper()
    return clean[:-2] if clean.endswith("/A") else clean


def _requested_forms_from_query(query: str) -> set[str]:
    clean = re.sub(r"\s+", " ", str(query or "").lower()).strip()
    patterns = {
        "10-K": r"(?<![a-z0-9])10\s*[- ]?\s*k(?![a-z0-9])",
        "10-Q": r"(?<![a-z0-9])10\s*[- ]?\s*q(?![a-z0-9])",
        "8-K": r"(?<![a-z0-9])8\s*[- ]?\s*k(?![a-z0-9])",
        "6-K": r"(?<![a-z0-9])6\s*[- ]?\s*k(?![a-z0-9])",
        "20-F": r"(?<![a-z0-9])20\s*[- ]?\s*f(?![a-z0-9])",
        "40-F": r"(?<![a-z0-9])40\s*[- ]?\s*f(?![a-z0-9])",
        "DEF 14A": r"(?<![a-z0-9])def\s*14a(?![a-z0-9])",
        "13F-HR": r"(?<![a-z0-9])13f(?:\s*[- ]?\s*hr)?(?![a-z0-9])",
        "SC 13D": r"(?<![a-z0-9])(?:sc\s*)?13d(?![a-z0-9])",
        "SC 13G": r"(?<![a-z0-9])(?:sc\s*)?13g(?![a-z0-9])",
        "S-1": r"(?<![a-z0-9])s\s*[- ]?\s*1(?![a-z0-9])",
        "S-3": r"(?<![a-z0-9])s\s*[- ]?\s*3(?![a-z0-9])",
    }
    explicit = {form for form, pattern in patterns.items() if re.search(pattern, clean)}
    if explicit:
        return explicit
    if any(term in clean for term in ("annual report", "annual filing")):
        return {"10-K", "20-F", "40-F"}
    if any(term in clean for term in ("quarterly report", "quarterly filing")):
        return {"10-Q", "6-K"}
    if any(term in clean for term in ("proxy statement", "proxy filing")):
        return {"DEF 14A"}
    return set()


def _filing_search_intent(query: str) -> dict[str, Any]:
    return {
        "requestedForms": sorted(_requested_forms_from_query(query)),
        "requestedYears": sorted(_target_years_from_query(query)),
        "requestedQuarter": _target_quarter_from_query(query),
        "needsResultsDocument": _query_needs_results_document(query),
    }


def _target_quarter_from_query(query: str) -> int | None:
    clean = query.lower()
    match = re.search(r"\bq([1-4])\b", clean)
    if match:
        return int(match.group(1))
    words = {
        "first quarter": 1,
        "second quarter": 2,
        "third quarter": 3,
        "fourth quarter": 4,
    }
    for phrase, quarter in words.items():
        if phrase in clean:
            return quarter
    return None


def _quarter_from_date(value: str | None) -> int | None:
    if not value or len(value) < 7:
        return None
    try:
        month = int(value[5:7])
    except ValueError:
        return None
    return ((month - 1) // 3) + 1


def _document_has_target_quarter(document_text: str, *, quarter: int, year: str) -> bool:
    short_year = year[-2:]
    clean = document_text.lower()
    compact = re.sub(r"[^a-z0-9]+", "", clean)
    quarter_end = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[quarter]
    patterns = [
        rf"(?:^|[^a-z0-9])q{quarter}[-_ ]?{short_year}(?:$|[^a-z0-9])",
        rf"(?:^|[^a-z0-9])q{quarter}[-_ ]?{year}(?:$|[^a-z0-9])",
        rf"(?:^|[^a-z0-9]){year}[-_ ]?q{quarter}(?:$|[^a-z0-9])",
        rf"(?:^|[^a-z0-9]){short_year}[-_ ]?q{quarter}(?:$|[^a-z0-9])",
    ]
    return (
        any(re.search(pattern, clean) for pattern in patterns)
        or f"{quarter_end}{year}" in compact
        or f"{year}{quarter_end}" in compact
    )


def _document_has_different_quarter(document_text: str, *, quarter: int, years: set[str]) -> bool:
    clean = document_text.lower()
    for match in re.finditer(r"(?:^|[^a-z0-9])q([1-4])[-_ ]?(\d{2}|\d{4})(?:$|[^a-z0-9])", clean):
        found_quarter = int(match.group(1))
        found_year = match.group(2)
        normalized_year = f"20{found_year}" if len(found_year) == 2 else found_year
        if found_quarter != quarter or (years and normalized_year not in years):
            return True
    return False


def _results_window_days(filing_date: str, *, quarter: int, year: str) -> int | None:
    quarter_end_days = {1: 31, 2: 30, 3: 30, 4: 31}
    try:
        filed = datetime.strptime(filing_date, "%Y-%m-%d")
        quarter_end = datetime(int(year), quarter * 3, quarter_end_days[quarter])
    except (TypeError, ValueError):
        return None
    return (filed - quarter_end).days


def _filing_is_in_results_window(filing_date: str, *, quarter: int, years: set[str]) -> bool:
    return any(
        (days := _results_window_days(filing_date, quarter=quarter, year=year)) is not None
        and 0 <= days <= RESULTS_WINDOW_MAX_DAYS
        for year in years
    )


def _query_needs_results_document(query: str) -> bool:
    clean = query.lower()
    return any(term in clean for term in ("results", "earnings", "quarterly update", "shareholder letter"))


def _infer_ticker(company: str | None, ticker: str | None) -> str | None:
    if ticker:
        return ticker.strip().upper()
    clean_company = (company or "").strip().lower()
    if clean_company in COMMON_COMPANY_TICKERS:
        return COMMON_COMPANY_TICKERS[clean_company]
    for name, mapped_ticker in COMMON_COMPANY_TICKERS.items():
        if name in clean_company:
            return mapped_ticker
    return None


@lru_cache(maxsize=16)
def _sec_get_json_cached(url: str, cache_bucket: int) -> Any:
    with httpx.Client(timeout=45, headers={"User-Agent": _agent_user_agent(), "Accept": "application/json"}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def _sec_get_json(url: str) -> Any:
    return _sec_get_json_cached(url, int(time.time() // SEC_JSON_CACHE_SECONDS))


def _company_name_tokens(value: str | None) -> list[str]:
    ignored = {
        "inc", "incorporated", "corp", "corporation", "company", "co", "plc", "ltd", "limited",
        "holdings", "holding", "group", "sa", "se", "nv", "the",
    }
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if token not in ignored and len(token) >= 2
    ]


def resolve_sec_company(company: str | None = None, ticker: str | None = None) -> dict[str, Any] | None:
    inferred_ticker = _infer_ticker(company, ticker)
    companies = _sec_get_json(SEC_COMPANY_TICKERS_URL)
    rows = companies.values() if isinstance(companies, dict) else companies
    clean_company = (company or "").strip().lower()
    query_tokens = {
        token.upper()
        for token in re.findall(r"(?<![a-z0-9])[a-z][a-z0-9.-]{0,9}(?![a-z0-9])", clean_company)
    }

    best: dict[str, Any] | None = None
    fuzzy_best: tuple[float, dict[str, Any]] | None = None
    query_words = set(_company_name_tokens(clean_company))
    for row in rows:
        row_ticker = str(row.get("ticker") or "").upper()
        row_title = str(row.get("title") or "")
        if inferred_ticker and row_ticker == inferred_ticker:
            best = row
            break
        if row_ticker and row_ticker in query_tokens:
            best = row
            break
        if clean_company and clean_company in row_title.lower():
            best = row
            break
        if row_title and row_title.lower() in clean_company:
            best = row
            break
        title_words = _company_name_tokens(row_title)
        overlap = query_words.intersection(title_words)
        primary_match = bool(title_words and title_words[0] in query_words and len(title_words[0]) >= 4)
        if not primary_match and len(overlap) < min(2, len(title_words)):
            continue
        score = len(overlap) / max(1, len(title_words)) + (1.0 if primary_match else 0.0)
        if fuzzy_best is None or score > fuzzy_best[0]:
            fuzzy_best = (score, row)
    if not best and fuzzy_best:
        best = fuzzy_best[1]
    if not best:
        return None

    cik = str(best.get("cik_str") or "").zfill(10)
    return {
        "ticker": str(best.get("ticker") or inferred_ticker or "").upper(),
        "title": best.get("title"),
        "cik": cik,
        "cikInt": int(best.get("cik_str")),
    }


def _filing_document_url(cik_int: int, accession: str, document: str) -> str:
    return f"{SEC_ARCHIVES_BASE}/{cik_int}/{accession.replace('-', '')}/{document}"


def _sec_directory_documents(cik_int: int, accession: str) -> list[dict[str, Any]]:
    url = f"{SEC_ARCHIVES_BASE}/{cik_int}/{accession.replace('-', '')}/index.json"
    try:
        payload = _sec_get_json(url)
    except Exception:
        return []
    return payload.get("directory", {}).get("item", []) if isinstance(payload, dict) else []


def _score_filing(
    query: str,
    form: str,
    filing_date: str,
    report_date: str | None,
    description: str | None,
    document: str | None = None,
) -> float:
    clean_query = query.lower()
    years = _target_years_from_query(clean_query)
    target_quarter = _target_quarter_from_query(clean_query)
    needs_results = _query_needs_results_document(clean_query)
    requested_forms = _requested_forms_from_query(clean_query)
    base_form = _base_sec_form(form)
    periodic_form = base_form in {"10-K", "20-F", "40-F", "10-Q"}
    document_text = f"{description or ''} {document or ''}"
    score = 1.0
    if base_form in CORE_SEC_FORMS:
        score += 2.0
    if requested_forms and base_form in requested_forms:
        score += 40.0
    if "results" in clean_query or "earnings" in clean_query:
        if base_form in {"8-K", "6-K"}:
            score += 12.0
        if base_form in {"10-K", "10-Q"}:
            score += 4.0
    if "q4" in clean_query or "fourth quarter" in clean_query:
        if base_form in {"8-K", "10-K"}:
            score += 3.0
    for year in years:
        if periodic_form:
            if year in (report_date or ""):
                score += 18.0
            if year in filing_date:
                score += 8.0
            if target_quarter and _quarter_from_date(report_date) == target_quarter and str(report_date or "").startswith(year):
                score += 18.0
        elif not (needs_results and target_quarter):
            if year in filing_date:
                score += 18.0
            elif year in (report_date or ""):
                score += 8.0
        if target_quarter == 4 and filing_date.startswith(str(int(year) + 1)) and filing_date[5:7] in {"01", "02"}:
            score += 4.0
        if target_quarter and _document_has_target_quarter(document_text, quarter=target_quarter, year=year):
            score += 8.0
    if needs_results and target_quarter and years and not periodic_form:
        window_days = [
            days
            for year in years
            if (days := _results_window_days(filing_date, quarter=target_quarter, year=year)) is not None
        ]
        if any(0 <= days <= RESULTS_WINDOW_MAX_DAYS for days in window_days):
            score += 30.0
        elif any(days < 0 for days in window_days):
            score -= 30.0
        else:
            score -= 10.0
    if target_quarter and years and _document_has_different_quarter(document_text, quarter=target_quarter, years=years):
        score -= 5.0
    if any(term in document_text.lower() for term in ("stocksplit", "stock split", "compensation", "employment agreement", "bylaws")):
        score -= 8.0
    if description and any(term in description.lower() for term in ("earnings", "results", "ex-99", "press release")):
        score += 2.0
    return score


def _period_label(form: str, report_date: str | None) -> str | None:
    if not report_date or len(report_date) < 7:
        return None
    year = report_date[:4]
    base_form = _base_sec_form(form)
    if base_form in {"10-K", "20-F", "40-F"}:
        return f"FY {year}"
    if base_form in {"10-Q", "6-K"}:
        quarter = _quarter_from_date(report_date)
        return f"Q{quarter} {year}" if quarter else year
    return report_date


def _filing_title(ticker: str, form: str, filing_date: str, report_date: str | None) -> str:
    base_form = _base_sec_form(form)
    period = _period_label(form, report_date)
    amendment = " amendment" if str(form).upper().endswith("/A") else ""
    if base_form in {"10-K", "20-F", "40-F"}:
        return f"{ticker} {period or 'Annual Report'} {base_form}{amendment}"
    if base_form in {"10-Q", "6-K"}:
        return f"{ticker} {period or 'Quarterly Report'} {base_form}{amendment}"
    return f"{ticker} {base_form}{amendment} filed {filing_date}"


def _candidate_match_details(
    *,
    form: str,
    filing_date: str,
    report_date: str | None,
    requested_forms: set[str],
    target_years: set[str],
    target_quarter: int | None,
    needs_results: bool = False,
) -> tuple[bool, list[str]]:
    base_form = _base_sec_form(form)
    periodic_form = base_form in {"10-K", "20-F", "40-F", "10-Q"}
    reasons: list[str] = []
    form_match = not requested_forms or base_form in requested_forms
    if requested_forms and form_match:
        reasons.append(f"Exact {base_form} form")
    report_year_match = bool(target_years and str(report_date or "")[:4] in target_years)
    filing_year_match = bool(target_years and filing_date[:4] in target_years)
    if report_year_match:
        reasons.append(f"Reporting period {str(report_date)[:4]}")
    elif filing_year_match:
        reasons.append(f"Filed in {filing_date[:4]}")
    results_window_match = bool(
        needs_results
        and target_quarter
        and target_years
        and _filing_is_in_results_window(filing_date, quarter=target_quarter, years=target_years)
    )
    quarter_match = bool(
        target_quarter
        and (
            periodic_form and _quarter_from_date(report_date) == target_quarter
            or not periodic_form and results_window_match
        )
    )
    if quarter_match:
        reasons.append(
            f"Q{target_quarter} reporting period"
            if periodic_form
            else f"Q{target_quarter} results filing window"
        )
    year_match = report_year_match if periodic_form else results_window_match or report_year_match or filing_year_match
    exact = form_match and (not target_years or year_match) and (not target_quarter or quarter_match)
    if not reasons:
        reasons.append("Official SEC filing")
    return exact, reasons


def _filing_batches(submissions: dict[str, Any], target_years: set[str]) -> tuple[list[dict[str, Any]], int]:
    filings = submissions.get("filings", {}) if isinstance(submissions, dict) else {}
    batches = [filings.get("recent", {})]
    archives_loaded = 0
    if not target_years:
        return batches, archives_loaded

    target_numbers = {int(year) for year in target_years}
    for archive in filings.get("files", []):
        name = str(archive.get("name") or "").strip()
        filing_from = str(archive.get("filingFrom") or "")[:4]
        filing_to = str(archive.get("filingTo") or "")[:4]
        if not name or not filing_from.isdigit() or not filing_to.isdigit():
            continue
        archive_start = int(filing_from)
        archive_end = int(filing_to)
        if not any(archive_start <= year + 1 and archive_end >= year for year in target_numbers):
            continue
        try:
            payload = _sec_get_json(SEC_SUBMISSIONS_FILE_URL.format(name=name))
        except Exception:
            continue
        if isinstance(payload, dict):
            batches.append(payload)
            archives_loaded += 1
    return batches, archives_loaded


def find_official_source_candidates(
    *,
    task: str,
    company: str | None = None,
    ticker: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    resolved = resolve_sec_company(company=company or task, ticker=ticker)
    if not resolved:
        return {
            "query": task,
            "resolvedCompany": None,
            "candidates": [],
            "message": "Could not resolve a public SEC company from the company/ticker.",
        }

    submissions = _sec_get_json(SEC_SUBMISSIONS_URL.format(cik=resolved["cik"]))
    candidates: list[dict[str, Any]] = []
    needs_results = _query_needs_results_document(task)
    target_quarter = _target_quarter_from_query(task)
    target_years = _target_years_from_query(task)
    requested_forms = _requested_forms_from_query(task)
    intent = _filing_search_intent(task)
    batches, archives_loaded = _filing_batches(submissions, target_years)
    filings_reviewed = 0
    exhibit_directories_checked = 0
    seen_documents: set[tuple[str, str]] = set()

    for batch in batches:
        forms = batch.get("form", []) if isinstance(batch, dict) else []
        accessions = batch.get("accessionNumber", []) if isinstance(batch, dict) else []
        primary_docs = batch.get("primaryDocument", []) if isinstance(batch, dict) else []
        filing_dates = batch.get("filingDate", []) if isinstance(batch, dict) else []
        report_dates = batch.get("reportDate", []) if isinstance(batch, dict) else []
        descriptions = batch.get("primaryDocDescription", []) if isinstance(batch, dict) else []

        for index, raw_form in enumerate(forms):
            filings_reviewed += 1
            form = str(raw_form or "").upper()
            base_form = _base_sec_form(form)
            if requested_forms:
                if base_form not in requested_forms:
                    continue
            elif base_form not in CORE_SEC_FORMS:
                continue
            if base_form not in QUERYABLE_SEC_FORMS:
                continue
            if index >= len(accessions) or index >= len(primary_docs) or index >= len(filing_dates):
                continue
            accession = str(accessions[index] or "").strip()
            primary_doc = str(primary_docs[index] or "").strip()
            filing_date = str(filing_dates[index] or "").strip()
            if not accession or not primary_doc or not filing_date:
                continue
            document_key = (accession, primary_doc)
            if document_key in seen_documents:
                continue
            seen_documents.add(document_key)
            report_date = str(report_dates[index] or "").strip() if index < len(report_dates) else None
            description = str(descriptions[index] or "").strip() if index < len(descriptions) else None
            score = _score_filing(task, form, filing_date, report_date, description, primary_doc)
            exact_match, match_reasons = _candidate_match_details(
                form=form,
                filing_date=filing_date,
                report_date=report_date,
                requested_forms=requested_forms,
                target_years=target_years,
                target_quarter=target_quarter,
                needs_results=needs_results,
            )
            primary_url = _filing_document_url(resolved["cikInt"], accession, primary_doc)
            candidates.append({
                "title": _filing_title(resolved["ticker"], form, filing_date, report_date),
                "url": primary_url,
                "source": "SEC EDGAR",
                "domain": "sec.gov",
                "form": form,
                "baseForm": base_form,
                "filingDate": filing_date,
                "reportDate": report_date,
                "periodLabel": _period_label(form, report_date),
                "accessionNumber": accession,
                "document": primary_doc,
                "score": round(score, 2),
                "confidence": round(max(0.2, min(0.99, (score + 10.0) / 70.0)), 3),
                "matchQuality": "Exact match" if exact_match else "Relevant filing",
                "matchReasons": match_reasons,
                "isExactMatch": exact_match,
                "isAmendment": form.endswith("/A"),
                "reason": f"Official SEC {form} filing. {description or ''}".strip(),
                "trusted": True,
            })

            include_exhibits = (
                base_form in {"8-K", "6-K"}
                and needs_results
                and (not requested_forms or base_form in requested_forms)
                and score >= 10
                and exhibit_directories_checked < 6
                and (
                    not target_quarter
                    or not target_years
                    or _filing_is_in_results_window(filing_date, quarter=target_quarter, years=target_years)
                )
            )
            if not include_exhibits:
                continue
            exhibit_directories_checked += 1
            for item in _sec_directory_documents(resolved["cikInt"], accession):
                name = str(item.get("name") or "")
                low_name = name.lower()
                if not name or name == primary_doc:
                    continue
                if not any(term in low_name for term in ("ex99", "ex-99", "exhibit", "earn", "result", "press")):
                    continue
                if not any(low_name.endswith(ext) for ext in (".htm", ".html", ".pdf", ".txt")):
                    continue
                if target_quarter and target_years and not any(
                    _document_has_target_quarter(name, quarter=target_quarter, year=year)
                    for year in target_years
                ) and not any(term in low_name for term in ("earn", "result", "letter")):
                    continue
                exhibit_key = (accession, name)
                if exhibit_key in seen_documents:
                    continue
                seen_documents.add(exhibit_key)
                item_score = _score_filing(task, form, filing_date, report_date, f"{description or ''} {name}", name) + 3.0
                candidates.append({
                    "title": f"{resolved['ticker']} {(_period_label(form, report_date) or filing_date)} earnings exhibit",
                    "url": _filing_document_url(resolved["cikInt"], accession, name),
                    "source": "SEC EDGAR exhibit",
                    "domain": "sec.gov",
                    "form": form,
                    "baseForm": base_form,
                    "filingDate": filing_date,
                    "reportDate": report_date,
                    "periodLabel": _period_label(form, report_date),
                    "accessionNumber": accession,
                    "document": name,
                    "score": round(item_score, 2),
                    "confidence": round(max(0.2, min(0.99, (item_score + 10.0) / 70.0)), 3),
                    "matchQuality": "Exact match" if exact_match else "Relevant exhibit",
                    "matchReasons": [*match_reasons, "Earnings exhibit"],
                    "isExactMatch": exact_match,
                    "isAmendment": False,
                    "reason": "Official SEC filing exhibit likely containing the earnings release or result document.",
                    "trusted": True,
                })

    candidates = sorted(
        candidates,
        key=lambda item: (
            item.get("score", 0),
            bool(item.get("isExactMatch")),
            not bool(item.get("isAmendment")),
            item.get("reportDate") or "",
            item.get("filingDate") or "",
        ),
        reverse=True,
    )
    selected = candidates[: max(1, min(int(limit), 20))]
    for index, candidate in enumerate(selected):
        candidate["isBestMatch"] = index == 0
    requested_label = ", ".join(sorted(requested_forms)) if requested_forms else "core filings"
    period_bits = [*(f"FY {year}" for year in sorted(target_years))]
    if target_quarter:
        period_bits.append(f"Q{target_quarter}")
    period_label = " / ".join(period_bits)
    if candidates:
        message = f"Found {len(candidates)} {requested_label} candidate(s){f' for {period_label}' if period_label else ''}."
    else:
        message = f"No {requested_label} filing matched{f' {period_label}' if period_label else ''} for {resolved['ticker']}."
    return {
        "query": task,
        "resolvedCompany": resolved,
        "intent": intent,
        "candidates": selected,
        "searched": {
            "filingsReviewed": filings_reviewed,
            "archivesLoaded": archives_loaded,
            "exhibitDirectoriesChecked": exhibit_directories_checked,
            "matchingCandidates": len(candidates),
        },
        "message": message,
    }


def import_url_into_brain(
    store: Any,
    *,
    url: str,
    title: str | None = None,
    tags: list[str] | None = None,
    upload_to_drive: bool = True,
    drive_folder_id: str | None = None,
    drive_subfolder: str = DEFAULT_AGENT_DOWNLOAD_FOLDER,
    force: bool = False,
    max_bytes: int = DEFAULT_AGENT_MAX_BYTES,
    trusted_only: bool = False,
    agent_task: str | None = None,
    source_label: str | None = None,
    keep_original: bool = True,
) -> dict[str, Any]:
    document = download_public_document(
        url,
        max_bytes=max_bytes,
        allowed_domains=TRUSTED_OFFICIAL_DOMAINS if trusted_only else None,
    )
    return import_document_into_brain(
        store,
        document,
        title=title,
        tags=tags,
        source_url=url,
        source_label=source_label,
        upload_to_drive=upload_to_drive,
        drive_folder_id=drive_folder_id,
        drive_subfolder=drive_subfolder,
        force=force,
        agent_task=agent_task,
        keep_original=keep_original,
    )
