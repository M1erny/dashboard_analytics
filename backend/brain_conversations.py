"""Durable, Obsidian-compatible Google Drive transcripts for Brain threads."""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any


TRANSCRIPT_SCHEMA = "investment-brain-thread/v1"
THREAD_PROPERTY_KEY = "brainThreadId"
EXCHANGE_MARKER_PREFIX = "brain-exchange:"
MAX_TRANSCRIPT_BYTES = 25 * 1024 * 1024
MAX_CONTEXT_STRING_CHARS = 24_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: str, *, max_length: int = 72) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return (clean or "research-thread")[:max_length].rstrip("-")


def _markdown_label(value: Any) -> str:
    return re.sub(r"[\[\]\r\n]+", " ", str(value or "Untitled source")).strip()


def _json_safe(value: Any, *, string_limit: int = MAX_CONTEXT_STRING_CHARS) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value if len(value) <= string_limit else value[:string_limit] + "\n[truncated in transcript]"
    if isinstance(value, dict):
        return {str(key): _json_safe(item, string_limit=string_limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, string_limit=string_limit) for item in value]
    return str(value)


def _source_from_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    source = item.get("source") if isinstance(item.get("source"), dict) else item
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    source_id = source.get("id") or item.get("sourceId")
    title = source.get("title") or source.get("fileName") or source.get("relativePath") or item.get("title")
    drive_file_id = source.get("driveFileId") or metadata.get("driveFileId") or metadata.get("id")
    url = (
        source.get("webUrl")
        or metadata.get("webViewLink")
        or metadata.get("driveWebViewLink")
        or metadata.get("sourceUrl")
        or metadata.get("finalUrl")
    )
    if not url and drive_file_id:
        url = f"https://drive.google.com/file/d/{drive_file_id}/view"
    if not title and not source_id:
        return None
    return {
        "sourceId": source_id,
        "title": title or f"Source {source_id}",
        "url": url,
        "driveFileId": drive_file_id,
        "relativePath": source.get("relativePath") or metadata.get("relativePath"),
        "sourceType": source.get("sourceType") or metadata.get("sourceType"),
    }


