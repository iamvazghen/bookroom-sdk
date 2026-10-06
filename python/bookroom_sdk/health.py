"""Provider health and the alternate (legacy) LLM transport for translation."""

from __future__ import annotations

from typing import Any

from . import bootstrap, errors
from .config import Config
from .results import HealthReport, guard


class HealthAPI:
    """Verify credentials and reachability before spending real money."""

    def __init__(self, config: Config):
        self.config = config

    @guard
    def check(self, *, cached: bool = False, ttl_seconds: float = 60.0) -> HealthReport:
        """Send a minimal synthetic request to the LLM and to JEv.

        Never sends book content. Use this to catch an invalid key or a model the
        key cannot reach before starting a paid run.
        """
        health = bootstrap.module("provider_health", self.config)
        raw = health.check_providers_cached(ttl_seconds) if cached else health.check_providers()
        if not isinstance(raw, dict):
            raise errors.ProviderError("Provider health check returned an unusable response")
        return HealthReport(
            ok=bool(raw.get("ok")),
            llm=dict(raw.get("gemini") or {}),
            review=dict(raw.get("jev") or {}),
        )

    @guard
    def check_cached(self, ttl_seconds: float = 60.0) -> HealthReport:
        """Cached variant; coalesces concurrent probes to avoid repeated billing."""
        return self.check(cached=True, ttl_seconds=ttl_seconds)


class TranslateAPI:
    """Translation and chapter classification through the alternate LLM transport.

    This is the application's legacy path: it talks to Ollama or any
    OpenAI-compatible endpoint configured with ``legacy_base_url``. It is separate
    from the Gemini generation path and is only imported on first use, because the
    application module validates its endpoint at import time.
    """

    def __init__(self, config: Config):
        self.config = config

    def _module(self):
        try:
            return bootstrap.module("llm", self.config)
        except errors.BookroomError as exc:
            raise errors.ConfigError(
                f"Could not initialise the alternate LLM transport: {exc} "
                "Check legacy_base_url is a valid HTTP(S) URL."
            ) from None

    @guard
    def translate(self, text: str, target_lang: str) -> str:
        """Translate one text into ``target_lang``."""
        if not text.strip():
            raise errors.ValidationError("text must not be empty")
        if not target_lang.strip():
            raise errors.ValidationError("target_lang must not be empty")
        return str(self._module().translate_text(text, target_lang))

    @guard
    def translate_batch(self, texts: list[str], target_lang: str) -> list[str]:
        """Translate many texts concurrently where the transport allows it."""
        if not texts:
            return []
        return [str(item) for item in self._module().translate_text_batch(list(texts), target_lang)]

    @guard
    def classify_chapters(self, texts: list[str]) -> list[str]:
        """Return only the chapters the model judged relevant to summarization."""
        if not texts:
            return []
        return [str(item) for item in self._module().classify_chapters_batch(list(texts))]

    @guard
    def extract_notes(self, texts: list[str]) -> list[str]:
        """Multi-node chapter notes: summary, lessons, key points, quotes, anecdotes, resources."""
        if not texts:
            return []
        return [str(item) for item in self._module().extract_notes_batch(list(texts))]

    def describe(self) -> dict[str, Any]:
        """Where this transport points, without exposing the key."""
        return {
            "endpoint": self.config.legacy_base_url,
            "model": self.config.legacy_model,
            "concurrency": self.config.legacy_concurrency,
        }
