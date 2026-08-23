"""Abstracted LLM access (Section 3).

LLMRouter is the only client the orchestrator ever imports. It tries FreeTierClient
(Groq) first and falls back to OllamaClient (Qwen2.5-Coder:7B) when the primary is
unavailable, rate-limited (429), or errors.

Prior art consulted per Section 8: LiteLLM's MIT-licensed router (fallback-on-429
pattern). Pattern adapted, code written from scratch — no vendored dependency.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol


class LLMError(Exception):
    pass


class RateLimitError(LLMError):
    pass


class LLMResponse:
    def __init__(self, text: str = "", raw: dict | None = None):
        self.text = text
        self.raw = raw or {}
        self.served_by: str | None = None


class LLMClient(Protocol):
    def complete(self, prompt: str, tools: list[dict] | None = None) -> LLMResponse: ...

    def is_available(self) -> bool: ...


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimitError(f"rate limited by {url}") from exc
        raise LLMError(f"HTTP {exc.code} from {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"cannot reach {url}: {exc.reason}") from exc


class FreeLLMAPIClient:
    """Self-hosted FreeLLMAPI gateway (OpenAI-compatible, MIT: tashfeenahmed/freellmapi).

    One unified key routes across every upstream free-tier provider configured in
    its dashboard. Base URL/key/model come from settings.json (or env overrides).
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        from evo.automation.db import get_setting

        self.base_url = (
            base_url
            or os.environ.get("FREELLMAPI_BASE_URL")
            or get_setting("freellmapi_base_url", "http://localhost:3001/v1")
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("FREELLMAPI_API_KEY") or get_setting("freellmapi_api_key", "")
        self.model = model or os.environ.get("FREELLMAPI_MODEL") or get_setting("freellmapi_model", "auto")

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def complete(self, prompt: str, tools: list[dict] | None = None) -> LLMResponse:
        if not self.api_key:
            raise LLMError("FreeLLMAPIClient has no API key")
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            payload["tools"] = tools
        raw = _post_json(
            f"{self.base_url}/chat/completions",
            payload,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=120.0,
        )
        try:
            text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected FreeLLMAPI response shape: {raw}") from exc
        return LLMResponse(text=text, raw=raw)

    def list_models(self) -> list[dict]:
        """Full gateway catalog (used by the abilities page)."""
        if not self.api_key:
            return []
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"}
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return json.loads(resp.read()).get("data", [])
        except Exception:
            return []


class GroqClient:
    """FreeTierClient implementation against Groq's OpenAI-compatible endpoint.

    Key resolution order: GROQ_API_KEY env var -> settings.json 'groq_api_key'.
    """

    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str | None = None, model: str = "llama-3.1-8b-instant"):
        self.model = model
        self.api_key = api_key or os.environ.get("GROQ_API_KEY") or self._key_from_settings()

    @staticmethod
    def _key_from_settings() -> str:
        from evo.automation.db import get_setting

        return get_setting("groq_api_key", "")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, tools: list[dict] | None = None) -> LLMResponse:
        if not self.api_key:
            raise LLMError("GroqClient has no API key (set GROQ_API_KEY)")
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            payload["tools"] = tools
        raw = _post_json(
            self.BASE_URL,
            payload,
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=60.0,
        )
        try:
            text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected Groq response shape: {raw}") from exc
        return LLMResponse(text=text, raw=raw)


# Backwards-compatible alias for the Section 3 name used across the spec.
FreeTierClient = GroqClient


class OllamaClient:
    """Local fallback: Qwen2.5-Coder:7B via Ollama."""

    def __init__(self, model: str | None = None, base_url: str | None = None):
        from evo.automation.db import get_setting

        self.model = (
            model
            or os.environ.get("OLLAMA_MODEL")
            or get_setting("ollama_model", "qwen2.5-coder:7b")
        )
        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def complete(self, prompt: str, tools: list[dict] | None = None) -> LLMResponse:
        raw = _post_json(
            f"{self.base_url}/api/generate",
            {"model": self.model, "prompt": prompt, "stream": False},
            {"Content-Type": "application/json"},
            timeout=600.0,
        )
        try:
            return LLMResponse(text=raw["response"], raw=raw)
        except KeyError as exc:
            raise LLMError(f"unexpected Ollama response shape: {raw}") from exc


class LLMRouter(LLMClient):
    """Tries primary first; falls back on unavailable / rate-limit / any error."""

    def __init__(self, primary: LLMClient | None = None, fallback: LLMClient | None = None):
        if primary is None:
            freellmapi = FreeLLMAPIClient()
            primary = freellmapi if freellmapi.is_available() else GroqClient()
        self.primary = primary
        self.fallback = fallback or OllamaClient()

    def is_available(self) -> bool:
        return self.primary.is_available() or self.fallback.is_available()

    def complete(self, prompt: str, tools: list[dict] | None = None) -> LLMResponse:
        last_error: Exception | None = None
        for client in (self.primary, self.fallback):
            try:
                if not client.is_available():
                    last_error = LLMError(f"{type(client).__name__} unavailable")
                    continue
                response = client.complete(prompt, tools)
                response.served_by = type(client).__name__
                return response
            except RateLimitError as exc:
                last_error = exc
                continue
            except LLMError as exc:
                last_error = exc
                continue
        raise LLMError(f"all LLM backends failed; last error: {last_error}")
