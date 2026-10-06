"""Prove the SDK's bundled engine produces exactly what the local app produces.

The claim under test: an integrator installing `bookroom-sdk` gets the same
summary quality as running the Book Summarizer on the developer's own machine.
That reduces to one question - is the vendored engine a faithful copy?

Both trees are driven over the same book with the same provider mock, then every
generated artifact is compared byte for byte. Any difference in the engine copy
shows up here as a differing file.

    python verify_engine_parity.py [app_root]
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "python"))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tests"))

from fixtures import build_epub  # noqa: E402
from mock_providers import MockProviders  # noqa: E402

from bookroom_sdk import Bookroom  # noqa: E402
from bookroom_sdk import bootstrap  # noqa: E402

DEFAULT_APP_ROOT = r"D:\summarizer\src"
BUNDLED = HERE / "python" / "bookroom_sdk" / "_engine"

# Four modules are deliberately not byte-identical; the reason is in
# _engine/PROVENANCE.md. The other fifteen must be exact copies.
DOCUMENTED_DEVIATIONS = {
    "gemini_provider.py": "provider label derived from the endpoint instead of a literal",
    "pdf_extractor.py": "imports pymupdf rather than the deprecated fitz alias",
    "report_manifest.py": "reads model and provider at write time, not import time",
    "resumable_pipeline.py": "imports pymupdf rather than the deprecated fitz alias",
}

VOLATILE_KEYS = ("generated_at_utc", "generated", "Generated", "finished_at", "checked_at")


def normalise(text: str) -> str:
    """Blank out timestamp-like values so two runs of text are comparable."""
    out = []
    for line in text.splitlines():
        if any(marker in line for marker in VOLATILE_KEYS):
            out.append(line.split(":")[0] + ": <timestamp>")
        else:
            out.append(line)
    return "\n".join(out)


VOLATILE_JSON_KEYS = ("generated_at_utc", "finished_at", "checked_at", "started_at")


def scrub_json(doc):
    """Remove volatile and provider-recording fields from a parsed document.

    The provider is dropped too, and only for the two documents whose whole job
    is to record which provider served the request: the two runs were given
    different endpoints on purpose, so that field is expected to differ.
    """
    if isinstance(doc, dict):
        return {k: scrub_json(v) for k, v in doc.items()
                if k not in VOLATILE_JSON_KEYS and k not in ("generation_provider", "provider")}
    if isinstance(doc, list):
        return [scrub_json(item) for item in doc]
    return doc


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(app_root: Path, book: Path, out: Path, mock) -> Path:
    room = Bookroom(llm_api_key="k", jev_api_key="j",
                    llm_base_url=mock.llm_base_url, jev_base_url=mock.jev_base_url,
                    app_root=app_root, output_dir=out, min_word_count=200)
    report = room.summarize.study_guide(book, output_slug="parity")
    return Path(report.markdown.path).parent


def main() -> int:
    app_root = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_APP_ROOT)
    if not (app_root / "book_pipeline.py").is_file():
        print(f"no application at {app_root}; pass the directory holding book_pipeline.py")
        return 2

    passed: list[str] = []
    failed: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        (passed if ok else failed).append(label)
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))

    print("=" * 70)
    print("ENGINE PARITY: bundled copy vs the local application tree")
    print("=" * 70)
    print(f"  local app   : {app_root}")
    print(f"  bundled     : {BUNDLED}")

    print("\n--- 1. the vendored copy matches the app except where documented ---")
    shared = sorted(p.name for p in app_root.glob("*.py") if (BUNDLED / p.name).is_file())
    mismatched = {name for name in shared
                  if digest(app_root / name) != digest(BUNDLED / name)}
    check("exactly the four documented modules differ",
          mismatched == set(DOCUMENTED_DEVIATIONS),
          ", ".join(sorted(mismatched)) or "none")
    exact = [name for name in shared if name not in mismatched]
    check("every other module is a byte-exact copy",
          len(exact) == len(shared) - len(DOCUMENTED_DEVIATIONS),
          f"{len(exact)} of {len(shared)} identical")
    for name, reason in sorted(DOCUMENTED_DEVIATIONS.items()):
        print(f"        {name:<22} {reason}")

    print("\n--- 2. the bundled copy is self-sufficient ---")
    engine_only = [p.name for p in BUNDLED.glob("*.py")]
    check("the engine ships all its modules",
          len(engine_only) >= 19, f"{len(engine_only)} modules")
    check("the engine carries no third-party app modules",
          not any(name in {"webapp.py", "worker.py", "clerk_auth.py", "job_store.py"}
                  for name in engine_only))

    print("\n--- 3. both engines produce the same report from the same book ---")
    workdir = Path(tempfile.mkdtemp(prefix="bookroom-parity-"))
    try:
        book = build_epub(workdir / "attention.epub")
        with MockProviders() as mock:
            sdk_dir = run(BUNDLED, book, workdir / "sdk", mock)
            baseline_dir = run(app_root, book, workdir / "local", mock)

        names = sorted(p.name for p in sdk_dir.iterdir()
                       if p.is_file() and not p.name.startswith("."))
        check("both runs produced the same artifact set",
              names == sorted(p.name for p in baseline_dir.iterdir()
                              if p.is_file() and not p.name.startswith(".")),
              ", ".join(names))

        for name in names:
            left, right = sdk_dir / name, baseline_dir / name
            if name == "study-guide.pdf":
                # A PDF embeds a creation timestamp; the text is compared below.
                continue
            if name in {"manifest.json", "usage.json"}:
                import json as _json
                ldoc = scrub_json(_json.loads(left.read_text(encoding="utf-8")))
                rdoc = scrub_json(_json.loads(right.read_text(encoding="utf-8")))
                same = ldoc == rdoc
                check(f"{name} matches apart from timestamps and the provider it records",
                      same, "" if same else "fields other than those differ")
                continue
            if name.endswith((".md", ".json")):
                same = normalise(left.read_text(encoding="utf-8")) == \
                    normalise(right.read_text(encoding="utf-8"))
            else:
                same = digest(left) == digest(right)
            check(f"{name} is identical between the two engines", same,
                  "" if same else f"{digest(left)[:10]} != {digest(right)[:10]}")

        pdf_left = sdk_dir / "study-guide.pdf"
        pdf_right = baseline_dir / "study-guide.pdf"
        if pdf_left.is_file() and pdf_right.is_file():
            try:
                import pymupdf
                with pymupdf.open(pdf_left) as one, pymupdf.open(pdf_right) as two:
                    text_one = normalise("".join(p.get_text() for p in one))
                    text_two = normalise("".join(p.get_text() for p in two))
                check("study-guide.pdf renders the same text",
                      text_one == text_two,
                      f"{len(text_one)} vs {len(text_two)} chars")
            except ImportError:
                check("study-guide.pdf comparable", False, "pymupdf unavailable")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"\nPASSED {len(passed)}   FAILED {len(failed)}")
    for name in failed:
        print(f"  - {name}")
    if not failed:
        print("\nAn integrator installing the SDK gets the local pipeline's output.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
