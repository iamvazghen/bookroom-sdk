"""Run the shipped examples for real, against the mock provider.

Proves the documentation's code paths actually work rather than merely
compiling: starts mock providers, exports the credentials as the examples
expect, then executes each example as a subprocess.

    python verify_examples.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "examples"
sys.path.insert(0, str(HERE / "tests"))
sys.path.insert(0, str(HERE))
# The package lives under python/, so a checkout run needs that on the path too.
sys.path.insert(0, str(HERE / "python"))

from fixtures import build_epub          # noqa: E402
from mock_providers import MockProviders  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []
PYTHON = Path(sys.executable)


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))


def run(script: Path, args: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    merged = {**os.environ, **env, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([str(PYTHON), str(script), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=merged, timeout=900)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="bookroom-examples-"))
    print(f"workdir: {workdir}")
    try:
        epub = build_epub(workdir / "src" / "attention.epub")

        with MockProviders() as mock:
            env = {
                "GEMINI_API_KEY": "mock-llm-key",
                "TYPESAFE_API_KEY": "mock-jev-key",
                "BOOKROOM_LLM_BASE_URL": mock.llm_base_url,
                "BOOKROOM_JEV_BASE_URL": mock.jev_base_url,
                "BOOKROOM_OUTPUT_DIR": str(workdir / "output"),
                "BOOKROOM_FACADE_TOKEN": "example-token",
            }
            # The engine ships inside the SDK; a fresh install must not need this.
            env.pop("BOOKROOM_APP_ROOT", None)

            print("\n=== quickstart.py ===")
            code, out, err = run(EXAMPLES / "quickstart.py", [str(epub)], env)
            check("quickstart exits cleanly", code == 0, f"exit {code}")
            check("quickstart reports credentials", "llm    : ok" in out, out.strip().splitlines()[0:1])
            check("quickstart prints the plan", "work batches" in out)
            check("quickstart prints artifacts", "study-guide.pdf" in out)
            if code != 0:
                print(err[-1200:])

            guide = workdir / "output" / "attention" / "study-guide.md"
            check("quickstart wrote the study guide", guide.is_file(), str(guide))

            print("\n=== review_and_export.py ===")
            if guide.is_file():
                code, out, err = run(EXAMPLES / "review_and_export.py",
                                     [str(guide), str(epub)], env)
                check("review_and_export exits cleanly", code == 0, f"exit {code}")
                check("review_and_export lists categories", "categories:" in out)
                check("review_and_export reports format problems", "format problems: none" in out)
                check("review_and_export shows pass counts",
                      "categories passed" in out)
                check("review_and_export reports exports",
                      "concepts     :" in out and "claims       :" in out)
                if code != 0:
                    print(err[-1200:])

            print("\n=== __main__ CLI ===")
            help_proc = subprocess.run(
                [str(PYTHON), "-m", "bookroom_sdk", "--help"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, **env, "PYTHONPATH": str(HERE / "python"),
                     "PYTHONIOENCODING": "utf-8"}, timeout=120, cwd=str(HERE))
            check("CLI help works", help_proc.returncode == 0, f"exit {help_proc.returncode}")

            # exercise the real CLI guide path through -m
            proc = subprocess.run(
                [str(PYTHON), "-m", "bookroom_sdk", "guide", str(epub), "--slug", "cli-run"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, **env, "PYTHONPATH": str(HERE / "python"),
                     "PYTHONIOENCODING": "utf-8"}, timeout=900, cwd=str(HERE))
            check("CLI guide exits cleanly", proc.returncode == 0,
                  f"exit {proc.returncode}")
            check("CLI guide emitted a report",
                  (workdir / "output" / "cli-run" / "study-guide.md").is_file())
            if proc.returncode != 0:
                print((proc.stderr or "")[-1200:])

            print("\n=== serve.py (facade startup) ===")
            port = 8791
            serve_env = {**env, "BOOKROOM_PORT": str(port), "BOOKROOM_HOST": "127.0.0.1"}
            proc = subprocess.Popen(
                [str(PYTHON), str(EXAMPLES / "serve.py")],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace",
                env={**os.environ, **serve_env, "PYTHONIOENCODING": "utf-8"})
            import time
            import urllib.request
            ready = False
            deadline = time.time() + 90
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/v1/describe",
                        headers={"Authorization": "Bearer example-token"})
                    with urllib.request.urlopen(req, timeout=5) as response:
                        ready = response.status == 200
                    if ready:
                        break
                except Exception:  # noqa: BLE001 - server not up yet
                    time.sleep(0.5)
            check("serve.py starts and answers with the token", ready)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/describe", timeout=5)
                check("facade rejects a missing token", False, "request succeeded")
            except Exception as exc:  # noqa: BLE001
                check("facade rejects a missing token", "401" in str(exc), type(exc).__name__)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n" + "=" * 62)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All example checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
