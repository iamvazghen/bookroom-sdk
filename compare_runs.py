"""Compare two summarization runs and report whether anything diverges.

    python compare_runs.py runs/sdk runs/baseline

Both directories must contain a ``run-report.json`` written by
``run_summary.py`` or ``run_baseline.py``, plus the generated artifacts.

The comparison is deliberately structural rather than textual: two runs of a
non-deterministic LLM pipeline will never produce byte-identical prose. What
must match is the *shape* of the result - which artifacts exist, how many
report categories were produced, whether each validated, whether anything
failed. Prose similarity is reported as information, not as a pass/fail.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_ARTIFACTS = (
    "study-guide.md", "chapter-notes.md", "study-guide.pdf", "study-maps.json",
    "claim-audit.json", "manifest.json", "usage.json", "evaluations.json",
)


def _load(directory: Path, name: str = "run-report.json") -> dict[str, Any] | None:
    target = directory / name
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _guide_path(directory: Path, report: dict[str, Any]) -> Path | None:
    stages = report.get("stages") or {}
    candidate = stages.get("report_path")
    if candidate and Path(candidate).is_file():
        return Path(candidate)
    for folder in sorted(directory.glob("**/study-guide.md")):
        return folder
    return None


def _on_disk(directory: Path) -> dict[str, Path]:
    """Every file the run left on disk, keyed by name.

    Both runs are enumerated the same way from the filesystem rather than from
    each runner's own artifact list, so a difference in how a runner *reports*
    its artifacts can never be mistaken for a difference in what it produced.
    """
    guide = _guide_path(directory, {})
    root = guide.parent if guide else directory
    found: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found[path.name] = path
    return found


def _prose_fingerprint(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines()]
    headings = [line for line in lines if line.startswith("## ")]
    words = re.findall(r"[A-Za-z']+", text)
    body = "\n".join(line for line in lines if not line.startswith("#"))
    shingle = set()
    tokens = re.findall(r"[a-z']+", body.lower())
    for index in range(len(tokens) - 4):
        shingle.add(" ".join(tokens[index:index + 5]))
    return {
        "characters": len(text),
        "words": len(words),
        "h2_headings": len(headings),
        "h2_names": headings,
        "five_word_shingles": len(shingle),
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two summarization runs.")
    parser.add_argument("left", help="Run directory using the SDK")
    parser.add_argument("right", help="Run directory using the application path")
    parser.add_argument("--tolerance", type=float, default=0.35,
                        help="Minimum prose overlap before a warning is raised")
    args = parser.parse_args()

    left_dir = Path(args.left).expanduser().resolve()
    right_dir = Path(args.right).expanduser().resolve()
    left = _load(left_dir)
    right = _load(right_dir)

    problems: list[str] = []
    notes: list[str] = []
    rows: list[tuple[str, str, str]] = []

    def add(label: str, a: Any, b: Any, *, required: bool = True) -> None:
        ok = a == b
        if not ok and required:
            problems.append(f"{label}: {a!r} != {b!r}")
        rows.append((label, str(a), str(b) + ("" if ok else "   <-- DIFFERS")))

    print("=" * 74)
    print("BOOKROOM RUN COMPARISON")
    print(f"  SDK run      : {left_dir}")
    print(f"  baseline run : {right_dir}")
    print("=" * 74)

    if left is None or right is None:
        missing = left_dir if left is None else right_dir
        print(f"\nERROR: no run-report.json in {missing}")
        return 2

    print("\n--- 1. did both runs finish? ---")
    left_ok = bool(left.get("ok"))
    right_ok = bool(right.get("ok"))
    print(f"  SDK      : ok={left_ok} error={left.get('error')}")
    print(f"  baseline : ok={right_ok} error={right.get('error')}")
    if not left_ok:
        problems.append(f"SDK run did not complete: {left.get('error')}")
    if not right_ok:
        problems.append(f"baseline run did not complete: {right.get('error')}")

    print("\n--- 2. same source, same configuration? ---")
    add("source file", left.get("source"), right.get("source"))
    add("source bytes", left.get("source_bytes"), right.get("source_bytes"))
    left_model = ((left.get("config") or {}).get("llm_model"))
    right_model = ((right.get("config") or {}).get("llm_model"))
    add("llm model", left_model, right_model)
    left_review = ((left.get("config") or {}).get("jev_enabled"))
    right_review = ((right.get("config") or {}).get("jev_enabled"))
    add("jev enabled", left_review, right_review)

    print("\n--- 3. extraction agreement ---")
    left_sections = ((left.get("stages") or {}).get("document") or {}).get("section_count")
    right_sections = ((right.get("stages") or {}).get("extract") or {}).get("section_count")
    add("section count", left_sections, right_sections)
    left_pre = (left.get("stages") or {}).get("preflight") or {}
    right_pre = (right.get("stages") or {}).get("preflight") or {}
    add("preflight sections", left_pre.get("section_count"), right_pre.get("section_count"))
    add("preflight batches", left_pre.get("batch_count"), right_pre.get("batch_count"))
    if left_pre.get("gemini_input_tokens_estimate") != right_pre.get("gemini_input_tokens_estimate"):
        notes.append("token estimates differ (expected: the SDK and the app size prompts identically "
                     "but the estimate is derived from section lengths)")

    print("\n--- 4. artifacts produced (enumerated from disk) ---")
    left_files = _on_disk(left_dir)
    right_files = _on_disk(right_dir)
    for artifact in EXPECTED_ARTIFACTS:
        in_left, in_right = artifact in left_files, artifact in right_files
        status = "ok" if in_left == in_right else "DIFFERS"
        if in_left != in_right:
            problems.append(f"artifact {artifact}: sdk={in_left} baseline={in_right}")
        print(f"  {artifact:<24} sdk={'yes' if in_left else 'no':<4} "
              f"baseline={'yes' if in_right else 'no':<4}  {status}")
    only_sdk = sorted(set(left_files) - set(right_files))
    only_base = sorted(set(right_files) - set(left_files))
    if only_sdk:
        notes.append(f"only in SDK run: {', '.join(only_sdk)}")
    if only_base:
        notes.append(f"only in baseline run: {', '.join(only_base)}")

    print("\n  byte-identical check for shared artifacts:")
    identical = 0
    for name in sorted(set(left_files) & set(right_files)):
        if name in {".pipeline-cache.json", "usage.json", "partial-chapter-notes.md"}:
            continue  # caches and run-scoped counters legitimately differ
        same = left_files[name].read_bytes() == right_files[name].read_bytes()
        identical += 1 if same else 0
        print(f"    {name:<24} {'IDENTICAL' if same else 'differs'}")
        if not same:
            notes.append(f"{name} differs between the two runs")

    print("\n--- 5. report validity ---")
    left_checks = (left.get("stages") or {}).get("checks") or {}
    right_checks = (right.get("stages") or {}).get("checks") or {}
    left_problems = left_checks.get("format_problems")
    right_problems = right_checks.get("format_problems")
    add("format validation clean", left_problems == [], right_problems == [])
    print(f"  SDK format problems      : {left_problems if left_problems else 'none'}")
    print(f"  baseline format problems : {right_problems if right_problems else 'none'}")

    left_guide = _guide_path(left_dir, left)
    right_guide = _guide_path(right_dir, right)
    print("\n--- 6. report content ---")
    if left_guide and right_guide:
        left_text = left_guide.read_text(encoding="utf-8")
        right_text = right_guide.read_text(encoding="utf-8")
        left_fp = _prose_fingerprint(left_text)
        right_fp = _prose_fingerprint(right_text)
        add("level-2 section count", left_fp["h2_headings"], right_fp["h2_headings"])
        left_headings = set(left_fp["h2_names"])
        right_headings = set(right_fp["h2_names"])
        missing = sorted(left_headings - right_headings)
        extra = sorted(right_headings - left_headings)
        if missing:
            problems.append(f"baseline is missing headings: {missing}")
        if extra:
            problems.append(f"baseline has extra headings: {extra}")
        print(f"  SDK      : {left_fp['characters']:,} chars, {left_fp['words']:,} words, "
              f"{left_fp['h2_headings']} sections")
        print(f"  baseline : {right_fp['characters']:,} chars, {right_fp['words']:,} words, "
              f"{right_fp['h2_headings']} sections")

        left_shingles = set()
        right_shingles = set()
        for text, sink in ((left_text, left_shingles), (right_text, right_shingles)):
            tokens = re.findall(r"[a-z']+", text.lower())
            for index in range(len(tokens) - 4):
                sink.add(" ".join(tokens[index:index + 5]))
        overlap = _jaccard(left_shingles, right_shingles)
        print(f"  5-gram overlap          : {overlap:.1%}")
        if overlap < args.tolerance:
            notes.append(
                f"prose overlap {overlap:.1%} is below {args.tolerance:.0%}. This is normal for a "
                "non-deterministic LLM pipeline; it is not a failure, but it does mean the two runs "
                "are independent samples rather than the same text."
            )
    else:
        problems.append("could not locate a study-guide.md in one of the runs")

    print("\n--- 7. review outcome ---")
    left_quality = ((left.get("stages") or {}).get("report") or {}).get("quality") or {}
    print(f"  SDK categories reviewed : {left_quality.get('categories_reviewed')}")
    print(f"  SDK categories passed   : {left_quality.get('categories_passed')}")
    baseline_evaluations = right_dir / "tolstoy-baseline" / "evaluations.json"
    for candidate in sorted(right_dir.glob("**/evaluations.json")):
        baseline_evaluations = candidate
        break
    if baseline_evaluations.is_file():
        try:
            data = json.loads(baseline_evaluations.read_text(encoding="utf-8"))
            records = data.get("report_sections", [])
            latest = [r["attempts"][-1] for r in records if r.get("attempts")]
            passed = sum(1 for a in latest if a.get("passed"))
            print(f"  baseline categories     : {len(latest)} reviewed, {passed} passed")
            add("categories reviewed", left_quality.get("categories_reviewed"), len(latest))
        except ValueError:
            notes.append("baseline evaluations.json was not valid JSON")

    print("\n--- 8. provider usage ---")
    left_calls = left_checks.get("llm_calls")
    left_tokens = left_checks.get("llm_total_tokens")
    right_calls = right_checks.get("llm_calls")
    right_tokens = right_checks.get("llm_total_tokens")
    print(f"  SDK      : {left_calls} calls, {left_tokens:,} tokens"
          if isinstance(left_tokens, int) else f"  SDK      : {left_calls} calls")
    print(f"  baseline : {right_calls} calls, {right_tokens:,} tokens"
          if isinstance(right_tokens, int) else f"  baseline : {right_calls} calls")
    print(f"  SDK elapsed     : {left.get('elapsed_seconds')}s")
    print(f"  baseline elapsed: {right.get('elapsed_seconds')}s")

    print("\n" + "=" * 74)
    if problems:
        print(f"RESULT: {len(problems)} difference(s) found")
        for problem in problems:
            print(f"  ! {problem}")
    else:
        print("RESULT: no functional differences - the SDK is a faithful wrapper")
    if notes:
        print("\nNotes (not failures):")
        for note in notes:
            print(f"  - {note}")
    print("=" * 74)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
