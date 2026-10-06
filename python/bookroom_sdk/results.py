"""Result objects returned by the SDK, plus the translation of application
exceptions into the SDK error hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import errors


@dataclass(frozen=True)
class Section:
    """One extracted unit of a book."""

    title: str
    text: str
    locator: str
    ocr_used: bool = False
    ocr_confidence: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "locator": self.locator,
            "word_count": len(self.text.split()),
            "characters": len(self.text),
            "ocr_used": self.ocr_used,
            "ocr_confidence": self.ocr_confidence,
        }


@dataclass(frozen=True)
class Document:
    """The extracted structure of a source book."""

    path: str
    kind: str                     # "pdf" | "epub"
    title: str
    sections: tuple[Section, ...]

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def total_words(self) -> int:
        return sum(len(section.text.split()) for section in self.sections)

    def as_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "kind": self.kind,
            "title": self.title,
            "section_count": self.section_count,
            "total_words": self.total_words,
            "sections": [section.as_dict() for section in self.sections],
        }
        if include_text:
            payload["sections"] = [
                {
                    "title": section.title,
                    "locator": section.locator,
                    "ocr_used": section.ocr_used,
                    "ocr_confidence": section.ocr_confidence,
                    "text": section.text,
                }
                for section in self.sections
            ]
        return payload


@dataclass(frozen=True)
class Preflight:
    """The application's own cost estimate and work-batch plan."""

    raw: dict[str, Any]

    @property
    def section_count(self) -> int:
        return int(self.raw.get("section_count", 0) or 0)

    @property
    def batch_count(self) -> int:
        return int(self.raw.get("batch_count", 0) or 0)

    @property
    def estimated_llm_input_tokens(self) -> int:
        return int(self.raw.get("gemini_input_tokens_estimate", 0) or 0)

    @property
    def estimated_jev_credits(self) -> int:
        return int(self.raw.get("jev_credits_estimate_worst_case", 0) or 0)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.raw)


@dataclass(frozen=True)
class Artifact:
    """A file produced by a run."""

    name: str
    path: str | None
    media_type: str

    def exists(self) -> bool:
        return bool(self.path) and Path(self.path).is_file()

    def read_bytes(self) -> bytes:
        if not self.path:
            raise FileNotFoundError(f"Artifact {self.name} has no local path")
        return Path(self.path).read_bytes()

    def read_text(self, encoding: str = "utf-8") -> str:
        if not self.path:
            raise FileNotFoundError(f"Artifact {self.name} has no local path")
        return Path(self.path).read_text(encoding=encoding)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "path": self.path, "media_type": self.media_type,
                "exists": self.exists()}


@dataclass(frozen=True)
class Report:
    """The result of a full study-guide run."""

    document: Document
    output_dir: str
    markdown: Artifact
    pdf: Artifact | None = None
    chapter_notes: Artifact | None = None
    concept_map: Artifact | None = None
    claim_audit: Artifact | None = None
    manifest: Artifact | None = None
    usage: Artifact | None = None
    preflight: Preflight | None = None
    evaluations: dict[str, Any] = field(default_factory=dict)
    quality: "QualitySummary | None" = None
    report_path: str | None = None

    @property
    def artifacts(self) -> tuple[Artifact, ...]:
        return tuple(
            artifact for artifact in (
                self.markdown, self.pdf, self.chapter_notes, self.concept_map,
                self.claim_audit, self.manifest, self.usage,
            ) if artifact is not None
        )

    def artifact(self, name: str) -> Artifact | None:
        for artifact in self.artifacts:
            if artifact.name == name:
                return artifact
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "document": self.document.as_dict(),
            "output_dir": self.output_dir,
            "report_path": self.report_path,
            "markdown": self.markdown.as_dict(),
            "pdf": self.pdf.as_dict() if self.pdf else None,
            "chapter_notes": self.chapter_notes.as_dict() if self.chapter_notes else None,
            "concept_map": self.concept_map.as_dict() if self.concept_map else None,
            "claim_audit": self.claim_audit.as_dict() if self.claim_audit else None,
            "manifest": self.manifest.as_dict() if self.manifest else None,
            "usage": self.usage.as_dict() if self.usage else None,
            "preflight": self.preflight.as_dict() if self.preflight else None,
            "evaluations": self.evaluations,
            "quality": self.quality.as_dict() if self.quality else None,
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True)
class QualitySummary:
    """Aggregate JEv outcome for a run."""

    enabled: bool
    threshold: float
    max_revisions: int
    categories_reviewed: int
    categories_passed: int
    categories_below_threshold: int
    revision_truncation_fallbacks: int = 0
    scores: dict[str, dict[str, float]] = field(default_factory=dict)
    focus: dict[str, str] = field(default_factory=dict)

    @property
    def all_passed(self) -> bool:
        return self.enabled and self.categories_reviewed > 0 and \
            self.categories_passed == self.categories_reviewed

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "threshold": self.threshold,
            "max_revisions": self.max_revisions,
            "categories_reviewed": self.categories_reviewed,
            "categories_passed": self.categories_passed,
            "categories_below_threshold": self.categories_below_threshold,
            "revision_truncation_fallbacks": self.revision_truncation_fallbacks,
            "all_passed": self.all_passed,
            "scores": self.scores,
            "focus": self.focus,
        }


