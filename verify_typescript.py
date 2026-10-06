"""Start the real facade and drive it with the built TypeScript SDK.

This is the cross-language proof: the Python engine (with a mock LLM/JEv
provider behind it, so nothing is paid for) serving a genuine book, exercised
entirely through the compiled TypeScript client over HTTP.

    python verify_typescript.py [book.epub|book.pdf]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "python"))
sys.path.insert(0, str(HERE / "tools"))

from bookroom_sdk import Bookroom              # noqa: E402
from bookroom_sdk.server import create_server  # noqa: E402

DEFAULT_BOOK = r"C:\Users\iamva\Downloads\_OceanofPDF.com_God_Sees_the_Truth_but_Waits_-_Leo_Tolstoy.pdf"


def find_dist_entry() -> Path | None:
    for candidate in ("dist/esm/index.js", "dist/cjs/index.js", "dist/index.js"):
        path = HERE / candidate
        if path.is_file():
            return path
    return None


def main() -> int:
    dist = find_dist_entry()
    if dist is None:
        print("TypeScript SDK is not built. Run, in this directory:")
        print("  npm install && npm run build")
        return 2
    client = HERE / "examples" / "cross_language_client.mjs"
    if not client.is_file():
        print(f"missing client script: {client}")
        return 2
    node = shutil.which("node")
    if node is None:
        print("node is not on PATH")
        return 2

    book = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path(DEFAULT_BOOK)
    if not book.is_file():
        print(f"no such book: {book}")
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="bookroom-cross-"))
    token = "cross-language-token"
    print(f"typescript entry: {dist}")
    print(f"book            : {book}")
    print(f"workdir         : {workdir}")

    try:
        with _MockProviders() as mock:
            room = Bookroom(llm_api_key="mock-llm-key", jev_api_key="mock-jev-key",
                            llm_base_url=mock.llm_base_url, jev_base_url=mock.jev_base_url,
                            app_root=r"D:\summarizer\src", output_dir=workdir / "output")
            server = create_server(room, host="127.0.0.1", port=0, token=token)
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print(f"facade          : {base}\n")
            try:
                proc = subprocess.run(
                    [node, str(client), dist.as_uri(), base, token, str(book)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    env={**os.environ, "NODE_OPTIONS": "", "PYTHONIOENCODING": "utf-8"},
                    timeout=2400)
                print((proc.stdout or "") + (proc.stderr or ""))
                return proc.returncode
            finally:
                server.shutdown()
                server.server_close()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    from mock_providers import MockProviders as _MockProviders  # noqa: E402
    raise SystemExit(main())
