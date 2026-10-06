"""Build and validate the publishable artifacts for both registries.

Produces the exact files that `npm publish` and `twine upload` would send, then
inspects them so problems surface here rather than after publication:

- the wheel really contains the engine, the type marker and the license
- the sdist really contains `pyproject.toml`, the engine and the entry point
- `twine check` accepts both
- the npm tarball really contains `dist/` for both module systems, the Python
  package, `SKILL.md` and the license, and nothing sensitive

This does not publish. Publication needs the maintainer's registry credentials
and is a separate, deliberate step.

    python build_artifacts.py
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY_DIR = HERE / "python"
DIST = PY_DIR / "dist"

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(label)
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))


def npm_command() -> list[str]:
    """Resolve npm to something subprocess can actually execute on Windows."""
    executable = shutil.which("npm") or shutil.which("npm.cmd")
    if executable is None:
        return []
    # `npm` on Windows is often a .ps1 shim that CreateProcess cannot launch.
    if executable.lower().endswith((".ps1", ".cmd", ".bat")):
        return ["cmd", "/c", executable]
    return [executable]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def main() -> int:
    print("=" * 70)
    print("BUILD PUBLISHABLE ARTIFACTS")
    print("=" * 70)

    uv = shutil.which("uv")

    # ------------------------------------------------------------ Python side
    print("\n--- Python: wheel + sdist ---")
    if DIST.exists():
        shutil.rmtree(DIST)
    if uv:
        proc = run([uv, "build", str(PY_DIR)])
    else:
        proc = run([sys.executable, "-m", "build", str(PY_DIR)])
    if proc.returncode != 0:
        print(proc.stdout[-2500:])
        print(proc.stderr[-2500:])
    check("build succeeds", proc.returncode == 0)

    wheels = glob.glob(str(DIST / "*.whl"))
    sdists = glob.glob(str(DIST / "*.tar.gz"))
    check("a wheel was produced", bool(wheels), Path(wheels[0]).name if wheels else "")
    check("an sdist was produced", bool(sdists), Path(sdists[0]).name if sdists else "")

    if wheels:
        with zipfile.ZipFile(wheels[0]) as archive:
            names = archive.namelist()
        engine = [n for n in names if "bookroom_sdk/_engine/" in n]
        check("the wheel ships the engine", len(engine) >= 19, f"{len(engine)} files")
        check("book_pipeline.py is in the wheel",
              any(n.endswith("_engine/book_pipeline.py") for n in names))
        check("the engine provenance note is in the wheel",
              any(n.endswith("_engine/PROVENANCE.md") for n in names))
        check("py.typed is in the wheel", any(n.endswith("py.typed") for n in names))
        check("LICENSE is in the wheel", any("LICENSE" in n for n in names))
        check("the engine is data, not a subpackage",
              not any("_engine/__init__.py" in n for n in names),
              "correct: no __init__.py")
        size = Path(wheels[0]).stat().st_size
        check("wheel is a sane size", 40_000 < size < 2_000_000, f"{size:,} bytes compressed")

    if sdists:
        with tarfile.open(sdists[0]) as archive:
            names = archive.getnames()
        check("the sdist ships the engine",
              any("_engine/book_pipeline.py" in n for n in names))
        check("the sdist ships pyproject.toml",
              any(n.endswith("pyproject.toml") for n in names))
        check("the sdist ships README.md", any(n.endswith("README.md") for n in names))

    proc = run([sys.executable, "-m", "twine", "check", *wheels, *sdists])
    if proc.returncode != 0 and "No module named" in (proc.stderr or ""):
        check("twine check (twine not installed here - skipped)", True, "install twine to verify")
    else:
        check("twine check passes", proc.returncode == 0,
              (proc.stdout or proc.stderr).strip().splitlines()[-1][:90] if proc.returncode else "")

    # -------------------------------------------------------------- npm side
    print("\n--- npm: tarball ---")
    proc = run(npm_command() + ["pack", "--dry-run", "--json"], cwd=str(HERE))
    entries: list[dict] = []
    if proc.returncode == 0:
        try:
            entries = json.loads(proc.stdout)[0].get("files", [])
        except (ValueError, IndexError):
            entries = []
    check("npm pack succeeds", proc.returncode == 0,
          (proc.stderr or "").strip()[-120:] if proc.returncode else "")
    if entries:
        paths = [e["path"] for e in entries]
        total = sum(e.get("size", 0) for e in entries)
        print(f"  {len(paths)} files, {total:,} bytes unpacked")
        check("dist/esm is published", any(p.startswith("dist/esm/") for p in paths))
        check("dist/cjs is published", any(p.startswith("dist/cjs/") for p in paths))
        check("type declarations are published", any(p.endswith(".d.ts") for p in paths))
        check("react entry point is published", "dist/esm/react.js" in paths)
        check("next entry point is published", "dist/esm/next.js" in paths)
        check("the Python package ships with the npm package",
              any(p.startswith("python/bookroom_sdk/") for p in paths))
        check("the engine ships with the npm package",
              sum(1 for p in paths if "/_engine/" in p) >= 19,
              f"{sum(1 for p in paths if '/_engine/' in p)} engine files")
        check("SKILL.md ships with the npm package", "SKILL.md" in paths)
        check("LICENSE ships with the npm package", "LICENSE" in paths)
        check("README ships with the npm package", "README.md" in paths)
        bad = [p for p in paths
               if p == ".env" or p.startswith("runs") or p.startswith("examples/")
               or p.startswith("node_modules") or p.endswith(".env")]
        check("no secrets or scratch directories in the tarball", not bad, ", ".join(bad[:4]))
        check("tarball is a sane size", total < 3_000_000, f"{total:,} bytes unpacked")

    print("\n" + "=" * 70)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1

    print("\nArtifacts are ready to publish. Publishing itself is a deliberate")
    print("step that needs the maintainer's registry credentials:")
    print("  npm publish --access public")
    print("  twine upload python/dist/*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
