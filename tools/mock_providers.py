"""A local stand-in for the LLM and JEv providers.

Speaks the two wire formats the engine actually uses:

* ``POST {llm_base_url}/models/{model}:generateContent`` with an ``x-goog-api-key``
  header, returning a Gemini ``candidates`` envelope.
* ``POST {jev_base_url}/systemone`` with a Bearer token, returning typed
  ``score`` and ``choice`` answers.

This exists so the pipeline can be exercised end to end when the real provider
is unavailable or out of quota. It is a test fixture: it never contacts a paid
service and it does not write to disk.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _gemini_envelope(text: str) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                        "finishReason": "STOP"}],
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
    return {"answers": scored, "model": "jev-mock", "usage": {"credits": 1, "requests": 1}}


_BULLETS = (
    "- The protagonist's first decision is made in haste and carries the story\n"
    "  - A later decision contradicts it directly\n"
    "  - The contradiction is never fully explained\n"
    "- A second thread introduces an external judgment that mirrors the internal one\n"
    "- The closing scene withdraws rather than resolves\n"
)


def _draft_for(prompt: str) -> str:
    """Return section-shaped Markdown so the downstream regex extraction works."""
    lowered = prompt.lower()
    if "revision" in lowered or "revise only" in lowered:
        return ("Revised: the central claim is stated more directly, the weakest "
                "claim is qualified, and the unsupported detail is removed.")
    if "concept map" in lowered:
        return "### Core Concept\n" + _BULLETS
    if "glossary" in lowered:
        return ("- **Haste** - the tempo of a decision made before its consequences are known.\n"
                "- **Accountability** - the burden of answering for an act already done.\n")
    if "timeline" in lowered:
        return "1. An offence is committed.\n2. A warning is given and refused.\n3. A death follows.\n4. The second thread is judged.\n"
    if "reader questions" in lowered or "faq" in lowered:
        return ("**What drives the first half?** A single impulsive act.\n\n"
                "**Why does the ending withhold judgment?** Because the second thread "
                "is the only verdict the text offers.\n")
    if "one paragraph" in lowered or "hook" in lowered:
        return ("A short moral tale in which a poor man commits a petty theft, is "
                "tempted twice more while ignorant of a murder, and is arrested only "
                "after the dead man's family have already forgiven him. Told through "
                "two parallel narratives, it argues that guilt is less a matter of "
                "knowledge than of what one has already chosen to do.")
    if "chapter" in lowered or "section" in lowered or "source locator" in lowered:
        return ("This section develops the tale in a plain declarative register. It "
                "first establishes the protagonist's poverty, then the chain of "
                "small thefts, and finally the arrest. The narrator supplies no "
                "verdict and no consolation; the moral is left to the reader. "
                "Where the source withholds an explanation, this summary withholds it too.")
    return ("The text makes three connected moves. It first establishes the problem "
            "in concrete terms, then assembles the evidence that bears on it, and "
            "finally proposes a response proportionate to the evidence. Where the "
            "evidence is thin the author says so explicitly rather than overstating "
            "the case, and the practical implication is that the method can be "
            "adopted incrementally.")


class _Handler(BaseHTTPRequestHandler):
    server_version = "MockProvider/1.0"
    calls: list[dict[str, Any]] = []

    def log_message(self, *args: Any) -> None:
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

        if self.path.rstrip("/").endswith("/api/chat"):
            prompt = ""
            for message in payload.get("messages", []) or []:
                prompt = str(message.get("content") or "")
            self.__class__.calls.append({"provider": "ollama", "path": self.path, "auth": True})
            self._send({"model": payload.get("model", "mock"),
                        "message": {"role": "assistant", "content": _draft_for(prompt)},
                        "done": True})
            return

        if self.path.rstrip("/").endswith("/chat/completions"):
            prompt = ""
            for message in payload.get("messages", []) or []:
                prompt = str(message.get("content") or "")
            self.__class__.calls.append({"provider": "openai", "path": self.path,
                                         "auth": bool(self.headers.get("Authorization"))})
            self._send({"id": "mock", "model": payload.get("model", "mock"),
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant",
                                                 "content": _draft_for(prompt)}}]})
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