def _collect_sources(context: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in context.get("retrieved", []) or []:
        source = _source_from_item(item)
        if source:
            candidates.append(source)
    for key in ("deepSources", "references", "fullDocuments"):
        for item in context.get(key, []) or []:
            source = _source_from_item(item)
            if source:
                candidates.append(source)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in candidates:
        identity = str(source.get("sourceId") or source.get("driveFileId") or source.get("url") or source.get("title"))
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(source)
    return deduped


def _compact_portfolio(portfolio: dict[str, Any] | None) -> dict[str, Any] | None:
    if not portfolio:
        return None
    positions = []
    for item in portfolio.get("positions", []) or []:
        positions.append({
            key: item.get(key)
            for key in (
                "ticker", "side", "targetWeight", "currentWeight", "signedCurrentWeight",
                "lastPrice", "returns", "positionMomentum", "ytdContribution",
                "sinceRebalanceContribution", "volume", "technical",
            )
            if key in item
        })
    return {
        "portfolio": portfolio.get("portfolio"),
        "generatedAt": portfolio.get("generatedAt"),
        "dataAsOf": portfolio.get("dataAsOf"),
        "fresh": portfolio.get("fresh"),
        "marketDataAvailable": portfolio.get("marketDataAvailable"),
        "source": portfolio.get("source"),
        "exposure": portfolio.get("exposure"),
        "performance": portfolio.get("performance"),
        "performanceRankings": portfolio.get("performanceRankings"),
        "concentration": portfolio.get("concentration"),
        "momentum": portfolio.get("momentum"),
        "volumeMomentumScreen": portfolio.get("volumeMomentumScreen"),
        "risk": portfolio.get("risk"),
        "positions": positions,
    }


def _context_manifest(
    *,
    exchange_id: str,
    saved_at: str,
    question: str,
    answer: str,
    model: str,
    embedding_model: str,
    system_prompt_hash: str,
    retrieval: dict[str, Any],
    context: dict[str, Any],
    timings: dict[str, Any],
) -> dict[str, Any]:
    manifest = {
        "schema": "investment-brain-exchange/v1",
        "exchangeId": exchange_id,
        "savedAt": saved_at,
        "messages": {"user": question, "assistant": answer},
        "model": model,
        "embeddingModel": embedding_model,
        "backendRevision": os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT") or "unknown",
        "systemPromptSha256": system_prompt_hash,
        "retrieval": retrieval,
        "timingsMs": timings,
        "context": {
            "memories": context.get("memories", []),
            "retrieved": context.get("retrieved", []),
            "deepSources": context.get("deepSources", []),
            "references": context.get("references", []),
            "fullDocuments": context.get("fullDocuments", []),
            "portfolio": _compact_portfolio(context.get("portfolio")),
        },
    }
    return _json_safe(manifest)


def _new_transcript(*, thread_id: str, title: str, created_at: str) -> str:
    quoted_title = json.dumps(title, ensure_ascii=False)
    return (
        "---\n"
        f"schema: {TRANSCRIPT_SCHEMA}\n"
        f"thread_id: {json.dumps(thread_id)}\n"
        f"title: {quoted_title}\n"
        f"created_at: {json.dumps(created_at)}\n"
        f"updated_at: {json.dumps(created_at)}\n"
        "exchange_count: 0\n"
        "tags:\n"
        "  - investment-brain\n"
        "  - research-thread\n"
        "---\n\n"
        f"# {title}\n\n"
        "> Durable Brain transcript. Human-readable Markdown, Obsidian-compatible YAML, and one JSON context manifest per exchange.\n"
    )


def _conversation_folder(client: Any, root_folder_id: str) -> dict[str, Any]:
    brain_folder = client.ensure_folder(root_folder_id, "Investment Brain")
    return client.ensure_folder(brain_folder["id"], "Conversations")


def _frontmatter_value(transcript: str, key: str) -> Any:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", transcript, flags=re.MULTILINE)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_brain_conversation(transcript: str) -> dict[str, Any]:
    manifests: list[dict[str, Any]] = []
    exchange_markers = list(re.finditer(
        rf"^<!-- {re.escape(EXCHANGE_MARKER_PREFIX)}[A-Za-z0-9_-]+ -->\s*$",
        transcript,
        flags=re.MULTILINE,
    ))
    for index, marker in enumerate(exchange_markers):
        segment_end = exchange_markers[index + 1].start() if index + 1 < len(exchange_markers) else len(transcript)
        segment = transcript[marker.end():segment_end]
        manifest_heading = segment.rfind("<summary>Machine-readable exchange manifest</summary>")
        if manifest_heading < 0:
            continue
        match = re.search(r"````json\s*(.*?)\s*````", segment[manifest_heading:], flags=re.DOTALL)
        if not match:
            continue
        try:
            manifest = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if manifest.get("schema") == "investment-brain-exchange/v1":
            manifests.append(manifest)

    messages: list[dict[str, Any]] = []
    for manifest in manifests:
        exchange_id = str(manifest.get("exchangeId") or len(messages) // 2)
        exchange_messages = manifest.get("messages") if isinstance(manifest.get("messages"), dict) else {}
        question = str(exchange_messages.get("user") or "").strip()
        answer = str(exchange_messages.get("assistant") or "").strip()
        if question:
            messages.append({"id": f"{exchange_id}-user", "role": "user", "content": question})
        if answer:
            messages.append({
                "id": f"{exchange_id}-assistant",
                "role": "assistant",
                "content": answer,
                "context": manifest.get("context"),
                "retrieval": manifest.get("retrieval"),
                "timingMs": (manifest.get("timingsMs") or {}).get("totalMs"),
            })
    return {
        "schema": _frontmatter_value(transcript, "schema"),
        "threadId": _frontmatter_value(transcript, "thread_id"),
        "title": _frontmatter_value(transcript, "title"),
        "createdAt": _frontmatter_value(transcript, "created_at"),
        "updatedAt": _frontmatter_value(transcript, "updated_at"),
        "exchangeCount": _frontmatter_value(transcript, "exchange_count") or len(manifests),
        "messages": messages,
    }


def list_brain_conversations(client: Any, *, root_folder_id: str, limit: int = 50) -> dict[str, Any]:
    folder = _conversation_folder(client, root_folder_id)
    files = client.list_files_by_app_property(
        folder["id"],
        "brainTranscriptSchema",
        TRANSCRIPT_SCHEMA,
        limit=limit,
    )
    items = []
    for file in files:
        properties = file.get("appProperties") if isinstance(file.get("appProperties"), dict) else {}
        thread_id = properties.get(THREAD_PROPERTY_KEY)
        if not thread_id:
            continue
        items.append({
            "threadId": thread_id,
            "title": properties.get("brainThreadTitle") or file.get("name"),
            "exchangeCount": int(properties.get("brainExchangeCount") or 0),
            "fileId": file.get("id"),
            "fileName": file.get("name"),
            "webViewLink": file.get("webViewLink"),
            "createdAt": file.get("createdTime"),
            "updatedAt": file.get("modifiedTime"),
            "size": int(file.get("size") or 0),
        })
    return {
        "folderId": folder.get("id"),
        "threads": items,
    }


def load_brain_conversation(client: Any, *, root_folder_id: str, thread_id: str) -> dict[str, Any] | None:
    folder = _conversation_folder(client, root_folder_id)
    file = client.find_file_by_app_property(folder["id"], THREAD_PROPERTY_KEY, thread_id)
    if not file:
        return None
    content, _, _ = client.download_file(file, max_bytes=MAX_TRANSCRIPT_BYTES)
    parsed = parse_brain_conversation(content.decode("utf-8", errors="replace"))
    parsed.update({
        "fileId": file.get("id"),
        "fileName": file.get("name"),
        "webViewLink": file.get("webViewLink"),
        "modifiedTime": file.get("modifiedTime"),
    })
    return parsed


def _update_frontmatter(text: str, *, updated_at: str, exchange_count: int) -> str:
    text = re.sub(r'^updated_at:.*$', f"updated_at: {json.dumps(updated_at)}", text, count=1, flags=re.MULTILINE)
    return re.sub(r'^exchange_count:.*$', f"exchange_count: {exchange_count}", text, count=1, flags=re.MULTILINE)


def _system_prompt_snapshot(system_prompt: str, prompt_hash: str) -> str:
    return (
        "\n\n<details>\n"
        f"<summary>System prompt snapshot {prompt_hash[:12]}</summary>\n\n"
        f"<!-- system-prompt:{prompt_hash} -->\n"
        f"<pre>{html.escape(system_prompt)}</pre>\n"
        "</details>\n"
    )


def _exchange_markdown(
    *,
    exchange_id: str,
    saved_at: str,
    question: str,
    answer: str,
    model: str,
    embedding_model: str,
    system_prompt_hash: str,
    retrieval: dict[str, Any],
    context: dict[str, Any],
    timings: dict[str, Any],
) -> str:
    sources = _collect_sources(context)
    source_lines = []
    for source in sources:
        label = _markdown_label(source.get("title"))
        identity = f"source {source.get('sourceId')}" if source.get("sourceId") is not None else "Drive source"
        if source.get("url"):
            source_lines.append(f"- [{label}]({source['url']}) ({identity})")
        else:
            source_lines.append(f"- {label} ({identity})")

    manifest = _context_manifest(
        exchange_id=exchange_id,
        saved_at=saved_at,
        question=question,
        answer=answer,
        model=model,
        embedding_model=embedding_model,
        system_prompt_hash=system_prompt_hash,
        retrieval=retrieval,
        context=context,
        timings=timings,
    )
    portfolio = context.get("portfolio") or {}
    context_summary = (
        f"- Model: `{model}`; embeddings: `{embedding_model}`\n"
        f"- System prompt: `{system_prompt_hash[:12]}`\n"
        f"- Market data: `{portfolio.get('dataAsOf') or 'not fetched'}`; live: `{bool(portfolio.get('marketDataAvailable'))}`\n"
        f"- Retrieval: semantic `{retrieval.get('semanticHits', 0)}`, exact `{retrieval.get('keywordHits', 0)}`, expanded files `{retrieval.get('expandedFiles', 0)}`\n"
    )
    return (
        f"\n\n## {saved_at} - Exchange\n"
        f"<!-- {EXCHANGE_MARKER_PREFIX}{exchange_id} -->\n\n"
        "### You\n\n"
        f"{question.strip()}\n\n"
        "### Investment Brain\n\n"
        f"{answer.strip()}\n\n"
        "### Context\n\n"
        f"{context_summary}\n"
        "#### Sources used\n\n"
        f"{chr(10).join(source_lines) if source_lines else '- No Drive or web source was attached to this exchange.'}\n\n"
        "<details>\n"
        "<summary>Machine-readable exchange manifest</summary>\n\n"
        "````json\n"
        f"{json.dumps(manifest, ensure_ascii=False, indent=2)}\n"
        "````\n"
        "</details>\n"
    )


def autosave_brain_conversation(
    client: Any,
    *,
    root_folder_id: str,
    thread_id: str,
    exchange_id: str,
    title: str,
    question: str,
    answer: str,
    model: str,
    embedding_model: str,
    system_prompt: str,
    retrieval: dict[str, Any],
    context: dict[str, Any],
    timings: dict[str, Any],
) -> dict[str, Any]:
    saved_at = _utc_now()
    conversations_folder = _conversation_folder(client, root_folder_id)
    existing = client.find_file_by_app_property(conversations_folder["id"], THREAD_PROPERTY_KEY, thread_id)
    clean_title = re.sub(r"\s+", " ", title).strip()[:160] or "Investment Brain research thread"
    prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
    marker = f"<!-- {EXCHANGE_MARKER_PREFIX}{exchange_id} -->"

    if existing:
        content, _, _ = client.download_file(existing, max_bytes=MAX_TRANSCRIPT_BYTES)
        transcript = content.decode("utf-8", errors="replace")
        file_name = str(existing.get("name") or f"{_slug(clean_title)}-{thread_id[:8]}.md")
        if marker in transcript:
            return {
                "status": "unchanged",
                "threadId": thread_id,
                "exchangeId": exchange_id,
                "fileId": existing.get("id"),
                "fileName": file_name,
                "webViewLink": existing.get("webViewLink"),
                "savedAt": saved_at,
                "format": "markdown+yaml+json",
            }
    else:
        transcript = _new_transcript(thread_id=thread_id, title=clean_title, created_at=saved_at)
        file_name = f"{saved_at[:10]} - {_slug(clean_title)} - {thread_id[:8]}.md"

    if f"<!-- system-prompt:{prompt_hash} -->" not in transcript:
        transcript += _system_prompt_snapshot(system_prompt, prompt_hash)
    transcript += _exchange_markdown(
        exchange_id=exchange_id,
        saved_at=saved_at,
        question=question,
        answer=answer,
        model=model,
        embedding_model=embedding_model,
        system_prompt_hash=prompt_hash,
        retrieval=retrieval,
        context=context,
        timings=timings,
    )
    exchange_count = len(re.findall(
        rf"^<!-- {re.escape(EXCHANGE_MARKER_PREFIX)}[A-Za-z0-9_-]+ -->\s*$",
        transcript,
        flags=re.MULTILINE,
    ))
    transcript = _update_frontmatter(transcript, updated_at=saved_at, exchange_count=exchange_count)
    encoded = transcript.encode("utf-8")
    if len(encoded) > MAX_TRANSCRIPT_BYTES:
        raise RuntimeError("Conversation transcript reached the 25 MB safety limit; start a new Brain thread.")

    properties = {
        THREAD_PROPERTY_KEY: thread_id,
        "brainTranscriptSchema": TRANSCRIPT_SCHEMA,
        "brainThreadTitle": clean_title[:100],
        "brainExchangeCount": str(exchange_count),
    }
    description = f"Investment Brain transcript {thread_id}. Obsidian-compatible Markdown with structured exchange manifests."
    if existing:
        file = client.update_file(
            existing["id"],
            name=file_name,
            data=encoded,
            mime_type="text/markdown",
            description=description,
            app_properties=properties,
        )
    else:
        file = client.upload_file(
            name=file_name,
            data=encoded,
            mime_type="text/markdown",
            folder_id=conversations_folder["id"],
            description=description,
            app_properties=properties,
        )
    return {
        "status": "saved",
        "threadId": thread_id,
        "exchangeId": exchange_id,
        "fileId": file.get("id"),
        "fileName": file.get("name") or file_name,
        "webViewLink": file.get("webViewLink"),
        "folderId": conversations_folder.get("id"),
        "savedAt": saved_at,
        "exchangeCount": exchange_count,
        "format": "markdown+yaml+json",
    }
