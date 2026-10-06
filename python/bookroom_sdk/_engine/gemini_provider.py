"""Minimal Gemini REST adapter with per-job usage accounting and a hard stop."""

import os
import threading
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))
MODEL = os.getenv("GEMINI_MODEL", os.getenv("LLM_MODEL", "gemini-3.8-flash"))
API_KEY = os.getenv("GEMINI_API_KEY", "")
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low").lower()
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_LOCAL = threading.local()
_KEYS = ("calls", "prompt_tokens", "candidate_tokens", "total_tokens")


class GeminiAPIError(RuntimeError):
    """Safe provider error that never includes request URLs or credentials."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _current() -> dict:
    if not hasattr(_LOCAL, "usage"):
        _LOCAL.usage = dict.fromkeys(_KEYS, 0)
        _LOCAL.batch_total_tokens = 0
    return _LOCAL.usage


def usage_snapshot() -> dict:
    return dict(_current())


def create_usage_report() -> dict:
    return {"schema_version": "1.0", "provider": "Google Gemini API", "model": MODEL, **usage_snapshot()}


def reset_usage() -> None:
    _LOCAL.usage = dict.fromkeys(_KEYS, 0)
    _LOCAL.batch_total_tokens = 0
    _LOCAL.retry_notifier = None


def set_retry_notifier(callback) -> None:
    _LOCAL.retry_notifier = callback


def begin_batch() -> None:
    """Start a new planned work batch without discarding whole-job usage totals."""
    _current()
    _LOCAL.batch_total_tokens = 0


def _token_count(metadata: dict, key: str) -> int:
    try:
        return max(0, int(metadata.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _retry_after_seconds(response) -> float | None:
    header = response.headers.get("Retry-After", "")
    try:
        if header:
            return max(0.0, float(header))
    except (TypeError, ValueError):
        pass
    try:
        body = response.json()
        details = body.get("error", {}).get("details", []) if isinstance(body, dict) else []
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict):
                continue
            delay = detail.get("retryDelay", "")
            if isinstance(delay, str) and delay.endswith("s"):
                return max(0.0, float(delay[:-1]))
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _post_generation(prompt: str, *, temperature: float, max_output_tokens: int):
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "thinkingConfig": {"thinkingLevel": THINKING_LEVEL},
        },
    }
    retries = max(0, min(int(os.getenv("GEMINI_MAX_RETRIES", "5")), 5))
    response = None
    for attempt in range(retries + 1):
        try:
            # Keep the API key out of the URL: request URLs are more likely to be
            # captured by reverse-proxy/access logs than authorization headers.
            response = httpx.post(
                f"{BASE_URL}/models/{MODEL}:generateContent",
                headers={"x-goog-api-key": API_KEY},
                json=payload,
                timeout=120,
            )
        except httpx.RequestError as exc:
            raise GeminiAPIError(f"Gemini could not be reached ({type(exc).__name__}). Check the network and retry.") from None
        if response.status_code == 429 and attempt < retries:
            retry_after = _retry_after_seconds(response)
            if retry_after is not None and retry_after <= 120:
                notifier = getattr(_LOCAL, "retry_notifier", None)
                if notifier:
                    notifier(retry_after, attempt + 1)
                if retry_after:
                    time.sleep(retry_after)
                continue
        if response.status_code not in {500, 502, 503, 504} or attempt >= retries:
            return response
        retry_after = response.headers.get("Retry-After", "")
        try:
            delay = max(0.0, min(float(retry_after), 8.0))
        except (TypeError, ValueError):
            delay = min(0.5 * (2 ** attempt), 4.0)
        if delay:
            time.sleep(delay)
    return response


def generate(prompt: str, *, temperature: float = 0.3, max_output_tokens: int = 8192) -> str:
    if not API_KEY:
        raise ValueError("Set GEMINI_API_KEY in the local environment")
    usage_state = _current()
    max_total = int(os.getenv("MAX_ACTUAL_GEMINI_TOKENS", "2000000"))
    if _LOCAL.batch_total_tokens >= max_total:
        raise RuntimeError(f"Actual Gemini batch token budget reached ({max_total:,}); stopped before another API call.")
    response = _post_generation(prompt, temperature=temperature, max_output_tokens=max_output_tokens)
    status = response.status_code
    if isinstance(status, int) and status >= 400:
        guidance = {
            400: "Gemini rejected the request. Check the configured model and request settings.",
            401: "Gemini rejected the API key. Replace it with a valid key from the intended Google AI Studio project.",
            403: "Gemini denied access to this project or model. In Google AI Studio, verify the key is active and allowed to use the Gemini API, check project/API restrictions, and replace it if it was exposed or reported as leaked.",
            404: "Gemini could not find the configured model or endpoint. Check model availability for this key's project.",
            429: "Gemini quota or rate limit reached. Check the project's limits and retry later.",
            503: "Gemini is temporarily unavailable after safe retries. Retry the job; saved checkpoints will be reused.",
        }
        if status == 429:
            retry_after = _retry_after_seconds(response)
            if retry_after is not None:
                message = f"Gemini quota or rate limit reached. Wait at least {int(retry_after)} seconds before retrying, or check the project's limits."
            else:
                message = guidance[429]
        elif status in {500, 502, 504}:
            message = f"Gemini is temporarily unavailable (HTTP {status}) after safe retries. Retry the job; saved checkpoints will be reused."
        else:
            message = guidance.get(status, f"Gemini request failed (HTTP {status}). Check the provider configuration and retry.")
        raise GeminiAPIError(message, retry_after_seconds=retry_after if status == 429 else None) from None
    try:
        data = response.json()
    except (ValueError, TypeError) as exc:
        raise ValueError("Gemini returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Gemini returned an invalid response object")
    metadata = data.get("usageMetadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    usage_state["calls"] += 1
    usage_state["prompt_tokens"] += _token_count(metadata, "promptTokenCount")
    usage_state["candidate_tokens"] += _token_count(metadata, "candidatesTokenCount")
    usage_state["total_tokens"] += _token_count(metadata, "totalTokenCount")
    _LOCAL.batch_total_tokens += _token_count(metadata, "totalTokenCount")
    candidates = data.get("candidates") or []
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ValueError("Gemini returned no usable candidates")
    candidate = candidates[0]
    if candidate.get("finishReason") == "MAX_TOKENS":
        raise ValueError("Gemini output was truncated at the configured token limit")
    content = candidate.get("content") or {}
    parts = content.get("parts", []) if isinstance(content, dict) else []
    if not isinstance(parts, list):
        parts = []
    result = "".join(part.get("text", "") for part in parts if isinstance(part, dict) and isinstance(part.get("text", ""), str))
    if not result.strip():
        raise ValueError("Gemini returned an empty response")
    if _LOCAL.batch_total_tokens > max_total:
        raise RuntimeError(f"Actual Gemini batch token budget exceeded ({_LOCAL.batch_total_tokens:,}/{max_total:,}); no further calls will be made.")
    return result.strip()
