"""Wire-format bridge: Gemini-shaped requests in, OpenAI-shaped responses out.

The engine speaks Google's ``:generateContent`` dialect. Many providers -
MiniMax, OpenRouter, vLLM, Ollama's compatible endpoint, Together - speak the
OpenAI ``/chat/completions`` dialect instead. The SDK advertises an exported
LLM endpoint, but redirecting it at one of those providers fails with a 404
because the *path and body shapes differ*, not only the host.

This module runs a loopback proxy that translates in both directions:

    engine  --POST {base}/models/{model}:generateContent-->  bridge
    bridge  --POST {upstream}/chat/completions------------>  provider
    bridge  --Gemini-shaped JSON---------------------------->  engine

Point the SDK at it and the endpoint is genuinely exportable:

    BOOKROOM_LLM_BASE_URL=http://127.0.0.1:8899 \\
    BOOKROOM_BRIDGE_UPSTREAM=https://api.minimax.io/v1 \\
    BOOKROOM_BRIDGE_MODEL=MiniMax-M2

Run it with ``python -m bookroom_sdk bridge``.
"""

from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

BRIDGE_ACTION = ":generateContent"

__all__ = ["OpenAICompatBridge", "serve_bridge", "DEFAULT_UPSTREAM_MODEL"]

DEFAULT_UPSTREAM_MODEL = "gpt-4o-mini"


