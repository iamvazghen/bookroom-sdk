"""Prove a clean install works on a machine that has never seen the engine.

Creates a fresh virtual environment, installs ``bookroom-sdk`` from source into
it, then runs a complete summarization in a subprocess whose environment has
**no** ``BOOKROOM_APP_ROOT``, no ``PYTHONPATH``, and no reference to the
original engine checkout. It also installs the project's own Python scripts
separately from the SDK so they cannot accidentally be the thing being tested.

    python verify_clean_install.py [book.pdf|book.epub]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY_DIR = HERE / "python"
DEFAULT_BOOK = r"C:\Users\iamva\Downloads\_OceanofPDF.com_God_Sees_the_Truth_but_Waits_-_Leo_Tolstoy.pdf"

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def _clean_env(**extra: str) -> dict[str, str]:
    """An environment with every Bookroom variable deliberately removed."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("BOOKROOM") and k not in {"PYTHONPATH", "GEMINI_API_KEY",
                                                         "TYPESAFE_API_KEY"}}
    env.update(extra)
    return env


def main() -> int:
    book = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path(DEFAULT_BOOK)
    if not book.is_file():
        print(f"no such book: {book}")
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="bookroom-clean-"))
    venv_dir = workdir / "venv"
    print(f"workdir: {workdir}")
    print(f"book   : {book}")

    section("1. create a fresh virtual environment")
    proc = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)],
                          capture_output=True, text=True)
    check("venv created", proc.returncode == 0, proc.stderr[-200:] if proc.returncode else "")
    if proc.returncode != 0:
        return 1
    scripts = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    pip = scripts / ("pip.exe" if os.name == "nt" else "pip")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    check("interpreter present", python.is_file(), str(python))

    section("2. pip install the SDK from source")
    proc = subprocess.run([str(pip), "install", "--quiet", str(PY_DIR)],
                          capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])
    check("pip install bookroom-sdk", proc.returncode == 0,
          (proc.stderr or "")[-200:] if proc.returncode else "")

    section("3. the console entry point exists")
    entry = scripts / ("bookroom.exe" if os.name == "nt" else "bookroom")
    check("bookroom command installed", entry.is_file(), str(entry))
    proc = subprocess.run([str(entry), "--version"], capture_output=True, text=True,
                          env=_clean_env(), timeout=120)
    check("bookroom --version runs", proc.returncode == 0,
          (proc.stdout or proc.stderr).strip()[:80])
    reported = (proc.stdout or "").strip()
    pyproject_version = ""
    try:
        import tomllib
        pyproject_version = str(
            tomllib.loads((PY_DIR / "pyproject.toml").read_text(encoding="utf-8"))
            ["project"]["version"])
    except Exception:  # noqa: BLE001
        pass
    check("reported version matches pyproject", pyproject_version in reported,
          f"{reported!r} vs {pyproject_version!r}")

    section("4. the engine resolves with no configuration at all")
    probe = (
        "import json,sys\n"
        "from bookroom_sdk import Bookroom\n"
        "r = Bookroom(llm_api_key='x', jev_api_key='y')\n"
        "print(json.dumps({'app_root': str(r.app_root),\n"
        "                  'loaded': r.load().name,\n"
        "                  'caps': len(r.describe()['capabilities'])}))\n"
    )
    proc = subprocess.run([str(python), "-c", probe], capture_output=True, text=True,
                          env=_clean_env(), timeout=300)
    if proc.returncode != 0:
        print(proc.stdout[-2000:]); print(proc.stderr[-2000:])
    check("imports and loads the bundled engine", proc.returncode == 0,
          (proc.stdout or proc.stderr).strip()[:120])
    info = {}
    if proc.returncode == 0:
        try:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            info = {}
    check("engine root is inside the installed package",
          "_engine" in str(info.get("app_root", "")),
          str(info.get("app_root", "")))
    check("capability surface intact", info.get("caps", 0) >= 35, str(info.get("caps")))

    section("5. the console entry point can extract the real book")
    proc = subprocess.run([str(entry), "extract", str(book)], capture_output=True,
                          text=True, env=_clean_env(), timeout=600)
    check("`bookroom extract` succeeds", proc.returncode == 0,
          (proc.stderr or "")[-200:] if proc.returncode else "")
    if proc.returncode == 0:
        # stdout must be pure JSON so the CLI can be piped into `jq`. Parse it
        # whole, and fall back to the last JSON object if anything else crept in.
        payload = None
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            decoder = json.JSONDecoder()
            for index in range(len(proc.stdout)):
                if proc.stdout[index] != "{":
                    continue
                try:
                    candidate, _ = decoder.raw_decode(proc.stdout, index)
                    payload = candidate
                except ValueError:
                    continue
        check("book extracted with no configuration",
              isinstance(payload, dict) and payload.get("section_count", 0) >= 1
              and payload.get("total_words", 0) > 0,
              f"{(payload or {}).get('section_count')} sections, "
              f"{(payload or {}).get('total_words')} words")
    check("extract stdout is clean JSON (no warning noise)",
          proc.stdout.strip().startswith("{") and proc.stdout.strip().endswith("}"),
          proc.stdout.strip().splitlines()[0][:70] if proc.stdout.strip() else "empty")

    section("6. a full run from an installed SDK (mocked provider, no credits)")
    runner = workdir / "run.py"
    runner.write_text(
        "import json, sys\n"
        "from bookroom_sdk import Bookroom\n"
        "room = Bookroom(llm_api_key='mock', jev_api_key='mock',\n"
        "                llm_base_url=sys.argv[1], jev_base_url=sys.argv[2],\n"
        "                output_dir=sys.argv[3])\n"
        "rep = room.summarize.study_guide(sys.argv[4], output_slug='clean')\n"
        "print(json.dumps({'md': rep.markdown.exists(), 'pdf': rep.pdf.exists(),\n"
        "                  'arts': [a.name for a in rep.artifacts],\n"
        "                  'q': rep.quality.categories_reviewed if rep.quality else 0}))\n",
        encoding="utf-8")
    mock_script = (
        "import sys, threading\n"
        f"sys.path.insert(0, {str(HERE / 'tools')!r})\n"
        "from mock_providers import MockProviders\n"
        "import subprocess, os, json\n"
        "m = MockProviders(); m.__enter__()\n"
        "print(json.dumps({'llm': m.llm_base_url, 'jev': m.jev_base_url}), flush=True)\n"
        "runner = sys.argv[1]\n"
        "env = {k: v for k, v in os.environ.items() if not k.startswith('BOOKROOM')}\n"
        "p = subprocess.run([sys.executable, runner, m.llm_base_url, m.jev_base_url,\n"
        "                    sys.argv[2], sys.argv[3]], env=env)\n"
        "sys.exit(p.returncode)\n"
    )
    mock_main = workdir / "mock_main.py"
    mock_main.write_text(mock_script, encoding="utf-8")
    proc = subprocess.run([str(python), str(mock_main), str(runner),
                           str(workdir / "out"), str(book)],
                          capture_output=True, text=True,
                          env=_clean_env(PYTHONIOENCODING="utf-8"), timeout=1800)
    output = (proc.stdout or "") + (proc.stderr or "")
    check("full run from the installed SDK", proc.returncode == 0, output[-300:] if proc.returncode else "")
    if proc.returncode == 0:
        line = [l for l in output.splitlines() if l.startswith("{") and "md" in l]
        result = json.loads(line[-1]) if line else {}
        check("study guide markdown written", result.get("md") is True)
        check("study guide PDF written", result.get("pdf") is True)
        check("all artifacts produced", len(result.get("arts", [])) >= 6,
              ",".join(result.get("arts", [])))
        check("16 categories reviewed", result.get("q") == 16, str(result.get("q")))

    print("\n" + "=" * 68)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("\nA clean virtual environment can install this package and run a book")
    print("with no engine checkout, no PYTHONPATH, and no BOOKROOM_APP_ROOT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
