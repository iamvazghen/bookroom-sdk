"""Retry the full SDK cycle until the provider is healthy enough to finish.

The pipeline is checkpointed, so each attempt resumes from the last completed
stage instead of paying twice. This exists because the LLM endpoint has been
intermittently returning 5xx and timing out, which is a provider condition and
not an SDK fault.

    python retry_run.py --attempts 4 -- <run_summary.py args...>
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    argv = sys.argv[1:]
    attempts = 4
    if "--attempts" in argv:
        index = argv.index("--attempts")
        attempts = int(argv[index + 1])
        del argv[index:index + 2]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print(__doc__)
        return 2

    for attempt in range(1, attempts + 1):
        print(f"\n{'#' * 70}\n# attempt {attempt}/{attempts}\n{'#' * 70}", flush=True)
        started = time.time()
        proc = subprocess.run([sys.executable, str(HERE / "run_summary.py"), *argv],
                              cwd=str(HERE))
        elapsed = time.time() - started
        if proc.returncode == 0:
            print(f"\nSUCCEEDED on attempt {attempt} in {elapsed:.0f}s")
            return 0
        if attempt < attempts:
            wait = min(60, 10 * attempt)
            print(f"\nattempt {attempt} failed after {elapsed:.0f}s; "
                  f"sleeping {wait}s before resuming from checkpoint", flush=True)
            time.sleep(wait)
    print(f"\nEXHAUSTED {attempts} attempts")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
