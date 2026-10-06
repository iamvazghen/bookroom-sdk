"""Baseline run through the Book Summarizer application's OWN code path.

This deliberately does **not** use the SDK. It drives the application's own
modules directly, exactly the way the shipped web app and worker do, so its
output can be compared against an SDK run to prove the SDK is a faithful
wrapper rather than a reimplementation.

    python run_baseline.py <book.pdf|book.epub> [--out DIR] [--slug NAME]

The stage sequence mirrors ``webapp_jev._run_job``:

  1. extract
  2. estimate + enforce budget, write preflight.json
  3. generate_resumable_report  (notes, digest, chapter-level JEv)
  4. evaluate_and_revise_report (16-category JEv quality gate)
  5. write_study_map, claim audit, create_pdf, usage.json, write_manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

def _default_engine_root() -> Path:
    """The engine copy bundled with the SDK, unless one is named explicitly.

    This runner deliberately bypasses the SDK, but the engine itself still
    ships inside the package, so no external checkout is required.
    """
    override = os.environ.get("BOOKROOM_APP_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    try:
        from bookroom_sdk.config import BUNDLED_ENGINE_DIR
        if (BUNDLED_ENGINE_DIR / "book_pipeline.py").is_file():
            return BUNDLED_ENGINE_DIR.resolve()
    except Exception:  # noqa: BLE001 - fall through to the clear error below
        pass
    return BUNDLED_ENGINE_DIR_FALLBACK


BUNDLED_ENGINE_DIR_FALLBACK = Path(__file__).resolve().parent / "python" / "bookroom_sdk" / "_engine"

APP_ROOT = _default_engine_root()


def _emit(message: str) -> None:
    print(message, flush=True)


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the application's own summarization path.")
    parser.add_argument("source", help="Path to a .pdf or .epub book")
    parser.add_argument("--out", default="output")
    parser.add_argument("--slug", default=None)
    parser.add_argument("--no-review", action="store_true")
    parser.add_argument("--report-name", default="run-report.json")
    args = parser.parse_args()

    source = Path(args.source).expanduser()
    if not source.is_file():
        _emit(f"error: no such file: {source}")
        return 2
    if not (APP_ROOT / "book_pipeline.py").is_file():
        _emit(f"error: engine root not found: {APP_ROOT}")
        return 2

    # Make the bundled engine discoverable even when the SDK is not installed,
    # so `python run_baseline.py` works straight from a checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))

    # The engine reads its own .env at import time; give it the same one the
    # SDK project uses so both runs are configured identically.
    os.environ.setdefault("BOOKROOM_APP_ROOT", str(APP_ROOT))
    sys.path.insert(0, str(APP_ROOT))

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    load_dotenv(APP_ROOT / ".env", override=False)

    import book_pipeline
    import cost_estimation
    import claim_audit
    import gemini_provider
    import map_export
    import pdf_export
    import quality_gate
    import report_format
    import report_manifest
    from resumable_pipeline import generate_resumable_report

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # The engine writes artifacts to OUTPUT_DIR/<slug>, not to --out. Point it
    # at the requested directory so a baseline run is directly comparable with
    # an SDK run, which passes output_dir through the same variable.
    os.environ["OUTPUT_DIR"] = str(out_dir)

    # Honor the same endpoint overrides the SDK does, so a baseline run and an
    # SDK run can be pointed at exactly the same providers and compared fairly.
    if os.environ.get("BOOKROOM_LLM_BASE_URL"):
        gemini_provider.BASE_URL = os.environ["BOOKROOM_LLM_BASE_URL"].rstrip("/")
    if os.environ.get("BOOKROOM_JEV_BASE_URL"):
        book_pipeline.JEV_BASE_URL = os.environ["BOOKROOM_JEV_BASE_URL"].rstrip("/")
    if os.environ.get("BOOKROOM_LLM_MODEL"):
        gemini_provider.MODEL = os.environ["BOOKROOM_LLM_MODEL"]
    slug = args.slug or "".join(
        c if c.isalnum() or c in "._-" else "_" for c in source.stem).strip("._") or "book"
    run_options: dict[str, Any] = {"output_slug": slug, "language": "English",
                                    "digest_length": "standard", "book_type": "auto",
                                    "reading_level": "general"}

    started = time.time()
    run: dict[str, Any] = {
        "runner": "baseline (application code path, no SDK)",
        "source": str(source),
        "source_bytes": source.stat().st_size,
        "output_dir": str(out_dir),
        "app_root": str(APP_ROOT),
        "config": {
            "llm_model": gemini_provider.MODEL,
            "llm_endpoint": gemini_provider.BASE_URL,
            "jev_enabled": book_pipeline.JEV_ENABLED,
            "jev_model": book_pipeline.JEV_MODEL,
            "jev_endpoint": book_pipeline.JEV_BASE_URL,
            "score_threshold": book_pipeline.QUALITY_THRESHOLD,
            "max_revisions": book_pipeline.MAX_REVISIONS,
        },
        "stages": {},
    }
    _emit("=" * 66)
    _emit(f"baseline runner: application code path (no SDK)")
    _emit(f"app root : {APP_ROOT}")
    _emit(f"model    : {gemini_provider.MODEL}   review={book_pipeline.JEV_ENABLED} "
          f"({book_pipeline.JEV_MODEL})")
    _emit("=" * 66)

    if args.no_review:
        book_pipeline.JEV_ENABLED = False
        run["config"]["jev_enabled"] = False

    try:
        # --- 1. extract ----------------------------------------------------
        _emit("\n[1/5] extract")
        extracted = book_pipeline._extract(source, options=run_options)
        _emit(f"  sections: {len(extracted)}   "
              f"chars: {sum(len(s['source']) for s in extracted):,}")
        run["stages"]["extract"] = {
            "section_count": len(extracted),
            "total_characters": sum(len(s["source"]) for s in extracted),
            "titles": [s["title"] for s in extracted],
        }

        # --- 2. preflight --------------------------------------------------
        _emit("\n[2/5] preflight and budget")
        estimate = cost_estimation.estimate_usage(extracted)
        cost_estimation.enforce_budget(estimate)
        run["stages"]["preflight"] = estimate
        _emit(f"  batches           : {estimate.get('batch_count')}")
        _emit(f"  llm input tokens  : {estimate['gemini_input_tokens_estimate']:,}")
        _emit(f"  review credits    : {estimate['jev_credits_estimate_worst_case']:,}")

        gemini_provider.reset_usage()
        directory = Path(os.getenv("OUTPUT_DIR", "output")) / slug
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "preflight.json").write_text(
            json.dumps(estimate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # --- 3. generation -------------------------------------------------
        _emit("\n[3/5] generate_resumable_report")
        report_path = generate_resumable_report(str(source), options=run_options,
                                                progress=lambda m, **k: _emit(f"  ... {m}"))
        directory = report_path.parent
        markdown = report_path.read_text(encoding="utf-8")
        _emit(f"  markdown: {len(markdown):,} characters")

        # --- 4. quality gate -----------------------------------------------
        if book_pipeline.JEV_ENABLED:
            _emit("\n[4/5] evaluate_and_revise_report (16 categories)")
            records = quality_gate.evaluate_and_revise_report(report_path)
            latest = [r["attempts"][-1] for r in records if r.get("attempts")]
            passed = sum(1 for a in latest if a.get("passed"))
            _emit(f"  {passed}/{len(latest)} categories passed")
        else:
            _emit("\n[4/5] quality gate skipped (--no-review)")
        run["stages"]["report_path"] = str(report_path)

        # --- 5. exports ----------------------------------------------------
        _emit("\n[5/5] exports")
        markdown = report_path.read_text(encoding="utf-8")
        map_export.write_study_map(report_path)
        notes = report_path.with_name("chapter-notes.md")
        claims = claim_audit.audit_claims(markdown, notes.read_text(encoding="utf-8"))
        (directory / "claim-audit.json").write_text(
            json.dumps(claims, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pdf_export.create_pdf(report_path)
        usage_payload = {"gemini": gemini_provider.create_usage_report(),
                         "gemini_attempts": [gemini_provider.create_usage_report()],
                         "jev": {"requests_with_usage": 0, "reported_usage_totals": {}}}
        (directory / "usage.json").write_text(
            json.dumps(usage_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_manifest.write_manifest(report_path, source,
                                      jev_enabled=book_pipeline.JEV_ENABLED)
        run["stages"]["checks"] = {
            "format_problems": report_format.validate_report(markdown),
            "claim_count": claims.get("claim_count", 0),
            "llm_calls": usage_payload["gemini"].get("calls", 0),
            "llm_total_tokens": usage_payload["gemini"].get("total_tokens", 0),
        }

    except Exception as exc:  # noqa: BLE001 - record whatever happened
        run["error"] = f"{type(exc).__name__}: {exc}"
        _emit(f"\nFAILED: {type(exc).__name__}: {exc}")
        target = out_dir / args.report_name
        target.write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str) + "\n",
                          encoding="utf-8")
        return 1

    guide = directory / "study-guide.md"
    run["artifacts"] = [
        {"name": p.name, "bytes": p.stat().st_size, "exists": True,
         "sha256": _digest(p)}
        for p in sorted(directory.iterdir()) if p.is_file()
    ]
    run["elapsed_seconds"] = round(time.time() - started, 2)
    run["ok"] = True
    _emit("\nartifacts:")
    for row in run["artifacts"]:
        _emit(f"  {row['name']:<22} {row['bytes']:>9,} bytes")
    _emit(f"\ndone in {run['elapsed_seconds']}s")

    target = out_dir / args.report_name
    target.write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str) + "\n",
                      encoding="utf-8")
    _emit(f"run report: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
