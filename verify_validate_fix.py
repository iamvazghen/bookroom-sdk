"""Reproduce the CI failure locally and prove the fix.

The bug: `export.validate(markdown_text)` treated a multi-kilobyte Markdown
*string* as a *path*. On Windows `Path.is_file()` returns False for an invalid
name, so it silently fell through and validation passed. On Linux the same call
raises `OSError: [Errno 36] File name too long`, which is what broke CI.

This script forces the Linux behaviour on any platform by installing a check
that raises for an over-long "filename", exactly as Linux does.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "python"))
sys.path.insert(0, str(HERE / "tools"))
sys.path.insert(0, str(HERE / "tests"))

from bookroom_sdk import Bookroom  # noqa: E402
from fixtures import build_epub   # noqa: E402
from mock_providers import MockProviders  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def emulate_linux_path_errors() -> None:
    """Make Path.is_file() raise on an over-long name, as Linux does."""
    original = Path.is_file

    def patched(self) -> bool:
        name = str(self)
        if len(name) > 4095:
            raise OSError(36, "File name too long")
        return original(self)

    Path.is_file = patched  # type: ignore[method-assign]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bookroom-validate-"))
    epub = build_epub(tmp / "attention.epub")

    with MockProviders() as mock:
        room = Bookroom(llm_api_key="k", jev_api_key="j",
                        llm_base_url=mock.llm_base_url,
                        jev_base_url=mock.jev_base_url,
                        output_dir=tmp / "out")
        report = room.summarize.study_guide(epub, output_slug="v")
        markdown = report.markdown.read_text(encoding="utf-8")
        print(f"markdown is {len(markdown):,} characters\n")

        check("validate() accepts report content (no provider call needed)",
              room.export.validate(markdown) == [], "clean report")
        check("validate() accepts a path string",
              room.export.validate(report.markdown.path) == [])
        check("validate() accepts a Path object",
              room.export.validate(Path(report.markdown.path)) == [])
        check("validate_file() accepts a path",
              room.export.validate_file(report.markdown.path) == [])

        broken = markdown.replace("## Glossary", "## Not A Real Section", 1)
        problems = room.export.validate(broken)
        check("validate() still reports real problems", bool(problems),
              f"{len(problems)} problem(s)")

        # Now the decisive part: force Linux semantics and re-run.
        emulate_linux_path_errors()
        try:
            result = room.export.validate(markdown)
            check("validate() survives Linux path semantics", result == [],
                  "no OSError raised")
        except OSError as exc:
            check("validate() survives Linux path semantics", False, f"OSError: {exc}")

        try:
            room.export.validate_file(tmp / "does-not-exist.md")
            check("validate_file() refuses a missing file", False, "no error raised")
        except Exception as exc:  # noqa: BLE001
            check("validate_file() refuses a missing file",
                  type(exc).__name__ == "ValidationError", type(exc).__name__)

    print("\n" + "=" * 60)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    if FAILED:
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("The CI failure is fixed at its root cause.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