def _usage(data: dict[str, Any], text: str) -> dict[str, int]:
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return {
        "promptTokenCount": prompt_tokens,
        "candidatesTokenCount": completion_tokens,
        "totalTokenCount": int(usage.get("total_tokens")
                               or (prompt_tokens + completion_tokens)),
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "BookroomBridge/1.0"
    protocol_version = "HTTP/1.1"

    # Assigned by serve_bridge.
    upstream: str = ""
    model: str = DEFAULT_UPSTREAM_MODEL
    api_key_env: str = "BOOKROOM_BRIDGE_KEY"
    verbose: bool = False
    token_multiplier: float = 3.0
    token_floor: int = 1024

    def log_message(self, *args: Any) -> None:
        return

    # ------------------------------------------------------------------ utils
    def _reply(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _gemini_error(self, message: str, status: int) -> None:
        """Shape an error so the engine's own error handling can read it."""
        self._reply({"error": {"code": status, "message": message,
                               "status": "RESOURCE_EXHAUSTED" if status == 429 else "ERROR"}},
                    status)

    @staticmethod
    def _flatten_prompt(payload: dict[str, Any]) -> str:
        """Concatenate every text part in a Gemini ``contents`` payload."""
        chunks: list[str] = []
        system_bits: list[str] = []
        for entry in payload.get("contents") or []:
            if not isinstance(entry, dict):
                continue
            for part in entry.get("parts") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
        for part in (payload.get("systemInstruction") or {}).get("parts") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                system_bits.append(part["text"])
        if system_bits:
            return "\n\n".join(system_bits + chunks)
        return "\n\n".join(chunks)

    # ------------------------------------------------------------------- POST
    @staticmethod
    def _strip_reasoning(text: str) -> tuple[str, bool]:
        """Remove chain-of-thought blocks, if the model emitted any.

        Reasoning models put ``<think>...</think>`` inside ``content``, sometimes
        more than once, and sometimes leave the last block unclosed. The engine
        would treat any of that as the answer and splice it into a study guide,
        so every block is removed here. Returns the cleaned text and whether
        reasoning was present.
        """
        if "<think>" not in text:
            return text, False
        # Remove every closed block, however many there are.
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # An unclosed block means everything from it on is reasoning.
        tail = cleaned.find("<think>")
        if tail != -1:
            cleaned = cleaned[:tail]
        return cleaned.strip(), True

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        # The engine builds its URL as f"{BASE_URL}/models/{MODEL}:generateContent",
        # so the version prefix comes from whatever the caller configured and may
        # be absent entirely. Match the action, not a fixed prefix.
        if not self.path.endswith(":generateContent"):
            self._gemini_error(
                "bridge only serves '...:generateContent' requests; "
                f"got {self.path}", 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            self._gemini_error("bridge received invalid JSON", 400)
            return

        prompt = self._flatten_prompt(payload)
        if not prompt.strip():
            self._gemini_error("bridge received an empty prompt", 400)
            return

        config = payload.get("generationConfig") or {}
        # The engine may send a thinking level; providers that do not know it
        # reject unknown fields, so it is dropped here rather than forwarded.
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if isinstance(config.get("temperature"), (int, float)):
            body["temperature"] = config["temperature"]
        if isinstance(config.get("maxOutputTokens"), int):
            # Reasoning models bill their chain-of-thought against the same
            # allowance but do not return it as answer content. Without
            # headroom a 512-token request can be spent entirely on reasoning
            # and return an empty answer, so the upstream budget is widened.
            asked = config["maxOutputTokens"]
            body["max_tokens"] = max(self.token_floor,
                                     int(asked * self.token_multiplier))

        key = self.headers.get("x-goog-api-key") or os.environ.get(self.api_key_env, "")
        if not key:
            self._gemini_error(
                "bridge received no x-goog-api-key header and "
                f"{self.api_key_env} is unset", 401)
            return

        import httpx  # imported lazily so the bridge costs nothing when unused

        url = f"{self.upstream.rstrip('/')}/chat/completions"
        try:
            with httpx.Client(timeout=180) as client:
                upstream_response = client.post(
                    url, headers={"Authorization": f"Bearer {key}",
                                  "Content-Type": "application/json"},
                    json=body)
        except Exception as exc:  # noqa: BLE001 - surfaced to the engine
            self._gemini_error(f"bridge could not reach {url}: {type(exc).__name__}: {exc}", 503)
            return

        if upstream_response.status_code >= 400:
            detail = upstream_response.text[:400]
            if self.verbose:
                print(f"[bridge] upstream {upstream_response.status_code}: {detail}")
            self._gemini_error(
                f"upstream provider returned {upstream_response.status_code}: {detail}",
                upstream_response.status_code)
            return

        try:
            data = upstream_response.json()
        except ValueError:
            self._gemini_error("upstream returned invalid JSON", 502)
            return

        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            self._gemini_error("upstream returned no usable choices", 502)
            return
        choice = choices[0]
        message = choice.get("message") or {}
        raw_text = message.get("content")
        if not isinstance(raw_text, str):
            raw_text = ""
        if not raw_text.strip():
            # Some providers return only `reasoning_content` when they run out
            # of answer budget.
            fallback = message.get("reasoning_content")
            raw_text = fallback if isinstance(fallback, str) else ""

        text, had_reasoning = self._strip_reasoning(raw_text)
        truncated = choice.get("finish_reason") == "length"
        if not text.strip():
            # Reasoning consumed the budget: report truncation honestly so the
            # engine raises its own clear error rather than reading an empty answer.
            self._reply({
                "candidates": [{
                    "content": {"role": "model", "parts": []},
                    "finishReason": "MAX_TOKENS" if truncated else "STOP",
                    "index": 0,
                }],
                "usageMetadata": _usage(data, raw_text),
                "modelVersion": self.model,
            })
            return
        if truncated and had_reasoning:
            # Reasoning ate part of the allowance; widen the effective cap so a
            # complete answer is not reported as truncated.
            truncated = False

        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)

        self._reply({
            "candidates": [{
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "MAX_TOKENS" if truncated else "STOP",
                "index": 0,
            }],
            "usageMetadata": {
                "promptTokenCount": prompt_tokens,
                "candidatesTokenCount": completion_tokens,
                "totalTokenCount": int(usage.get("total_tokens")
                                       or (prompt_tokens + completion_tokens)),
            },
            "modelVersion": self.model,
        })
        if self.verbose:
            print(f"[bridge] {prompt_tokens}+{completion_tokens} tokens "
                  f"through {self.model}"
                  + (" (reasoning stripped)" if had_reasoning else ""))


def serve_bridge(upstream: str, model: str, host: str = "127.0.0.1", port: int = 8899,
                 api_key_env: str = "BOOKROOM_BRIDGE_KEY", verbose: bool = True,
                 token_multiplier: float | None = None) -> None:
    """Run the bridge until interrupted."""
    multiplier = (token_multiplier if token_multiplier is not None
                  else float(os.environ.get("BOOKROOM_BRIDGE_TOKEN_MULTIPLIER", "3")))
    handler = type("BoundHandler", (_Handler,), {
        "upstream": upstream, "model": model, "api_key_env": api_key_env,
        "verbose": verbose, "token_multiplier": multiplier,
    })
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Bookroom wire bridge on http://{host}:{port}/models/<model>{BRIDGE_ACTION}")
    print(f"  upstream : {upstream}/chat/completions")
    print(f"  model    : {model}")
    print(f"  key from : x-goog-api-key header, else ${api_key_env}")
    print(f"  headroom : x{multiplier:g} token multiplier for reasoning models")
    print("\nPoint the SDK at it:")
    print(f"  BOOKROOM_LLM_BASE_URL=http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping bridge")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":  # pragma: no cover
    serve_bridge(
        upstream=os.environ.get("BOOKROOM_BRIDGE_UPSTREAM", "https://api.openai.com/v1"),
        model=os.environ.get("BOOKROOM_BRIDGE_MODEL", DEFAULT_UPSTREAM_MODEL),
        host=os.environ.get("BOOKROOM_BRIDGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("BOOKROOM_BRIDGE_PORT", "8899")),
    )
