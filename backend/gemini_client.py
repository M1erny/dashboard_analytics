import json
import os
import re
from pathlib import Path
from typing import Any

import httpx


DEFAULT_GENERATION_MODEL = "gemini-3.5-flash-lite"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_THINKING_BUDGET = 0
DEFAULT_THINKING_LEVEL = "minimal"
VALID_THINKING_LEVELS = {"minimal", "low", "medium", "high"}
DEFAULT_REQUEST_TIMEOUT = 45.0
DEFAULT_EMBEDDING_TIMEOUT = 15.0
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def load_backend_env() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
                os.environ[key] = value


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _safe_provider_error(error: Exception) -> str:
    text = str(error)
    if isinstance(error, httpx.HTTPStatusError):
        response_text = error.response.text[:500] if error.response is not None else ""
        text = f"Google AI returned HTTP {error.response.status_code}: {response_text}"

    text = re.sub(r"key=([^&\s]+)", "key=<redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(api[_-]?key|secret|token)=([^\s&]+)", r"\1=<redacted>", text, flags=re.IGNORECASE)
    return text[:800]


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = None,
        generation_model: str | None = None,
        embedding_model: str | None = None,
    ):
        load_backend_env()
        self.api_key = (
            api_key
            or os.environ.get("GOOGLE_AI_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        self.generation_model = (
            generation_model
            or os.environ.get("BRAIN_LLM_MODEL")
            or DEFAULT_GENERATION_MODEL
        )
        self.embedding_model = (
            embedding_model
            or os.environ.get("BRAIN_EMBEDDING_MODEL")
            or DEFAULT_EMBEDDING_MODEL
        )
        self.thinking_budget = _env_int("BRAIN_LLM_THINKING_BUDGET", DEFAULT_THINKING_BUDGET)
        configured_thinking_level = os.environ.get("BRAIN_LLM_THINKING_LEVEL", "").strip().lower()
        self.thinking_level = (
            configured_thinking_level
            if configured_thinking_level in VALID_THINKING_LEVELS
            else DEFAULT_THINKING_LEVEL
        )
        self.request_timeout = _env_float("BRAIN_LLM_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT)
        self.embedding_timeout = _env_float("BRAIN_EMBEDDING_TIMEOUT_SECONDS", DEFAULT_EMBEDDING_TIMEOUT)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def status(self) -> dict[str, Any]:
        return {
            "provider": "google_ai_studio",
            "configured": self.configured,
            "generationModel": self.generation_model,
            "embeddingModel": self.embedding_model,
            "thinkingBudget": self.thinking_budget,
            "thinkingLevel": self.thinking_level if self.generation_model.startswith("gemini-3.5") else None,
            "requestTimeoutSeconds": self.request_timeout,
            "embeddingTimeoutSeconds": self.embedding_timeout,
            "apiKeyEnv": "GOOGLE_AI_API_KEY or GEMINI_API_KEY",
        }

    def _require_key(self) -> str:
        if not self.api_key:
            raise RuntimeError("Google AI API key is not configured")
        return self.api_key

    def embed_text(self, text: str, *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
        api_key = self._require_key()
        clean_text = (text or "").strip()
        if not clean_text:
            raise ValueError("Cannot embed empty text")

        url = f"{GEMINI_API_BASE}/models/{self.embedding_model}:embedContent"
        payload = {
            "model": f"models/{self.embedding_model}",
            "content": {"parts": [{"text": clean_text[:24000]}]},
            "taskType": task_type,
        }

        with httpx.Client(timeout=self.embedding_timeout) as client:
            try:
                response = client.post(url, params={"key": api_key}, json=payload)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Gemini embedding timed out after {self.embedding_timeout:.0f}s") from exc
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(_safe_provider_error(exc)) from exc
            data = response.json()

        values = data.get("embedding", {}).get("values")
        if not isinstance(values, list):
            raise RuntimeError("Gemini embedding response did not include embedding values")
        return [float(value) for value in values]

    def embed_texts(self, texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        """Embed multiple chunks in one Gemini request while preserving input order."""
        api_key = self._require_key()
        clean_texts = [(text or "").strip() for text in texts]
        if not clean_texts or any(not text for text in clean_texts):
            raise ValueError("Cannot embed an empty batch or empty text")

        url = f"{GEMINI_API_BASE}/models/{self.embedding_model}:batchEmbedContents"
        payload = {
            "requests": [
                {
                    "model": f"models/{self.embedding_model}",
                    "content": {"parts": [{"text": text[:24000]}]},
                    "taskType": task_type,
                }
                for text in clean_texts
            ]
        }

        # A batch contains more work than a single query embedding. Keep the
        # interactive timeout configurable while allowing the worker enough room.
        timeout = max(self.embedding_timeout, 45.0)
        with httpx.Client(timeout=timeout) as client:
            try:
                response = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Gemini embedding batch timed out after {timeout:.0f}s") from exc
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(_safe_provider_error(exc)) from exc
            data = response.json()

        raw_embeddings = data.get("embeddings")
        if not isinstance(raw_embeddings, list) or len(raw_embeddings) != len(clean_texts):
            raise RuntimeError("Gemini embedding batch response did not match the submitted chunks")

        embeddings: list[list[float]] = []
        for item in raw_embeddings:
            values = item.get("values") if isinstance(item, dict) else None
            if not isinstance(values, list):
                raise RuntimeError("Gemini embedding batch response included an invalid vector")
            embeddings.append([float(value) for value in values])
        return embeddings

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.25,
        max_output_tokens: int = 900,
        timeout_seconds: float | None = None,
    ) -> str:
        return self._generate(
            prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )

    def generate_json(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any],
        system_instruction: str | None = None,
        temperature: float = 0.15,
        max_output_tokens: int = 8000,
        timeout_seconds: float | None = None,
        model: str | None = None,
        thinking_level: str | None = None,
    ) -> Any:
        """Generate a JSON document that conforms to response_schema.

        Gemini honours responseSchema, but a schema-constrained answer can still
        arrive fenced or truncated, so the caller gets a decoded object or a
        RuntimeError that says which of the two happened.
        """
        raw = self._generate(
            prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            model=model,
            thinking_level=thinking_level,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Gemini returned a response that is not valid JSON "
                f"({exc.msg} at character {exc.pos}). The answer was most likely "
                "truncated by the output token limit."
            ) from exc

    def _generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.25,
        max_output_tokens: int = 900,
        timeout_seconds: float | None = None,
        model: str | None = None,
        thinking_level: str | None = None,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        api_key = self._require_key()
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            raise ValueError("Cannot generate from empty prompt")

        generation_model = (model or self.generation_model).strip()
        url = f"{GEMINI_API_BASE}/models/{generation_model}:generateContent"
        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        }
        if response_mime_type:
            generation_config["responseMimeType"] = response_mime_type
        if response_schema:
            generation_config["responseSchema"] = response_schema
        requested_level = (thinking_level or self.thinking_level or "").strip().lower()
        if requested_level not in VALID_THINKING_LEVELS:
            requested_level = self.thinking_level
        if generation_model.startswith("gemini-3.5"):
            generation_config["thinkingConfig"] = {"thinkingLevel": requested_level}
        elif self.thinking_budget is not None:
            generation_config["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": clean_prompt}],
                }
            ],
            "generationConfig": generation_config,
        }
        clean_system_instruction = (system_instruction or "").strip()
        if clean_system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": clean_system_instruction[:12000]}],
            }

        request_timeout = timeout_seconds or self.request_timeout
        with httpx.Client(timeout=request_timeout) as client:
            try:
                response = client.post(url, params={"key": api_key}, json=payload)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"Gemini request timed out after {request_timeout:.0f}s") from exc

            if response.status_code == 400 and "thinkingConfig" in generation_config:
                generation_config.pop("thinkingConfig", None)
                response = client.post(url, params={"key": api_key}, json=payload)

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(_safe_provider_error(exc)) from exc
            data = response.json()

        candidates = data.get("candidates") or []
        candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
        parts = (candidate.get("content") or {}).get("parts") or []
        text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        answer = "\n".join(part for part in text_parts if part).strip()
        if not answer:
            # An empty answer is usually a truncation, a safety block, or thinking
            # that consumed the whole output allowance. Say which one.
            reasons = [f"model={generation_model}", f"finishReason={candidate.get('finishReason') or 'unknown'}"]
            block_reason = (data.get("promptFeedback") or {}).get("blockReason")
            if block_reason:
                reasons.append(f"blockReason={block_reason}")
            raise RuntimeError(
                f"Gemini generation response did not include text ({', '.join(reasons)})"
            )
        return answer
