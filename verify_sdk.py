"""End-to-end verification of the Bookroom SDK against the real application.

Runs the whole pipeline against genuine EPUB/PDF fixtures using a local mock
provider, then asserts on what actually landed on disk. Nothing here asserts
"it worked"; every check reads the produced artifact.

    python verify_sdk.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
# The package lives under python/, so a checkout run needs that on the path too.
sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))

from fixtures import build_epub, build_pdf          # noqa: E402
from mock_providers import MockProviders            # noqa: E402

from bookroom_sdk import Bookroom                    # noqa: E402
from bookroom_sdk import errors                      # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))
    return condition


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="bookroom-verify-"))
    print(f"workdir: {workdir}")

    try:
        epub = build_epub(workdir / "src" / "attention.epub")
        pdf = build_pdf(workdir / "src" / "attention.pdf")
        print(f"fixtures: epub={epub.stat().st_size}B pdf={pdf.stat().st_size}B")

        with MockProviders() as mock:
            room = Bookroom(
                llm_api_key="mock-llm-key",
                jev_api_key="mock-jev-key",
                llm_base_url=mock.llm_base_url,
                jev_base_url=mock.jev_base_url,
                output_dir=workdir / "output",
                min_word_count=200,
            )

            # ---------------------------------------------------------- describe
            section("configuration surface")
            described = room.describe()
            described_text = json.dumps(described)
            check("describe() leaks no secret values",
                  "mock-llm-key" not in described_text and "mock-jev-key" not in described_text)
            check("describe() exports the LLM endpoint",
                  described["config"]["llm_endpoint"] == mock.llm_base_url,
                  described["config"]["llm_endpoint"])
            check("describe() exports the review endpoint",
                  described["config"]["jev_endpoint"] == mock.jev_base_url)
            check("capability surface is non-trivial",
                  len(described["capabilities"]) >= 35,
                  f"{len(described['capabilities'])} capabilities")

            # ------------------------------------------------------------ health
            section("provider health")
            health = room.check()
            check("LLM credential accepted", health.llm.get("status") == "ok", str(health.llm))
            check("review credential accepted", health.review.get("status") == "ok", str(health.review))
            check("health.ok is true", health.ok)

            # ----------------------------------------------------------- extract
            section("extraction (EPUB)")
            document = room.extract.extract(epub)
            check("EPUB sections extracted", document.section_count == 4,
                  f"{document.section_count} sections")
            check("section text is non-empty", all(s.text for s in document.sections))
            check("locators present", all(s.locator for s in document.sections))
            check("word count is real", document.total_words > 800, f"{document.total_words} words")

            section("extraction (PDF)")
            pdf_doc = room.extract.extract_pdf(pdf)
            check("PDF sections extracted", pdf_doc.section_count >= 4,
                  f"{pdf_doc.section_count} sections")
            check("PDF locators are page ranges",
                  all("PDF pages" in s.locator for s in pdf_doc.sections))
            outline = room.extract.outline(pdf)
            check("PDF outline readable", len(outline) >= 4, f"{len(outline)} entries")
            meta = room.extract.metadata(pdf)
            check("PDF author metadata read",
                  meta.get("author") == "A. Fixture", str(meta.get("author")))

            section("extraction rejects unsupported input")
            bogus = workdir / "src" / "notes.txt"
            bogus.write_text("not a book", encoding="utf-8")
            try:
                room.extract.extract(bogus)
                check("unsupported type rejected", False, "no error raised")
            except errors.UnsupportedSourceError:
                check("unsupported type rejected", True)

            # --------------------------------------------------------- preflight
            section("preflight / budget")
            plan = room.summarize.preflight(epub)
            check("preflight counts sections", plan.section_count == 4, str(plan.section_count))
            check("preflight plans >=1 batch", plan.batch_count >= 1, f"{plan.batch_count} batches")
            check("preflight estimates tokens", plan.estimated_llm_input_tokens > 0,
                  f"{plan.estimated_llm_input_tokens} tokens")
            check("preflight estimates review credits", plan.estimated_jev_credits > 0,
                  f"{plan.estimated_jev_credits} credits")

            # ------------------------------------------------- single-section API
            section("single-section summarization")
            first = document.sections[0]
            notes = room.summarize.summarize_section(
                {"title": first.title, "source": first.text, "locator": first.locator})
            check("section summary produced", len(notes) > 40, f"{len(notes)} chars")

            section("raw-text summarization")
            text_notes = room.summarize.summarize_text(first.text[:4000], title="Raw text sample")
            check("text summary produced", len(text_notes) > 40, f"{len(text_notes)} chars")

            # -------------------------------------------------------- study guide
            section("full study guide (resumable pipeline)")
            events: list[str] = []
            report = room.summarize.study_guide(
                epub,
                progress=lambda message, **kw: events.append(str(message)),
                output_slug="attention",
            )
            check("progress callbacks fired", len(events) > 0, f"{len(events)} events")
            check("markdown artifact exists", report.markdown.exists(), report.markdown.path or "")
            check("pdf artifact exists", report.pdf is not None and report.pdf.exists(),
                  report.pdf.path if report.pdf else "missing")
            check("chapter notes exist",
                  report.chapter_notes is not None and report.chapter_notes.exists())
            check("concept map exists",
                  report.concept_map is not None and report.concept_map.exists())
            check("evaluations recorded", bool(report.evaluations),
                  f"{len(report.evaluations)} top-level keys")

            markdown_text = report.markdown.read_text()
            check("markdown is substantial", len(markdown_text) > 2000, f"{len(markdown_text)} chars")

            # --------------------------------------------------- format validation
            section("deterministic format validation")
            problems = room.export.validate(markdown_text)
            check("report passes format validation", problems == [], str(problems)[:120])
            report_format_sections = room.review.report_sections()
            check("16 canonical categories", len(report_format_sections) == 16,
                  f"{len(report_format_sections)}")
            missing = [s["heading"] for s in report_format_sections
                       if f"## {s['heading']}" not in markdown_text]
            check("all canonical headings present", not missing, str(missing))

            # ------------------------------------------------------- quality gate
            section("JEv quality gate (16 categories)")
            records = room.review.review_report(report.markdown.path)
            check("every category reviewed", len(records) == 16, f"{len(records)} records")
            passed_count = sum(
                1 for r in records
                if r.get("attempts") and r["attempts"][-1].get("passed")
            )
            check("categories passed threshold", passed_count == 16, f"{passed_count}/16")
            scored = [
                a.get("scores", {})
                for r in records if r.get("attempts") for a in r["attempts"][-1:]
            ]
            check("scores are numeric 0-4",
                  bool(scored) and all(
                      isinstance(v, (int, float)) for s in scored for v in s.values()
                  ))

            section("quality summary on the report object")
            quality = report.quality
            check("quality summary present", quality is not None)
            if quality:
                check("quality reports review enabled", quality.enabled)
                check("quality counts 16 categories", quality.categories_reviewed == 16,
                      f"{quality.categories_reviewed}")
                check("quality reports all passed", quality.all_passed)

            # ------------------------------------------------------------ exports
            section("exports")
            pdf_artifact = room.export.pdf(report.markdown.path)
            check("explicit PDF export succeeds", pdf_artifact.exists(),
                  f"{pdf_artifact.path} ({Path(pdf_artifact.path).stat().st_size}B)" if pdf_artifact.path else "")
            if pdf_artifact.exists():
                header = Path(pdf_artifact.path).read_bytes()[:5]
                check("PDF has a valid header", header == b"%PDF-", str(header))

            graph = room.export.concept_map(report.markdown.path)
            check("concept map is a graph", isinstance(graph, dict) and "nodes" in graph,
                  f"{len(graph.get('nodes', []))} nodes")
            check("concept map validates", isinstance(graph.get("edges"), list))

            claims = room.export.claim_audit(report.markdown.path)
            check("claim audit produced", claims.get("claim_count", 0) > 0,
                  f"{claims.get('claim_count')} claims")
            check("claim audit flags review items",
                  any(c.get("status") == "low_overlap_review" or
                      c.get("status") == "source_overlap_found" for c in claims.get("claims", [])))

            manifest = room.export.manifest(report.markdown.path, epub)
            check("manifest records the model", bool(manifest.get("generation_model")),
                  str(manifest.get("generation_model")))
            check("manifest records review state",
                  manifest.get("jev_evaluation_enabled") is True)
            check("manifest holds no secrets",
                  "mock-llm-key" not in json.dumps(manifest) and
                  "mock-jev-key" not in json.dumps(manifest))

            usage = room.export.usage()
            check("usage accounted for calls", int(usage.get("calls", 0)) > 0,
                  f"{usage.get('calls')} calls, {usage.get('total_tokens')} tokens")

            artifacts = room.export.artifacts(report.markdown.path)
            names = {a.name for a in artifacts}
            check("artifacts listed", "study-guide.md" in names, str(sorted(names)))

            merge_src = workdir / "merge-src"
            merge_src.mkdir(parents=True, exist_ok=True)
            (merge_src / "a.md").write_text("# A\n\nalpha content\n", encoding="utf-8")
            (merge_src / "b.md").write_text("# B\n\nbeta content\n", encoding="utf-8")
            merged = room.export.merge_markdown(merge_src, workdir / "merged" / "book.md")
            merged_text = Path(merged).read_text(encoding="utf-8")
            check("merge concatenates markdown", "alpha content" in merged_text and
                  "beta content" in merged_text, f"{len(merged_text)} chars")

            # ---------------------------------------------------- standalone JEv
            section("standalone JEv scoring")
            review = room.review.evaluate(
                "The source states that water freezes at zero degrees Celsius.",
                "The source says water freezes at zero degrees Celsius.",
            )
            check("standalone evaluation returns answers",
                  isinstance(review, dict) and "answers" in review, str(list(review)[:4]))

            sectioned = room.review.evaluate_section(
                "Thesis", first.text[:2000], notes)
            check("section review is typed",
                  sectioned.enabled and isinstance(sectioned.scores, dict) and bool(sectioned.scores),
                  str(sorted(sectioned.scores)))
            check("section review passes at threshold",
                  sectioned.passed is True)

            # ---------------------------------------------------------- resume
            section("checkpoint resume (second run reuses saved work)")
            llm_before = len([c for c in mock.calls if c["provider"] == "llm"])
            second = room.summarize.study_guide(epub, output_slug="attention")
            llm_after = len([c for c in mock.calls if c["provider"] == "llm"])
            check("resume issued no new chapter calls", llm_after == llm_before,
                  f"{llm_before} -> {llm_after}")
            check("resume returned the same report",
                  second.markdown.path == report.markdown.path)

            section("review can be disabled per run")
            no_review = room.with_options(output_dir=workdir / "output2")
            report2 = no_review.summarize.study_guide(epub, output_slug="no-review", review=False)
            check("run without review still produces markdown",
                  report2.markdown.exists(), report2.markdown.path or "")
            check("run without review records review off",
                  bool(report2.evaluations) and report2.evaluations.get("enabled") is False)

            # ------------------------------------------------------ translation
            section("alternate transport (Ollama-compatible)")
            alternate = room.with_options(legacy_base_url=f"http://127.0.0.1:{mock.port}",
                                         legacy_model="mock-model")
            described_alt = alternate.translate.describe()
            check("alternate transport endpoint is exported",
                  described_alt["endpoint"] == f"http://127.0.0.1:{mock.port}",
                  described_alt["endpoint"])
            translated = alternate.translate.translate("A paragraph of English prose to translate.",
                                                       "Spanish")
            check("translation produced text", isinstance(translated, str) and len(translated) > 20,
                  f"{len(translated)} chars")
            batch = alternate.translate.translate_batch(["first item", "second item"], "French")
            check("batch translation returns one result per input",
                  isinstance(batch, list) and len(batch) == 2, f"{len(batch)} results")
            notes_alt = alternate.translate.extract_notes(["chapter body " * 40])
            check("legacy multi-node notes produced",
                  isinstance(notes_alt, list) and bool(notes_alt[0]), f"{len(notes_alt[0])} chars")
            check("alternate transport actually called the provider",
                  any(c["provider"] == "ollama" for c in mock.calls))

            # --------------------------------------------------------- key guards
            section("missing-credential guards")
            try:
                Bookroom(llm_api_key=None).summarize.study_guide(epub)
                check("missing LLM key rejected", False, "no error raised")
            except errors.ConfigError:
                check("missing LLM key rejected", True)
            try:
                no_review_key = Bookroom(llm_api_key="k", jev_api_key=None)
                no_review_key.review.evaluate("source", "summary")
                check("missing review key rejected", False, "no error raised")
            except errors.ConfigError:
                check("missing review key rejected", True)

            llm_calls = len([c for c in mock.calls if c["provider"] == "llm"])
            jev_calls = len([c for c in mock.calls if c["provider"] == "jev"])
            check("LLM provider actually exercised", llm_calls > 20, f"{llm_calls} calls")
            check("review provider actually exercised", jev_calls >= 16, f"{jev_calls} calls")
            check("provider auth headers were sent",
                  all(c["auth"] for c in mock.calls), "every call carried credentials")

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n" + "=" * 62)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All SDK checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