@dataclass(frozen=True)
class Review:
    """A single JEv evaluation."""

    enabled: bool
    passed: bool | None
    scores: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    focus: str | None = None
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "passed": self.passed,
            "scores": self.scores,
            "confidence": self.confidence,
            "focus": self.focus,
            "model": self.model,
            "usage": self.usage,
        }


@dataclass(frozen=True)
class HealthReport:
    """Result of a provider credential check."""

    ok: bool
    llm: dict[str, Any]
    review: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "llm": self.llm, "review": self.review,
                "llm_provider": "llm", "review_provider": "jev"}


@dataclass(frozen=True)
class ProviderUsage:
    """Token accounting for one run."""

    calls: int = 0
    prompt_tokens: int = 0
    candidate_tokens: int = 0
    total_tokens: int = 0
    provider: str = ""
    model: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "model": self.model, "calls": self.calls,
            "prompt_tokens": self.prompt_tokens, "candidate_tokens": self.candidate_tokens,
            "total_tokens": self.total_tokens,
        }


# --------------------------------------------------------------------------- #
# Application exception translation
# --------------------------------------------------------------------------- #

def translate_exception(exc: BaseException) -> BaseException:
    """Map an application exception onto the SDK hierarchy.

    Imported lazily inside the function so this module has no import-time
    dependency on the wrapped application.
    """
    text = str(exc)

    if isinstance(exc, errors.BookroomError):
        return exc

    try:
        from .bootstrap import AppLoadError  # local import, avoids a cycle
    except Exception:  # pragma: no cover - defensive
        AppLoadError = errors.AppLoadError  # type: ignore[assignment]

    if isinstance(exc, AppLoadError):
        return exc

    name = type(exc).__name__
    lowered = text.lower()

    # Quota / rate limiting.
    if name == "GeminiAPIError":
        retry_after = getattr(exc, "retry_after_seconds", None)
        if retry_after or "quota" in lowered or "rate limit" in lowered:
            return errors.QuotaError(text, retry_after_seconds=retry_after, provider="llm")
        return errors.ProviderError(text, provider="llm")

    if "tesseract" in lowered or "ocr" in lowered:
        return errors.ExtractionError(f"{name}: {text}")

    if "only epub and pdf" in lowered or "only epub and pdf files are supported" in lowered:
        return errors.UnsupportedSourceError(f"{name}: {text}")

    if "token budget" in lowered or "batch cap" in lowered or "exceeds the configured per-batch" in lowered:
        return errors.BudgetExceededError(f"{name}: {text}")

    if "failed format validation" in lowered or "broke report formatting" in lowered \
            or "failed validation" in lowered:
        return errors.ValidationError(f"{name}: {text}")

    if "no extractable sections" in lowered or "no selectable text" in lowered \
            or "no table of contents" in lowered or "no sections met the minimum word count" in lowered:
        return errors.ExtractionError(f"{name}: {text}")

    if "set gemini_api_key" in lowered or "typesafe_api_key" in lowered \
            or "set llm_api_key" in lowered:
        return errors.ConfigError(f"{name}: {text}")

    if name in {"HTTPStatusError", "ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException"}:
        return errors.ProviderError(f"{name}: {text}", provider="llm")

    if "httpx" in name or "network" in lowered:
        return errors.ProviderError(f"{name}: {text}")

    return errors.JobError(f"{name}: {text}")


def guard(func):
    """Decorator translating application exceptions into SDK errors."""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise translate_exception(exc) from None

    return wrapper
