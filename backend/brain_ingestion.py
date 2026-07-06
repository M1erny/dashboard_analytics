import hashlib
import re
from typing import Any


def normalize_text(value: str) -> str:
    """Collapse noisy whitespace while preserving paragraph breaks."""
    text = value.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def estimate_tokens(text: str) -> int:
    # Cheap approximation. Good enough for chunk budgeting before model-specific tokenizers are connected.
    return max(1, int(len(text.split()) * 1.3))


def stable_hash(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8", errors="ignore"))
        digest.update(b"\x00")
    return digest.hexdigest()


def chunk_text(
    text: str,
    *,
    source_title: str,
    tags: list[str] | None = None,
    chunk_words: int = 900,
    overlap_words: int = 120,
) -> list[dict[str, Any]]:
    clean_text = normalize_text(text)
    words = clean_text.split()
    if not words:
        return []

    chunk_words = max(150, min(int(chunk_words), 2500))
    overlap_words = max(0, min(int(overlap_words), chunk_words // 2))
    step = max(1, chunk_words - overlap_words)
    clean_tags = tags or []
    chunks: list[dict[str, Any]] = []

    for ordinal, start in enumerate(range(0, len(words), step)):
        part_words = words[start:start + chunk_words]
        if not part_words:
            break

        body = " ".join(part_words).strip()
        if not body:
            continue

        chunks.append(
            {
                "ordinal": ordinal,
                "title": f"{source_title} - chunk {ordinal + 1}",
                "body": body,
                "summary": None,
                "tokenCount": estimate_tokens(body),
                "tags": clean_tags,
                "metadata": {
                    "wordStart": start,
                    "wordEnd": start + len(part_words),
                    "chunker": "word-window-v1",
                },
                "contentHash": stable_hash(source_title, str(ordinal), body),
                "embeddingModel": None,
                "embedding": None,
            }
        )

        if start + chunk_words >= len(words):
            break

    return chunks
