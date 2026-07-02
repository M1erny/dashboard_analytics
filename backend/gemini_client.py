import os
from pathlib import Path
from typing import Any

import httpx


DEFAULT_GENERATION_MODEL = "gemini-2.5-flash"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
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

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def status(self) -> dict[str, Any]:
        return {
            "provider": "google_ai_studio",
            "configured": self.configured,
            "generationModel": self.generation_model,
            "embeddingModel": self.embedding_model,
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

        with httpx.Client(timeout=60) as client:
            response = client.post(url, params={"key": api_key}, json=payload)
            response.raise_for_status()
            data = response.json()

        values = data.get("embedding", {}).get("values")
        if not isinstance(values, list):
            raise RuntimeError("Gemini embedding response did not include embedding values")
        return [float(value) for value in values]

    def generate_text(
        self,
        prompt: str,
        *,
        temperature: float = 0.25,
        max_output_tokens: int = 1800,
    ) -> str:
        api_key = self._require_key()
        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            raise ValueError("Cannot generate from empty prompt")

        url = f"{GEMINI_API_BASE}/models/{self.generation_model}:generateContent"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": clean_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }

        with httpx.Client(timeout=90) as client:
            response = client.post(url, params={"key": api_key}, json=payload)
            response.raise_for_status()
            data = response.json()

        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        answer = "\n".join(part for part in text_parts if part).strip()
        if not answer:
            raise RuntimeError("Gemini generation response did not include text")
        return answer
