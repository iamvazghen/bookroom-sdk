"""A local stand-in for the LLM and JEv providers.

Speaks the two wire formats the wrapped application actually uses:

* ``POST {llm_base_url}/models/{model}:generateContent`` with an ``x-goog-api-key``
  header, returning a Gemini ``candidates`` envelope.
* ``POST {jev_base_url}/systemone`` with a Bearer token, returning typed
  ``score`` and ``choice`` answers.

It lets the whole pipeline - extraction, chapter notes, the 16-section digest,
the JEv quality gate and every export - run for real without a paid key.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _gemini_envelope(text: str) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {
            "promptTokenCount": max(1, len(text) // 4),
            "candidatesTokenCount": max(1, len(text) // 4),
            "totalTokenCount": max(2, len(text) // 2),
        },
        "modelVersion": "mock-1",
    }


def _jev_envelope(score: int = 4, confidence: float = 0.92) -> dict[str, Any]:
    scored = {
        "faithfulness": {"score": score, "confidence": confidence},
        "coverage": {"score": score, "confidence": confidence},
        "clarity": {"score": score, "confidence": confidence},
        "structure": {"score": score, "confidence": confidence},
        "revision_focus": {"choice": "none"},
    }
    return {
        "answers": scored,
        "model": "jev-mock",
        "usage": {"credits": 1, "requests": 1},
    }


_BULLETS = (
    "- Core claim rests on a single controlling assumption\n"
    "  - Sub-claim A depends on that assumption holding\n"
    "  - Sub-claim B is weaker but still material\n"
    "- Evidence is unevenly distributed across the text\n"
    "- The strongest material appears in the middle third\n"
)


def _draft_for(prompt: str) -> str:
    """Return section-shaped Markdown so the downstream regex extraction works."""
    lowered = prompt.lower()
    if "revision" in lowered or "revise only" in lowered:
        return "Revised: the central argument is stated more directly and the weakest claim is qualified."
    if "concept map" in lowered:
        return "### Core Concept\n" + _BULLETS
    if "glossary" in lowered:
        return "- **Grounding** - the commitment to justify a claim from evidence rather than assertion.\n" \
               "- **Salience** - how much a given idea matters to the book's thesis.\n"
    if "timeline" in lowered:
        return "1. The problem is framed.\n2. Evidence is assembled.\n3. A resolution is proposed.\n4. Limits are acknowledged.\n"
    if "reader questions" in lowered or "faq" in lowered:
        return "**What is the central claim?** It is that attention is the scarce resource.\n\n" \
               "**Who is this for?** Readers who want a practical framework.\n"
    if "one paragraph" in lowered or "hook" in lowered:
        return ("This book argues that sustained attention, more than raw time or talent, separates "
                "effective work from merely busy work. It builds the case from research on practice, "
                "then supplies a concrete operating method the reader can adopt immediately.")
    if "chapter" in lowered or "section" in lowered or "source locator" in lowered:
        return ("This section develops the book's central claim with supporting evidence. The argument "
                "moves from a stated problem to the evidence gathered against it, then to the response "
                "the author proposes. Qualifications introduced earlier are preserved here rather than "
                "dropped, because the conclusion depends on them.")
    return ("The text makes three connected moves. It first establishes the problem in concrete terms, "
            "then assembles the evidence that bears on it, and finally proposes a response proportionate "
            "to the evidence. Where the evidence is thin, the author says so explicitly rather than "
            "overstating the case. The practical implication is that the method can be adopted "
            "incrementally, and that the reader should expect to revise it as they gain experience.")


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockProvider/1.0"
    calls: list[dict[str, Any]] = []

    def log_message(self, *args: Any) -> None:  # silence request logging
        return

    def _send(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            payload = {}

        if ":generateContent" in self.path:
            prompt = ""
            try:
                prompt = payload["contents"][0]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError):
                pass
            self.__class__.calls.append({"provider": "llm", "path": self.path,
                                         "auth": bool(self.headers.get("x-goog-api-key"))})
            self._send(_gemini_envelope(_draft_for(prompt)))
            return

        # Ollama's native chat shape (the default alternate transport).
        if self.path.rstrip("/").endswith("/api/chat"):
            prompt = ""
            for message in payload.get("messages", []) or []:
                prompt = str(message.get("content") or "")
            self.__class__.calls.append({"provider": "ollama", "path": self.path, "auth": True})
            self._send({"model": payload.get("model", "mock"),
                        "message": {"role": "assistant", "content": _draft_for(prompt)},
                        "done": True})
            return

        # OpenAI / OpenRouter-compatible chat completions.
        if self.path.rstrip("/").endswith("/chat/completions"):
            prompt = ""
            for message in payload.get("messages", []) or []:
                prompt = str(message.get("content") or "")
            self.__class__.calls.append({"provider": "openai", "path": self.path,
                                         "auth": bool(self.headers.get("Authorization"))})
            self._send({"id": "mock", "model": payload.get("model", "mock"),
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": _draft_for(prompt)}}]})
            return

        if self.path.rstrip("/").endswith("/systemone"):
            self.__class__.calls.append({"provider": "jev", "path": self.path,
                                         "auth": (self.headers.get("Authorization") or "").startswith("Bearer ")})
            self._send(_jev_envelope())
            return

        self._send({"error": {"message": f"unhandled path {self.path}"}}, 404)


class MockProviders:
    """Context manager that runs both mock providers on one loopback port."""

    def __init__(self, host: str = "127.0.0.1"):
        self._server = ThreadingHTTPServer((host, 0), _Handler)
        self._thread: threading.Thread | None = None
        _Handler.calls = []

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def llm_base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1beta"

    @property
    def jev_base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def calls(self) -> list[dict[str, Any]]:
        return list(_Handler.calls)

    def __enter__(self) -> "MockProviders":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)


if __name__ == "__main__":
    with MockProviders() as mock:
        print("llm:", mock.llm_base_url)
        print("jev:", mock.jev_base_url)
