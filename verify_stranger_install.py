"""Can a stranger install and run Bookroom from scratch?

Installs from the public GitHub URL into a throwaway virtual environment - the
way someone who has never seen this machine would - then exercises the SDK and
the console command against a real book, with credentials passed only through
the environment.

    python verify_stranger_install.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The Python project lives in python/, so pip needs the subdirectory fragment.
# Without it, `pip install git+<repo>` fails with "neither 'setup.py' no
# 'pyproject.toml' found", because it only looks at the repository root.
REPO = "https://github.com/iamvazghen/bookroom-sdk.git"
PYTHON_PROJECT = f"{REPO}#subdirectory=python"

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def read_keys() -> dict[str, str]:
    """The credentials a user would have in their own environment."""
    source = Path(r"D:\summarizer\src\.env")
    keys: dict[str, str] = {}
    if not source.is_file():
        return keys
    for raw in source.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if "=" not in line or line.startswith("#"):
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if name in {"GEMINI_API_KEY", "TYPESAFE_API_KEY"} and value:
            keys[name] = value
    return keys


def report_summary(passed: int, failed: int) -> None:
    print("\n" + "=" * 68)
    print(f"PASSED {passed}   FAILED {failed}")
    for name in FAILED:
        print(f"  - {name}")
    print("=" * 68)


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="bookroom-stranger-"))
    venv_dir = workdir / "venv"
    print(f"workdir: {workdir}")

    keys = read_keys()
    if not keys:
        print("No credentials available; the live-provider stages cannot run.")
        return 2
    print(f"credentials found: {', '.join(keys)} (values not shown)")

    # A clean environment: nothing inherited from this shell, no PYTHONPATH,
    # no BOOKROOM_* variable, and a working directory with no .env in it.
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith("BOOKROOM") and k != "PYTHONPATH"}
    clean.update(keys)
    clean["PYTHONIOENCODING"] = "utf-8"

    section("1. the package is NOT on a registry yet")
    for name, url in (("PyPI", f"https://pypi.org/pypi/bookroom-sdk/json"),
                      ("npm", "https://registry.npmjs.org/bookroom-sdk")):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                code = response.status
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", type(exc).__name__)
        check(f"{name}: bookroom-sdk is unpublished", code == 404, f"HTTP {code}")

    section("2. install from GitHub into a fresh environment")
    proc = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)],
                          capture_output=True, text=True)
    check("virtual environment created", proc.returncode == 0)
    if proc.returncode != 0:
        return 1
    scripts = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    pip = scripts / ("pip.exe" if os.name == "nt" else "pip")

    # The bare repository URL is checked too, because that is the command a
    # reader is most likely to try first and it does not work.
    bare = subprocess.run([str(pip), "install", "--quiet", "--dry-run", f"git+{REPO}"],
                          capture_output=True, text=True, env=clean, timeout=900)
    check("bare `git+<repo>` correctly reports it is not a Python project",
          bare.returncode != 0, "expected failure without #subdirectory=python")

    proc = subprocess.run([str(pip), "install", "--quiet", f"bookroom-sdk @ git+{PYTHON_PROJECT}"],
                          capture_output=True, text=True, env=clean, timeout=2400)
    if proc.returncode != 0:
        print(proc.stdout[-2500:]); print(proc.stderr[-2500:])
    check("pip install with #subdirectory=python succeeds", proc.returncode == 0,
          (proc.stderr or "").strip()[-160:] if proc.returncode else "")

    section("3. the console command exists")
    entry = scripts / ("bookroom.exe" if os.name == "nt" else "bookroom")
    if not check("bookroom command installed", entry.is_file()):
        print("  (skipping the stages that need the console command)")
        report_summary(len(PASSED), len(FAILED))
        return 1
    proc = subprocess.run([str(entry), "--version"], capture_output=True, text=True,
                          env=clean, timeout=120)
    check("bookroom --version", proc.returncode == 0, (proc.stdout or "").strip()[:60])

    section("4. the engine resolves with no path configured")
    probe = (
        "import json\n"
        "from bookroom_sdk import Bookroom\n"
        "r = Bookroom.from_env()\n"
        "print(json.dumps({'app_root': str(r.app_root),\n"
        "                  'bundled': '_engine' in str(r.app_root),\n"
        "                  'caps': len(r.describe()['capabilities'])}))\n"
    )
    proc = subprocess.run([str(python), "-c", probe], capture_output=True, text=True,
                          env=clean, timeout=300, cwd=str(workdir))
    if proc.returncode != 0:
        print(proc.stdout[-1500:]); print(proc.stderr[-1500:])
    check("loads the bundled engine", proc.returncode == 0)
    info: dict = {}
    if proc.returncode == 0:
        try:
            info = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            info = {}
    check("engine comes from inside the package", bool(info.get("bundled")),
          str(info.get("app_root", ""))[-60:])
    check("full capability surface", info.get("caps", 0) >= 35, str(info.get("caps")))

    section("5. a real book, read by the installed package")
    book = workdir / "book.epub"
    build = subprocess.run(
        [str(python), "-c",
         "import sys; sys.path.insert(0, sys.argv[1]);"
         "from fixtures import build_epub; from pathlib import Path;"
         "build_epub(Path(sys.argv[2])); print('ok')",
         str(HERE / "tests"), str(book)],
        capture_output=True, text=True, env=clean, timeout=300)
    check("fixture built", build.returncode == 0, (build.stderr or "").strip()[-140:])
    proc = subprocess.run([str(entry), "extract", str(book)], capture_output=True, text=True,
                          env=clean, timeout=600)
    check("`bookroom extract` reads the book", proc.returncode == 0,
          (proc.stderr or "").strip()[-160:] if proc.returncode else "")
    if proc.returncode == 0:
        try:
            doc = json.loads(proc.stdout)
            check("sections and words extracted",
                  doc.get("section_count", 0) >= 1 and doc.get("total_words", 0) > 0,
                  f"{doc.get('section_count')} sections, {doc.get('total_words')} words")
        except ValueError:
            check("sections and words extracted", False, "unparseable output")

    section("6. the credentials the user supplied are accepted")
    health = (
        "import json\n"
        "from bookroom_sdk import Bookroom\n"
        "print(json.dumps(Bookroom.from_env().check().as_dict()))\n"
    )
    proc = subprocess.run([str(python), "-c", health], capture_output=True, text=True,
                          env=clean, timeout=600, cwd=str(workdir))
    if proc.returncode != 0:
        print(proc.stderr[-1500:])
    report: dict = {}
    if proc.returncode == 0:
        try:
            report = json.loads(proc.stdout.strip().splitlines()[-1])
        except ValueError:
            report = {}
    llm_ok = (report.get("llm") or {}).get("status") == "ok"
    review_ok = (report.get("review") or {}).get("status") == "ok"
    check("LLM key accepted", llm_ok, str((report.get("llm") or {}).get("message"))[:90])
    check("review key accepted", review_ok, str((report.get("review") or {}).get("message"))[:90])

    report_summary(len(PASSED), len(FAILED))
    if llm_ok and review_ok:
        print("\nA stranger with valid keys can install from GitHub, read a book,")
        print("and have both providers accepted. A live summarization run is a")
        print("separate question - see the note in the report above.")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
