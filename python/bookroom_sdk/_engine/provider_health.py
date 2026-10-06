"""On-demand, low-cost credential checks that never send book contents."""

from __future__ import annotations

import os
from copy import deepcopy
from threading import Lock
from time import monotonic

import httpx

_CHECK_LOCK = Lock()
_CHECK_CACHE: dict | None = None
_CHECKED_AT = 0.0


def _jev_failure(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return "Jev denied this credential or model access. Check the TypeSafe project key and model permissions."
        if status == 404:
            return "Jev could not find the configured endpoint or model. Check the TypeSafe API base URL and model."
        if status == 429:
            return "Jev quota or rate limit reached. Check the project's limits and retry later."
        return f"Jev check failed (HTTP {status}). Check the provider configuration and retry."
    if isinstance(exc, httpx.RequestError):
        return "Jev could not be reached. Check the network and configured API endpoint."
    return "Jev returned an unusable response. Check the configured model and retry."


def check_providers() -> dict:
    """Check configured providers with synthetic text; never includes credentials in output."""
    worker_url = os.getenv("PROVIDER_CHECK_URL", "").strip()
    if worker_url:
        token = os.getenv("WORKER_CONTROL_TOKEN", "")
        if len(token) < 32:
            return _worker_unavailable("Private provider-check authentication is not configured.")
        try:
            response = httpx.post(
                worker_url,
                headers={"X-Worker-Control-Token": token},
                timeout=180,
                follow_redirects=False,
            )
            payload = response.json()
            if _valid_provider_result(payload):
                return payload
            return _worker_unavailable("Private worker returned an invalid provider-check response.")
        except (httpx.RequestError, ValueError, TypeError):
            return _worker_unavailable("Private provider-check worker is unavailable. Check the worker service and retry.")

    from gemini_provider import API_KEY as GEMINI_KEY, MODEL, GeminiAPIError, generate
    from book_pipeline import JEV_API_KEY, JEV_ENABLED, JEV_MODEL, _jev_evaluate

    enabled = os.getenv("GEMINI_ENABLED", "true" if GEMINI_KEY else "false").lower() == "true"
    result = {
        "gemini": {"status": "not_configured", "message": "Gemini is not enabled or its server-side key is missing."},
        "jev": {"status": "not_configured", "message": "Jev is disabled or its server-side key is missing."},
    }
    if enabled and GEMINI_KEY:
        try:
            reply = generate("Provider connection check. Reply with exactly: OK", temperature=0, max_output_tokens=8)
            if not reply.strip():
                raise ValueError("Empty response")
            result["gemini"] = {"status": "ok", "model": MODEL, "message": "Gemini accepted a minimal test request."}
        except GeminiAPIError as exc:
            result["gemini"] = {"status": "failed", "message": str(exc)}
        except Exception as exc:
            result["gemini"] = {"status": "failed", "message": f"Gemini check failed ({type(exc).__name__}). Check provider configuration and retry."}

    if JEV_ENABLED and JEV_API_KEY:
        try:
            evaluation = _jev_evaluate(
                "Provider connection check",
                "The sample source states that water freezes at zero degrees Celsius.",
                "The source says water freezes at zero degrees Celsius.",
            )
            scores = evaluation.get("scores", {})
            if not evaluation.get("enabled") or not isinstance(scores, dict) or not scores or any(not isinstance(score, (int, float)) for score in scores.values()):
                raise ValueError("Jev returned no usable scores")
            result["jev"] = {"status": "ok", "model": evaluation.get("model", JEV_MODEL), "message": "Jev accepted a minimal evaluation request."}
        except httpx.HTTPStatusError as exc:
            result["jev"] = {"status": "failed", "message": _jev_failure(exc)}
        except httpx.RequestError as exc:
            result["jev"] = {"status": "failed", "message": _jev_failure(exc)}
        except Exception as exc:
            result["jev"] = {"status": "failed", "message": f"Jev check failed ({type(exc).__name__}). Check provider configuration and retry."}

    result["ok"] = all(item["status"] == "ok" for item in (result["gemini"], result["jev"]))
    return result


def _valid_provider_result(payload) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        return False
    for provider in ("gemini", "jev"):
        entry = payload.get(provider)
        if not isinstance(entry, dict) or entry.get("status") not in {"ok", "failed", "not_configured"}:
            return False
        if not isinstance(entry.get("message"), str):
            return False
    return True


def _worker_unavailable(message: str) -> dict:
    failure = {"status": "failed", "message": message}
    return {"ok": False, "gemini": dict(failure), "jev": dict(failure)}


def check_providers_cached(ttl_seconds: float = 60) -> dict:
    """Coalesce concurrent checks and cache the result to avoid repeated billable probes."""
    global _CHECK_CACHE, _CHECKED_AT
    with _CHECK_LOCK:
        current = monotonic()
        if _CHECK_CACHE is not None and current - _CHECKED_AT < ttl_seconds:
            result = deepcopy(_CHECK_CACHE)
            result["cached"] = True
            return result
        _CHECK_CACHE = check_providers()
        _CHECKED_AT = monotonic()
        result = deepcopy(_CHECK_CACHE)
        result["cached"] = False
        return result
