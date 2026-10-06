"""Serve the engine over HTTP for non-Python clients.

    python examples/serve.py

Then, from a TypeScript or any other codebase:

    const room = new Bookroom({ baseUrl: "http://127.0.0.1:8787",
                                token: process.env.BOOKROOM_FACADE_TOKEN });
    const report = await room.summarize.studyGuide("book.epub");

The LLM and JEv keys stay in this process. Clients only ever see the facade
token, so you can host the engine somewhere shared without leaking either key.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from bookroom_sdk import Bookroom  # noqa: E402
from bookroom_sdk.server import serve  # noqa: E402


def main() -> int:
    # Credentials come from the environment in a real deployment.
    llm_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("BOOKROOM_LLM_API_KEY")
    jev_api_key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("BOOKROOM_JEV_API_KEY")
    if not llm_api_key:
        print("set GEMINI_API_KEY (or BOOKROOM_LLM_API_KEY) before serving")
        return 2

    token = os.environ.get("BOOKROOM_FACADE_TOKEN") or secrets.token_urlsafe(24)
    host = os.environ.get("BOOKROOM_HOST", "127.0.0.1")
    port = int(os.environ.get("BOOKROOM_PORT", "8787"))

    room = Bookroom(llm_api_key=llm_api_key, jev_api_key=jev_api_key)

    if not os.environ.get("BOOKROOM_FACADE_TOKEN"):
        print(f"generated facade token (clients need it):\n  {token}\n")
    if host not in {"127.0.0.1", "localhost"}:
        print(f"WARNING: binding to {host}. Put a TLS terminator in front of this "
              "before exposing it to a network you do not control.\n")

    serve(room, host=host, port=port, token=token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
