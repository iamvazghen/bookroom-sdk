"""Full summarization cycle through the Bookroom SDK. No UI.

    python run_summary.py <book.pdf|book.epub> [--out DIR] [--slug NAME] [--no-review]

Runs every stage the SDK exposes, in order, and writes a machine-readable
``run-report.json`` next to the outputs so a later comparison can diff two runs
without re-reading the prose.

Stages
  1. credential + reachability check (never sends book content)
  2. preflight estimate and budget enforcement
  3. extraction
  4. full study guide: chapter notes, digest, JEv review, all exports
  5. post-hoc exports and audits
  6. run report
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE / "python") not in sys.path:
    sys.path.insert(0, str(HERE / "python"))

from bookroom_sdk import Bookroom, errors  # noqa: E402


def _emit(message: str) -> None:
    print(message, flush=True)


def _artifact_rows(report: Any) -> list[dict[str, Any]]:
    rows = []
    for artifact in report.artifacts:
        path = Path(artifact.path) if artifact.path else None
        rows.append({
            "name": artifact.name,
            "media_type": artifact.media_type,
            "exists": bool(path and path.is_file()),
            "bytes": path.stat().st_size if path and path.is_file() else 0,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full Bookroom summarization cycle.")
    parser.add_argument("source", help="Path to a .pdf or .epub book")
    parser.add_argument("--out", default="output", help="Output directory (default: output)")
    parser.add_argument("--slug", default=None, help="Output folder name (default: from filename)")
    parser.add_argument("--app-root", default=None,
                        help="Book Summarizer source root (contains book_pipeline.py). "
                             "Defaults to BOOKROOM_APP_ROOT, then D:\\summarizer\\src.")
    parser.add_argument("--no-review", action="store_true", help="Skip JEv review")
    parser.add_argument("--language", default="English")
    parser.add_argument("--length", default="standard", choices=("brief", "standard", "deep"))
    parser.add_argument("--report-name", default="run-report.json")
    args = parser.parse_args()

    source = Path(args.source).expanduser()
    if not source.is_file():
        _emit(f"error: no such file: {source}")
        return 2

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    run: dict[str, Any] = {
        "source": str(source),
        "source_bytes": source.stat().st_size,
        "output_dir": str(out_dir),
        "sdk": "bookroom-sdk",
        "stages": {},
    }

    # The SDK needs to know where the Book Summarizer engine lives. In a monorepo
    # checkout it can be discovered; in a standalone project it must be told.
    import os

    app_root = args.app_root or os.environ.get("BOOKROOM_APP_ROOT") or r"D:\summarizer\src"
    try:
        room = Bookroom.from_env(output_dir=out_dir, app_root=Path(app_root))
    except errors.ConfigError as exc:
        _emit(f"error: {exc}")
        return 2

    described = room.describe()
    run["config"] = described["config"]
    _emit("=" * 66)
    _emit(f"LLM      : {described['config']['llm_endpoint']}  model={described['config']['llm_model']}")
    _emit(f"review   : {described['config']['jev_endpoint']}  model={described['config']['jev_model']}"
          f"  enabled={described['config']['jev_enabled']}")
    _emit(f"app root : {described['config']['app_root']}")
    _emit("=" * 66)

    # --- 1. credentials ----------------------------------------------------
    _emit("\n[1/6] credential and reachability check")
    try:
        health = room.check()
    except errors.BookroomError as exc:
        _emit(f"  FAILED: {type(exc).__name__}: {exc}")
        run["error"] = f"health: {exc}"
        _write(out_dir, args.report_name, run)
        return 1
    _emit(f"  llm    : {health.llm.get('status')} ({health.llm.get('model')})")
    _emit(f"  review : {health.review.get('status')} ({health.review.get('model')})")
    run["stages"]["health"] = health.as_dict()
    if health.llm.get("status") != "ok":
        _emit(f"  LLM not usable: {health.llm.get('message')}")
        run["error"] = "llm not usable"
        _write(out_dir, args.report_name, run)
        return 1

    # --- 2. preflight ------------------------------------------------------
    _emit("\n[2/6] preflight estimate")
    try:
        plan = room.summarize.preflight(source, options={
            "language": args.language, "digest_length": args.length})
    except errors.BookroomError as exc:
        _emit(f"  FAILED: {type(exc).__name__}: {exc}")
        run["error"] = f"preflight: {exc}"
        _write(out_dir, args.report_name, run)
        return 1
    _emit(f"  sections        : {plan.section_count}")
    _emit(f"  work batches    : {plan.batch_count}")
    _emit(f"  llm input tokens: {plan.estimated_llm_input_tokens:,} (estimate)")
    _emit(f"  review credits  : {plan.estimated_jev_credits:,} (worst case)")
    run["stages"]["preflight"] = plan.as_dict()

    # --- 3. extraction -----------------------------------------------------
    _emit("\n[3/6] extraction")
    try:
        document = room.extract.extract(source, options={
            "language": args.language, "digest_length": args.length})
    except errors.BookroomError as exc:
        _emit(f"  FAILED: {type(exc).__name__}: {exc}")
        run["error"] = f"extract: {exc}"
        _write(out_dir, args.report_name, run)
        return 1
    _emit(f"  title   : {document.title}")
    _emit(f"  sections: {document.section_count}   words: {document.total_words:,}")
    for section in document.sections[:5]:
        _emit(f"    - {section.title}  [{section.locator}]")
    run["stages"]["document"] = document.as_dict()

    # --- 4. the full job ---------------------------------------------------
    _emit("\n[4/6] full study guide (notes, digest, JEv review, exports)")
    last = [time.time()]

    def progress(message, **kwargs):
        if time.time() - last[0] > 3:
            _emit(f"  ... {message}")
            last[0] = time.time()

    try:
        report = room.summarize.study_guide(
            source,
            options={"language": args.language, "digest_length": args.length},
            output_slug=args.slug,
            review=not args.no_review,
            progress=progress,
        )
    except errors.QuotaError as exc:
        _emit(f"  QUOTA reached; wait {exc.retry_after_seconds}s and re-run to resume")
        run["error"] = f"quota: {exc}"
        _write(out_dir, args.report_name, run)
        return 1
    except errors.BookroomError as exc:
        _emit(f"  FAILED: {type(exc).__name__}: {exc}")
        run["error"] = f"study_guide: {exc}"
        _write(out_dir, args.report_name, run)
        return 1

    markdown = report.markdown.read_text()
    _emit(f"  markdown : {len(markdown):,} characters")
    _emit(f"  headings : {sum(1 for line in markdown.splitlines() if line.startswith('## '))} section headings")
    if report.quality:
        q = report.quality
        _emit(f"  review   : {q.categories_passed}/{q.categories_reviewed} categories at or above {q.threshold}")
    run["stages"]["report"] = report.as_dict()

    # --- 5. exports and audits --------------------------------------------
    _emit("\n[5/6] exports and audits")
    checks: dict[str, Any] = {}
    problems = room.export.validate(markdown)
    checks["format_problems"] = problems
    _emit(f"  format validation : {'OK' if not problems else problems}")

    claims = room.export.claim_audit(report.markdown.path)
    graph = room.export.concept_map(report.markdown.path)
    manifest = room.export.manifest(report.markdown.path, source)
    usage = room.export.usage()
    checks["claim_count"] = claims.get("claim_count", 0)
    checks["low_overlap_claims"] = sum(
        1 for c in claims.get("claims", []) if c.get("status") == "low_overlap_review")
    checks["concept_nodes"] = len(graph.get("nodes", []))
    checks["concept_edges"] = len(graph.get("edges", []))
    checks["llm_calls"] = usage.get("calls", 0)
    checks["llm_total_tokens"] = usage.get("total_tokens", 0)
    _emit(f"  claims            : {checks['claim_count']} triaged, "
          f"{checks['low_overlap_claims']} flagged for review")
    _emit(f"  concept map       : {checks['concept_nodes']} nodes, {checks['concept_edges']} edges")
    _emit(f"  llm usage         : {checks['llm_calls']} calls, "
          f"{checks['llm_total_tokens']:,} tokens")
    run["stages"]["checks"] = checks
    run["artifacts"] = _artifact_rows(report)

    _emit("\n  artifacts:")
    for row in run["artifacts"]:
        mark = "ok " if row["exists"] else "MISSING"
        _emit(f"    [{mark}] {row['name']:<22} {row['bytes']:>9,} bytes  {row['media_type']}")

    # --- 6. run report -----------------------------------------------------
    run["elapsed_seconds"] = round(time.time() - started, 2)
    run["ok"] = True
    _emit(f"\n[6/6] done in {run['elapsed_seconds']}s")
    report_path = _write(out_dir, args.report_name, run)
    _emit(f"run report: {report_path}")
    return 0


def _write(out_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                      encoding="utf-8")
    return target


if __name__ == "__main__":
    raise SystemExit(main())
