"""JEv review: independent scoring, the 16-category quality gate, and revisions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from . import bootstrap, errors
from .config import Config
from .results import Review, guard


def _to_review(payload: dict[str, Any]) -> Review:
    scores = {key: value for key, value in (payload.get("scores") or {}).items()
              if isinstance(value, (int, float))}
    confidence = {key: value for key, value in (payload.get("confidence") or {}).items()
                  if isinstance(value, (int, float))}
    return Review(
        enabled=bool(payload.get("enabled")),
        passed=payload.get("passed"),
        scores=scores,
        confidence=confidence,
        focus=payload.get("focus"),
        model=payload.get("model"),
        usage=payload.get("usage") or {},
        raw=payload,
    )


class ReviewAPI:
    """Score summaries with JEv and drive bounded revisions.

    JEv is a structured decision model, not a generator: its scores are advisory
    signals about faithfulness, coverage, clarity and structure, not proof that a
    summary is correct.
    """

    def __init__(self, config: Config):
        self.config = config

    # ------------------------------------------------------------ single score
    @guard
    def evaluate(self, source_excerpt: str, summary: str) -> dict[str, Any]:
        """Score one summary against a bounded excerpt (faithfulness/coverage/clarity).

        Uses the application's standalone JEv adapter and returns its raw typed
        response. Keep excerpts small; do not send an entire book.
        """
        self.config.require_jev_key()
        if not source_excerpt.strip() or not summary.strip():
            raise errors.ValidationError("source_excerpt and summary must both be non-empty")
        jev = bootstrap.module("jev", self.config)
        return jev.evaluate_summary(source_excerpt, summary)

    @guard
    def evaluate_summary(self, source_excerpt: str, summary: str) -> dict[str, Any]:
        """Alias of :meth:`evaluate` matching the application's function name."""
        return self.evaluate(source_excerpt, summary)

    @guard
    def evaluate_section(self, title: str, source: str, draft: str) -> Review:
        """Score one candidate section using the four-dimension production rubric."""
        self.config.require_jev_key()
        pipeline = bootstrap.module("book_pipeline", self.config)
        return _to_review(pipeline._jev_evaluate(title, source, draft))

    # -------------------------------------------------------- the quality gate
    @guard
    def report_sections(self) -> list[dict[str, str]]:
        """The canonical 16 report categories, in order."""
        report_format = bootstrap.module("report_format", self.config)
        return [{"key": key, "heading": heading} for key, heading in report_format.REPORT_SECTIONS]

    @guard
    def review_report(
        self,
        report_path: str | os.PathLike[str],
        *,
        progress: Callable[..., None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_work_unit: Callable[[str, int], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Independently evaluate and revise every category of a finished report.

        Operates in place on ``study-guide.md`` beside ``chapter-notes.md`` and
        ``evaluations.json``; returns the per-category review records. A category
        that stays below threshold after its revision budget is retained with its
        history rather than hidden.
        """
        self.config.require_jev_key()
        path = Path(report_path).expanduser().resolve()
        if not path.is_file():
            raise errors.ValidationError(f"No report at {path}")
        notes = path.with_name("chapter-notes.md")
        if not notes.is_file():
            raise errors.ValidationError(
                f"{path.name} needs a sibling chapter-notes.md; it is the evidence JEv reviews against."
            )
        pipeline = bootstrap.module("book_pipeline", self.config)
        was_enabled = pipeline.JEV_ENABLED
        pipeline.JEV_ENABLED = True
        try:
            gate = bootstrap.module("quality_gate", self.config)
            return list(gate.evaluate_and_revise_report(
                path, progress=progress, should_cancel=should_cancel, on_work_unit=on_work_unit
            ))
        finally:
            pipeline.JEV_ENABLED = was_enabled

    @guard
    def evaluations(self, report_path: str | os.PathLike[str]) -> dict[str, Any]:
        """Read the stored evaluation history for a report."""
        import json
        path = Path(report_path).expanduser().resolve()
        target = path if path.suffix == ".json" else path.with_name("evaluations.json")
        if not target.is_file():
            return {}
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @guard
    def manifest(self, report_path: str | os.PathLike[str],
                 source_path: str | os.PathLike[str]) -> dict[str, Any]:
        """Write (and return) the reproducible, secret-free manifest."""
        import json
        report = Path(report_path).expanduser().resolve()
        source = Path(source_path).expanduser().resolve()
        if not report.is_file():
            raise errors.ValidationError(f"No report at {report}")
        if not source.is_file():
            raise errors.ValidationError(f"No source at {source}")
        manifest_module = bootstrap.module("report_manifest", self.config)
        written = manifest_module.write_manifest(report, source,
                                                jev_enabled=self.config.review_enabled)
        try:
            return json.loads(Path(written).read_text(encoding="utf-8"))
        except ValueError:
            return {}

    @guard
    def audit_claims(self, report_path: str | os.PathLike[str],
                    chapter_notes: str | os.PathLike[str] | None = None,
                    *, min_overlap: float = 0.18) -> dict[str, Any]:
        """Lexical evidence triage for the report's claims.

        Lexical overlap cannot prove a claim true; low-overlap claims are flagged
        for human review and never auto-rejected.
        """
        import json
        report = Path(report_path).expanduser().resolve()
        notes_path = Path(chapter_notes).expanduser().resolve() if chapter_notes \
            else report.with_name("chapter-notes.md")
        if not report.is_file():
            raise errors.ValidationError(f"No report at {report}")
        if not notes_path.is_file():
            raise errors.ValidationError(f"No chapter notes at {notes_path}")
        audit = bootstrap.module("claim_audit", self.config)
        return audit.audit_claims(report.read_text(encoding="utf-8"),
                                  notes_path.read_text(encoding="utf-8"),
                                  min_overlap=min_overlap)
