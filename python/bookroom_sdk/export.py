"""Exports: Markdown, PDF, concept map, claims, manifest, usage, and merging."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import bootstrap, errors
from .config import Config
from .results import Artifact, guard

_MEDIA = {
    "study-guide.md": "text/markdown",
    "chapter-notes.md": "text/markdown",
    "study-guide.pdf": "application/pdf",
    "study-maps.json": "application/json",
    "claim-audit.json": "application/json",
    "manifest.json": "application/json",
    "usage.json": "application/json",
    "preflight.json": "application/json",
    "evaluations.json": "application/json",
}


def _artifact(directory: Path, name: str) -> Artifact:
    target = directory / name
    return Artifact(name=name, path=str(target) if target.is_file() else None,
                    media_type=_MEDIA.get(name, "application/octet-stream"))


class ExportAPI:
    """Produce and package the generated study-guide artifacts."""

    def __init__(self, config: Config):
        self.config = config

    # ----------------------------------------------------------------- report
    @guard
    def pdf(self, report_path: str | os.PathLike[str],
            pdf_path: str | os.PathLike[str] | None = None) -> Artifact:
        """Render a validated study guide to a complete, Unicode PDF."""
        source = Path(report_path).expanduser().resolve()
        if not source.is_file():
            raise errors.ValidationError(f"No Markdown report at {source}")
        pdf_export = bootstrap.module("pdf_export", self.config)
        target = Path(pdf_path).expanduser().resolve() if pdf_path else source.with_suffix(".pdf")
        written = Path(pdf_export.create_pdf(source, target))
        return Artifact(name=written.name, path=str(written), media_type="application/pdf")

    @guard
    def markdown(self, report_path: str | os.PathLike[str]) -> str:
        """Read the canonical Markdown study guide as text."""
        source = Path(report_path).expanduser().resolve()
        if not source.is_file():
            raise errors.ValidationError(f"No report at {source}")
        return source.read_text(encoding="utf-8")

    @guard
    def write_markdown(self, report_path: str | os.PathLike[str],
                       destination: str | os.PathLike[str]) -> str:
        """Copy the study guide to another location as Markdown."""
        source = Path(report_path).expanduser().resolve()
        if not source.is_file():
            raise errors.ValidationError(f"No report at {source}")
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return str(target)

    @guard
    def validate(self, markdown: str | os.PathLike[str]) -> list[str]:
        """Run the application's deterministic layout checks; [] means valid."""
        report_format = bootstrap.module("report_format", self.config)
        if isinstance(markdown, (str, os.PathLike)):
            path = Path(markdown).expanduser().resolve()
            text = path.read_text(encoding="utf-8") if path.is_file() else str(markdown)
        else:  # pragma: no cover - defensive
            text = str(markdown)
        return list(report_format.validate_report(text))

    @guard
    def render_report(self, title: str, sections: dict[str, str], *, author: str = "Unknown author",
                      source_name: str = "Unknown source", model: str | None = None) -> str:
        """Render a complete study guide from already-generated section bodies."""
        report_format = bootstrap.module("report_format", self.config)
        return report_format.render_report(
            title, sections,
            author=author, source_name=source_name,
            model=model or self.config.llm_model,
        )

    # -------------------------------------------------------------- structured
    @guard
    def concept_map(self, report_path: str | os.PathLike[str]) -> dict[str, Any]:
        """Convert the report's Concept Map into a validated portable graph."""
        source = Path(report_path).expanduser().resolve()
        if not source.is_file():
            raise errors.ValidationError(f"No report at {source}")
        map_export = bootstrap.module("map_export", self.config)
        written = Path(map_export.write_study_map(source))
        try:
            return json.loads(written.read_text(encoding="utf-8"))
        except ValueError:
            return {}

    @guard
    def graph_from_markdown(self, markdown: str) -> dict[str, Any]:
        """Build a concept graph from arbitrary Markdown."""
        map_export = bootstrap.module("map_export", self.config)
        return map_export.markdown_to_graph(markdown)

    @guard
    def claim_audit(self, report_path: str | os.PathLike[str],
                    chapter_notes: str | os.PathLike[str] | None = None, *,
                    min_overlap: float = 0.18) -> dict[str, Any]:
        """Lexical evidence triage for the report's claims."""
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

    @guard
    def manifest(self, report_path: str | os.PathLike[str],
                 source_path: str | os.PathLike[str]) -> dict[str, Any]:
        """Write the reproducible, secret-free manifest beside a study guide."""
        report = Path(report_path).expanduser().resolve()
        source = Path(source_path).expanduser().resolve()
        if not report.is_file():
            raise errors.ValidationError(f"No report at {report}")
        if not source.is_file():
            raise errors.ValidationError(f"No source at {source}")
        manifest_module = bootstrap.module("report_manifest", self.config)
        written = manifest_module.write_manifest(report, source, jev_enabled=self.config.review_enabled)
        try:
            return json.loads(Path(written).read_text(encoding="utf-8"))
        except ValueError:
            return {}

    @guard
    def usage(self) -> dict[str, Any]:
        """Current in-process provider usage for this thread's run."""
        provider = bootstrap.module("gemini_provider", self.config)
        report = provider.create_usage_report()
        return dict(report) if isinstance(report, dict) else {}

    @guard
    def artifacts(self, report_path: str | os.PathLike[str]) -> list[Artifact]:
        """Every artifact that exists beside a study guide."""
        source = Path(report_path).expanduser().resolve()
        directory = source if source.is_dir() else source.parent
        return [_artifact(directory, name) for name in _MEDIA if (directory / name).is_file()]

    @guard
    def merge_markdown(self, folder: str | os.PathLike[str],
                       destination: str | os.PathLike[str] = "book.md") -> str:
        """Concatenate every .md file in a folder, in alphabetical order."""
        source = Path(folder).expanduser().resolve()
        if not source.is_dir():
            raise errors.ValidationError(f"Not a directory: {source}")
        target = Path(destination).expanduser().resolve()
        # The application writes the output file directly, so create the parent.
        target.parent.mkdir(parents=True, exist_ok=True)
        merge = bootstrap.module("merge_markdowns", self.config)
        merge.concat_md_files(str(source), str(target))
        return str(target)
