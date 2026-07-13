import ipaddress
import json
import mimetypes
import os
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

from brain_indexer import SUPPORTED_EXTENSIONS
from brain_ingestion import chunk_text, normalize_text, stable_hash
from drive_indexer import (
    GoogleDriveClient,
    MIME_EXTENSION_MAP,
    drive_folder_url,
    extract_drive_file_text,
    parse_drive_folder_id,
    sha256_bytes,
)


DEFAULT_AGENT_MAX_BYTES = 15 * 1024 * 1024
DEFAULT_AGENT_DOWNLOAD_FOLDER = "Agent Downloads"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
TRUSTED_OFFICIAL_DOMAINS = {
    "sec.gov",
    "www.sec.gov",
    "data.sec.gov",
}
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


def _markdown_filename(filename: str, original_extension: str) -> str:
    """Return the Drive filename for the canonical, AI-readable source."""
    clean_name = PurePosixPath(filename).name
    if clean_name.lower().endswith(original_extension.lower()):
        clean_name = clean_name[: -len(original_extension)]
    return _safe_filename(clean_name or "source", ".md")


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
) -> bytes:
    """Create the single durable Drive artifact for a web-acquired source.

    The raw HTML/PDF/DOCX is intentionally not uploaded. The original URL and
    source-format details stay in the Markdown front matter and database
    metadata so the conversion remains auditable.
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
    canonical_data = _canonical_markdown_document(
        document,
        title=source_title,
        source_url=original_url,
        retrieved_at=indexed_at,
        extracted_text=clean_text,
        agent_task=agent_task,
    )
    canonical_hash = sha256_bytes(canonical_data)

    drive_file = None
    upload_error = None
    clean_drive_folder_id = parse_drive_folder_id(drive_folder_id)
    if upload_to_drive:
        try:
            client = GoogleDriveClient(store=store)
            parent_id = clean_drive_folder_id or parse_drive_folder_id()
            target_folder_id = parent_id
            if parent_id and drive_subfolder:
                target_folder_id = client.ensure_folder(parent_id, drive_subfolder)["id"]
            drive_file = client.upload_file(
                name=canonical_filename,
                data=canonical_data,
                mime_type="text/markdown; charset=utf-8",
                folder_id=target_folder_id,
                description=(
                    f"Markdown conversion created by Investment Brain agent from {document.final_url}. "
                    f"Original format: {document.extension}."
                ),
            )
        except Exception as exc:
            upload_error = str(exc)[:500]
            if upload_to_drive:
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
        **extraction_metadata,
    }
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
            },
        },
    }


def _target_years_from_query(query: str) -> set[str]:
    years = {match.group(0) for match in re.finditer(r"\b20\d{2}\b", query)}
    return years


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
    patterns = [
        rf"(?:^|[^a-z0-9])q{quarter}[-_ ]?{short_year}(?:$|[^a-z0-9])",
        rf"(?:^|[^a-z0-9])q{quarter}[-_ ]?{year}(?:$|[^a-z0-9])",
        rf"(?:^|[^a-z0-9]){year}[-_ ]?q{quarter}(?:$|[^a-z0-9])",
        rf"(?:^|[^a-z0-9]){short_year}[-_ ]?q{quarter}(?:$|[^a-z0-9])",
    ]
    return any(re.search(pattern, clean) for pattern in patterns)


def _document_has_different_quarter(document_text: str, *, quarter: int, years: set[str]) -> bool:
    clean = document_text.lower()
    for match in re.finditer(r"(?:^|[^a-z0-9])q([1-4])[-_ ]?(\d{2}|\d{4})(?:$|[^a-z0-9])", clean):
        found_quarter = int(match.group(1))
        found_year = match.group(2)
        normalized_year = f"20{found_year}" if len(found_year) == 2 else found_year
        if found_quarter != quarter or (years and normalized_year not in years):
            return True
    return False


def _filing_is_before_target_quarter_end(filing_date: str, *, quarter: int, year: str) -> bool:
    if not filing_date.startswith(year) or len(filing_date) < 7:
        return False
    try:
        filing_month = int(filing_date[5:7])
    except ValueError:
        return False
    return filing_month <= quarter * 3


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


def _sec_get_json(url: str) -> Any:
    with httpx.Client(timeout=45, headers={"User-Agent": _agent_user_agent(), "Accept": "application/json"}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def resolve_sec_company(company: str | None = None, ticker: str | None = None) -> dict[str, Any] | None:
    inferred_ticker = _infer_ticker(company, ticker)
    companies = _sec_get_json(SEC_COMPANY_TICKERS_URL)
    rows = companies.values() if isinstance(companies, dict) else companies
    clean_company = (company or "").strip().lower()

    best: dict[str, Any] | None = None
    for row in rows:
        row_ticker = str(row.get("ticker") or "").upper()
        row_title = str(row.get("title") or "")
        if inferred_ticker and row_ticker == inferred_ticker:
            best = row
            break
        if clean_company and clean_company in row_title.lower():
            best = row
            break
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
    document_text = f"{description or ''} {document or ''}"
    score = 1.0
    if form in {"10-K", "10-Q", "8-K", "6-K", "20-F"}:
        score += 2.0
    if "results" in clean_query or "earnings" in clean_query:
        if form in {"8-K", "6-K"}:
            score += 4.0
        if form in {"10-K", "10-Q"}:
            score += 2.0
    if "q4" in clean_query or "fourth quarter" in clean_query:
        if form in {"8-K", "10-K"}:
            score += 3.0
    for year in years:
        if year in (report_date or ""):
            score += 4.0
        if year in filing_date:
            score += 2.0
        if target_quarter and _quarter_from_date(report_date) == target_quarter and str(report_date or "").startswith(year):
            score += 8.0
        if target_quarter == 4 and filing_date.startswith(str(int(year) + 1)) and filing_date[5:7] in {"01", "02"}:
            score += 4.0
        if target_quarter and _document_has_target_quarter(document_text, quarter=target_quarter, year=year):
            score += 8.0
        if needs_results and target_quarter and _filing_is_before_target_quarter_end(filing_date, quarter=target_quarter, year=year):
            score -= 14.0
    if target_quarter and years and _document_has_different_quarter(document_text, quarter=target_quarter, years=years):
        score -= 5.0
    if any(term in document_text.lower() for term in ("stocksplit", "stock split", "compensation", "employment agreement", "bylaws")):
        score -= 8.0
    if description and any(term in description.lower() for term in ("earnings", "results", "ex-99", "press release")):
        score += 2.0
    return score


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
    recent = submissions.get("filings", {}).get("recent", {})
    candidates: list[dict[str, Any]] = []
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    descriptions = recent.get("primaryDocDescription", [])
    needs_results = _query_needs_results_document(task)
    target_quarter = _target_quarter_from_query(task)
    target_years = _target_years_from_query(task)

    for index, form in enumerate(forms):
        if form not in {"10-K", "10-Q", "8-K", "6-K", "20-F"}:
            continue
        accession = accessions[index]
        primary_doc = primary_docs[index]
        filing_date = filing_dates[index]
        report_date = report_dates[index] if index < len(report_dates) else None
        description = descriptions[index] if index < len(descriptions) else None
        score = _score_filing(task, form, filing_date, report_date, description, primary_doc)
        primary_url = _filing_document_url(resolved["cikInt"], accession, primary_doc)
        candidates.append({
            "title": f"{resolved['ticker']} {form} filed {filing_date}",
            "url": primary_url,
            "source": "SEC EDGAR",
            "domain": "sec.gov",
            "form": form,
            "filingDate": filing_date,
            "reportDate": report_date,
            "accessionNumber": accession,
            "document": primary_doc,
            "score": round(score, 2),
            "confidence": min(0.98, score / 12.0),
            "reason": f"Official SEC {form} filing. {description or ''}".strip(),
            "trusted": True,
        })

        if form in {"8-K", "6-K"} and score >= 10:
            for item in _sec_directory_documents(resolved["cikInt"], accession):
                name = str(item.get("name") or "")
                low_name = name.lower()
                if not name or name == primary_doc:
                    continue
                if not any(term in low_name for term in ("ex99", "ex-99", "exhibit", "earn", "result", "press")):
                    continue
                if not any(low_name.endswith(ext) for ext in (".htm", ".html", ".pdf", ".txt")):
                    continue
                if needs_results and target_quarter and target_years and not any(
                    _document_has_target_quarter(name, quarter=target_quarter, year=year)
                    for year in target_years
                ) and not any(term in low_name for term in ("earn", "result", "letter")):
                    continue
                item_score = _score_filing(task, form, filing_date, report_date, f"{description or ''} {name}", name) + 3.0
                candidates.append({
                    "title": f"{resolved['ticker']} earnings exhibit {filing_date}",
                    "url": _filing_document_url(resolved["cikInt"], accession, name),
                    "source": "SEC EDGAR exhibit",
                    "domain": "sec.gov",
                    "form": form,
                    "filingDate": filing_date,
                    "reportDate": report_date,
                    "accessionNumber": accession,
                    "document": name,
                    "score": round(item_score, 2),
                    "confidence": min(0.99, item_score / 12.0),
                    "reason": "Official SEC filing exhibit likely containing the earnings release or result document.",
                    "trusted": True,
                })

    candidates = sorted(candidates, key=lambda item: (item.get("score", 0), item.get("confidence", 0), item.get("filingDate") or ""), reverse=True)
    return {
        "query": task,
        "resolvedCompany": resolved,
        "candidates": candidates[: max(1, min(int(limit), 20))],
        "message": f"Found {len(candidates)} official SEC candidate(s).",
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
    )
