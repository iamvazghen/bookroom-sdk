"""Run the real book through BOTH code paths and compare them, offline.

Everything in this comparison is real: the real PDF, real extraction, real
report assembly, real format validation, real PDF export, real concept map,
real claim audit, real manifest. **Only the LLM and JEv text generation is
mocked**, so the run needs no provider quota.

This exists to answer one question precisely: does the SDK wrapper produce the
same result as the engine's own code path? It is a wrapper-equivalence check,
not a check of summary quality.

    python verify_equivalence.py <book.pdf|book.epub>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tools"))

from mock_providers import MockProviders  # noqa: E402

PYTHON = sys.executable
argv_runs = sys.argv[2] if len(sys.argv) > 2 else None


def _run(script: str, args: list[str], env: dict[str, str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run([PYTHON, str(HERE / script), *args], cwd=str(cwd),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env={**os.environ, **env}, timeout=2400)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    source = Path(sys.argv[1]).expanduser()
    if not source.is_file():
        print(f"no such file: {source}")
        return 2

    # A second runs root gives a clean-cache run, so both sides make the same
    # number of provider calls instead of one side resuming from a checkpoint.
    runs_root = Path(argv_runs).expanduser() if len(sys.argv) > 2 else HERE / "runs"
    runs = runs_root
    sdk_dir = runs / "sdk"
    base_dir = runs / "baseline"
    for directory in (sdk_dir, base_dir):
        directory.mkdir(parents=True, exist_ok=True)

    with MockProviders() as mock:
        # No engine path is passed: both runs must work against the copy bundled
        # inside the SDK, which is what a fresh install gets.
        env = {
            "BOOKROOM_LLM_BASE_URL": mock.llm_base_url,
            "BOOKROOM_JEV_BASE_URL": mock.jev_base_url,
            "PYTHONIOENCODING": "utf-8",
        }
        env.pop("BOOKROOM_APP_ROOT", None)
        print(f"mock LLM    : {mock.llm_base_url}")
        print(f"mock review : {mock.jev_base_url}")
        print(f"real source : {source}\n")

        print("=" * 70)
        print("RUN 1/2  through the SDK")
        print("=" * 70)
        code, out = _run("run_summary.py",
                         [str(source), "--out", str(sdk_dir), "--slug", "book"],
                         env, HERE)
        print(out[-3000:])
        if code != 0:
            print(f"\nSDK run failed ({code})")
            return 1

        print("\n" + "=" * 70)
        print("RUN 2/2  through the engine's own code path (no SDK)")
        print("=" * 70)
        code, out = _run("run_baseline.py",
                         [str(source), "--out", str(base_dir), "--slug", "book"],
                         env, HERE)
        print(out[-3000:])
        if code != 0:
            print(f"\nbaseline run failed ({code})")
            return 1

    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    code, out = _run("compare_runs.py", [str(sdk_dir), str(base_dir)],
                     {"PYTHONIOENCODING": "utf-8"}, HERE)
    print(out)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
