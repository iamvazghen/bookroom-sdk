"""Review an existing study guide, and export it in every format.

Shows the JEv quality gate run on its own, which is what you want when the
report already exists - for example one produced by an earlier run, or one you
revised by hand.

    python examples/review_and_export.py output/MyBook/study-guide.md MyBook.epub
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from bookroom_sdk import Bookroom, errors  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python review_and_export.py <study-guide.md> <source.epub>")
        return 2
    report_path = Path(sys.argv[1])
    source_path = Path(sys.argv[2])
    for path in (report_path, source_path):
        if not path.is_file():
            print(f"no such file: {path}")
            return 2

    # The only two credentials this example needs.
    llm_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("BOOKROOM_LLM_API_KEY")
    jev_api_key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("BOOKROOM_JEV_API_KEY")
    if not llm_api_key:
        print("set GEMINI_API_KEY (or BOOKROOM_LLM_API_KEY) first")
        return 2

    room = Bookroom.from_env(llm_api_key=llm_api_key, jev_api_key=jev_api_key)

    # 1. What are we reviewing? The 16 canonical categories.
    print("categories:")
    for item in room.review.report_sections():
        print(f"  {item['key']:<20} {item['heading']}")

    # 2. Deterministic checks first - cheap, and no provider is called.
    problems = room.export.validate(report_path.read_text(encoding="utf-8"))
    print(f"\nformat problems: {problems or 'none'}")

    # 3. Independent JEv review of every category, with bounded revisions.
    try:
        records = room.review.review_report(
            report_path,
            progress=lambda message, **kw: print(f"  ... {message}"),
        )
    except errors.QuotaError as exc:
        print(f"quota reached; wait {exc.retry_after_seconds}s and re-run")
        return 1

    passed = 0
    for record in records:
        attempts = record.get("attempts") or []
        if not attempts:
            continue
        final = attempts[-1]
        scores = final.get("scores") or {}
        lowest = min(scores.values()) if scores else 0
        mark = "pass" if final.get("passed") else f"below threshold (lowest {lowest})"
        passed += 1 if final.get("passed") else 0
        print(f"  {record.get('section'):<38} {mark}")

    print(f"\n{passed}/{len(records)} categories passed. "
          "Anything below threshold keeps its evaluation history - it is not hidden.")

    # 4. Every export format.
    pdf = room.export.pdf(report_path)
    graph = room.export.concept_map(report_path)
    claims = room.export.claim_audit(report_path)
    manifest = room.export.manifest(report_path, source_path)
    usage = room.export.usage()

    print(f"\npdf          : {pdf.path} ({Path(pdf.path).stat().st_size:,} bytes)")
    print(f"concepts     : {len(graph.get('nodes', []))} nodes, "
          f"{len(graph.get('edges', []))} relationships")
    print(f"claims       : {claims.get('claim_count')} triaged")
    print(f"model        : {manifest.get('generation_model')}")
    print(f"llm calls    : {usage.get('calls')} ({usage.get('total_tokens'):,} tokens)")

    flagged = [c for c in claims.get("claims", []) if c.get("status") == "low_overlap_review"]
    if flagged:
        print(f"\n{len(flagged)} claims had low lexical overlap and want a human look:")
        for claim in flagged[:5]:
            print(f"  - {claim['claim'][:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
