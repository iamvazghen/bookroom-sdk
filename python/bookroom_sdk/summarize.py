"""Summarization: chapter notes, the 16-section digest, and full study guides."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from . import bootstrap, errors
from .config import Config, SummarizeOptions
from .results import Document, Preflight, guard
from .extract import ExtractAPI, _require_supported

ProgressFn = Callable[..., None]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise errors.CancelledError("Run cancelled after saving completed work.")


class SummarizeAPI:
    """Produce study notes and complete study guides."""

    def __init__(self, config: Config):
        self.config = config
        self._extract = ExtractAPI(config)

    # ------------------------------------------------------------- primitives
    @guard
    def preflight(self, source: str | os.PathLike[str],
                  *, options: SummarizeOptions | dict[str, Any] | None = None) -> Preflight:
        """Estimate provider spend and the work-batch plan before spending anything.

        The application's own budget caps are enforced here, so an over-budget
        book fails here instead of partway through a paid run.
        """
        path = _require_supported(Path(source))
        prefs = SummarizeOptions.parse(options)
        document = self._extract.extract(path, options=prefs)
        estimation = bootstrap.module("cost_estimation", self.config)
        pipeline = bootstrap.module("book_pipeline", self.config)
        raw_sections = [
            {"title": section.title, "source": section.text, "locator": section.locator}
            for section in document.sections
        ]
        estimate = estimation.estimate_usage(raw_sections)
        estimation.enforce_budget(estimate)
        return Preflight(raw=estimate)

    @guard
    def summarize_section(self, section: dict[str, Any],
                          *, options: SummarizeOptions | dict[str, Any] | None = None) -> str:
        """Summarize one section, with JEv review and bounded revisions.

        ``section`` needs ``title``, ``source`` and ``locator``.
        """
        prefs = SummarizeOptions.parse(options)
        missing = [key for key in ("title", "source") if not section.get(key)]
        if missing:
            raise errors.ValidationError(f"section is missing required key(s): {', '.join(missing)}")
        payload = {
            "title": section.get("title"),
            "source": section.get("source"),
            "locator": section.get("locator", ""),
        }
        pipeline = bootstrap.module("book_pipeline", self.config)
        notes, _history = pipeline._summarize_section(payload, options=prefs.as_dict())
        return notes

    @guard
    def summarize_sections(self, source: str | os.PathLike[str],
                           *, options: SummarizeOptions | dict[str, Any] | None = None) -> dict[str, str]:
        """Summarize every extracted section; returns ``{title: notes}``."""
        prefs = SummarizeOptions.parse(options)
        document = self._extract.extract(source, options=prefs)
        pipeline = bootstrap.module("book_pipeline", self.config)
        notes: dict[str, str] = {}
        for section in document.sections:
            payload = {"title": section.title, "source": section.text, "locator": section.locator}
            text, _history = pipeline._summarize_section(payload, options=prefs.as_dict())
            notes[section.title] = text
        return notes

    @guard
    def summarize_text(self, text: str, *, title: str = "Untitled",
                       options: SummarizeOptions | dict[str, Any] | None = None) -> str:
        """Summarize raw text without a source file."""
        if not text or not text.strip():
            raise errors.ValidationError("text must not be empty")
        prefs = SummarizeOptions.parse(options)
        pipeline = bootstrap.module("book_pipeline", self.config)
        section = {"title": title, "source": text, "locator": ""}
        notes, _history = pipeline._summarize_section(section, options=prefs.as_dict())
        return notes

    @guard
    def digest(self, book_title: str, chapter_notes: str,
               *, options: SummarizeOptions | dict[str, Any] | None = None) -> str:
        """Build the digest body from existing chapter notes (no re-summarizing)."""
        if not chapter_notes.strip():
            raise errors.ValidationError("chapter_notes must not be empty")
        prefs = SummarizeOptions.parse(options)
        pipeline = bootstrap.module("book_pipeline", self.config)
        return pipeline._build_digest(book_title, chapter_notes, options=prefs.as_dict())

    # ------------------------------------------------------------- full guide
    @guard
    def study_guide(
        self,
        source: str | os.PathLike[str],
        *,
        options: SummarizeOptions | dict[str, Any] | None = None,
        output_dir: str | os.PathLike[str] | None = None,
        output_slug: str | None = None,
        progress: ProgressFn | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_work_unit: Callable[[str, int], None] | None = None,
        review: bool | None = None,
    ) -> Any:
        """Generate the complete checkpointed study guide.

        Every stage is saved as it completes, so an interrupted or quota-paused
        run resumes from the last finished section instead of starting over.

        Returns a :class:`~bookroom_sdk.results.Report`.
        """
        path = _require_supported(Path(source))
        self.config.require_llm_key()

        prefs = SummarizeOptions.parse(options)
        run_options = dict(prefs.as_dict())
        if output_slug:
            run_options["output_slug"] = output_slug

        provider = bootstrap.module("gemini_provider", self.config)
        provider.reset_usage()

        document = self._extract.extract(path, options=prefs)

        pipeline = bootstrap.module("book_pipeline", self.config)
        report_sections = len(pipeline.REPORT_SECTIONS)
        previous_review = pipeline.JEV_ENABLED
        if review is not None:
            pipeline.JEV_ENABLED = bool(review)
        try:
            # 1. Preflight: cost estimate and the sequential work-batch plan. The
            #    application's budget caps are enforced here, so an over-budget
            #    book fails before any paid call.
            estimation = bootstrap.module("cost_estimation", self.config)
            raw_sections = [{"title": s.title, "source": s.text, "locator": s.locator}
                            for s in document.sections]
            estimate = estimation.estimate_usage(raw_sections)
            estimation.enforce_budget(estimate)
            preflight = Preflight(raw=estimate)

            slug = output_slug or re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or "book"
            directory = Path(self.config.output_dir) / slug
            directory.mkdir(parents=True, exist_ok=True)
            if self.config.exports.preflight:
                (directory / "preflight.json").write_text(
                    json.dumps(estimate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            # 2. Checkpointed generation: chapter notes, then every digest section.
            resumable = bootstrap.module("resumable_pipeline", self.config)
            report_path = Path(resumable.generate_resumable_report(
                str(path),
                options=run_options,
                progress=progress,
                should_cancel=should_cancel,
                on_work_unit=on_work_unit,
            ))
            directory = report_path.parent

            _cancelled(should_cancel)

            # 3. Independent JEv review of every report category, with bounded
            #    revisions. Categories still below threshold are retained.
            if pipeline.JEV_ENABLED:
                gate = bootstrap.module("quality_gate", self.config)
                gate.evaluate_and_revise_report(
                    report_path, progress=progress, should_cancel=should_cancel,
                    on_work_unit=on_work_unit)
                _cancelled(should_cancel)

            markdown_text = report_path.read_text(encoding="utf-8")
            notes_path = report_path.with_name("chapter-notes.md")

            # 4. Structured exports.
            if self.config.exports.concept_map:
                map_export = bootstrap.module("map_export", self.config)
                map_export.write_study_map(report_path)
            if self.config.exports.claim_audit and notes_path.is_file():
                audit = bootstrap.module("claim_audit", self.config)
                (directory / "claim-audit.json").write_text(
                    json.dumps(audit.audit_claims(markdown_text,
                                                  notes_path.read_text(encoding="utf-8")),
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if self.config.exports.pdf:
                pdf_export = bootstrap.module("pdf_export", self.config)
                pdf_export.create_pdf(report_path)
            if self.config.exports.usage:
                self._write_usage(directory, provider, path)
            if self.config.exports.manifest:
                manifest_module = bootstrap.module("report_manifest", self.config)
                manifest_module.write_manifest(report_path, path,
                                               jev_enabled=pipeline.JEV_ENABLED)
        finally:
            if review is not None:
                pipeline.JEV_ENABLED = previous_review

        return self._collect(path, document, report_path, provider, preflight=preflight)

    # Also exposed as ``report`` for readability at call sites.
    report = study_guide

    @guard
    def study_guide_simple(self, source: str | os.PathLike[str],
                           *, progress: ProgressFn | None = None) -> Path:
        """The application's non-resumable entry point, for reference or parity checks."""
        path = _require_supported(Path(source))
        pipeline = bootstrap.module("book_pipeline", self.config)
        return Path(pipeline.generate_book_report(str(path), progress=progress))

    # ----------------------------------------------------------------- private
    @staticmethod
    def _write_usage(directory: Path, provider: Any, path: Path) -> None:
        """Persist provider usage, including credits already recorded in evaluations."""
        payload: dict[str, Any] = {
            "gemini": provider.create_usage_report(),
            "gemini_attempts": [provider.create_usage_report()],
            "jev": {"requests_with_usage": 0, "reported_usage_totals": {}},
        }
        requests, totals = 0, {}
        evaluation_file = directory / "evaluations.json"
        if evaluation_file.is_file():
            state = _read_json(evaluation_file)
            for record in (state.get("sections") or []) + (state.get("report_sections") or []):
                if not isinstance(record, dict):
                    continue
                for attempt in record.get("attempts", []) or []:
                    usage = attempt.get("usage") or {}
                    if not isinstance(usage, dict) or not usage:
                        continue
                    requests += 1
                    for key, value in usage.items():
                        if isinstance(value, (int, float)):
                            totals[key] = totals.get(key, 0) + value
            payload["jev"] = {"requests_with_usage": requests, "reported_usage_totals": totals}
        (directory / "usage.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _collect(self, path: Path, document: Document, report_path: Path, provider: Any,
                 preflight: Preflight | None = None) -> Any:
        """Assemble a Report from the files a run left on disk."""
        from .results import Artifact, QualitySummary, Report

        directory = report_path.parent
        exports = self.config.exports.as_dict()

        def artifact(name: str, media: str, enabled: bool) -> Artifact | None:
            if not enabled:
                return None
            target = directory / name
            return Artifact(name=name, path=str(target) if target.is_file() else None, media_type=media)

        evaluations = _read_json(directory / "evaluations.json")

        usage_artifact: Artifact | None = None
        if exports.get("usage"):
            usage_file = directory / "usage.json"
            usage_artifact = Artifact(
                name="usage.json",
                path=str(usage_file) if usage_file.is_file() else None,
                media_type="application/json",
            )

        quality: QualitySummary | None = None
        if evaluations:
            records = [record for record in evaluations.get("report_sections", []) if isinstance(record, dict)]
            latest = [record["attempts"][-1] for record in records if record.get("attempts")]
            scores = {
                record.get("section", "?"): {
                    key: value for key, value in (attempt.get("scores") or {}).items()
                    if isinstance(value, (int, float))
                }
                for record, attempt in zip(records, latest)
            }
            focus = {
                record.get("section", "?"): str(attempt.get("focus"))
                for record, attempt in zip(records, latest)
                if attempt.get("focus")
            }
            passed = sum(bool(attempt.get("passed")) for attempt in latest)
            quality = QualitySummary(
                enabled=bool(evaluations.get("enabled")),
                threshold=float(evaluations.get("threshold") or self.config.jev_score_threshold),
                max_revisions=int(evaluations.get("max_revisions") or self.config.jev_max_revisions),
                categories_reviewed=len(latest),
                categories_passed=passed,
                categories_below_threshold=max(0, len(latest) - passed),
                revision_truncation_fallbacks=int(evaluations.get("revision_truncation_fallbacks") or 0),
                scores=scores,
                focus=focus,
            )

        markdown_artifact = Artifact(name="study-guide.md", path=str(report_path),
                                     media_type="text/markdown")
        return Report(
            document=document,
            output_dir=str(directory),
            markdown=markdown_artifact,
            pdf=artifact("study-guide.pdf", "application/pdf", exports.get("pdf", True)),
            chapter_notes=artifact("chapter-notes.md", "text/markdown", exports.get("chapter_notes", True)),
            concept_map=artifact("study-maps.json", "application/json", exports.get("concept_map", True)),
            claim_audit=artifact("claim-audit.json", "application/json", exports.get("claim_audit", True)),
            manifest=artifact("manifest.json", "application/json", exports.get("manifest", True)),
            usage=usage_artifact,
            preflight=preflight,
            evaluations=evaluations,
            quality=quality,
            report_path=str(report_path),
        )
