"""The Bookroom client: one object that exposes every wrapped capability."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import bootstrap, errors
from .config import Config, ConfigError, ExportSet, SummarizeOptions, discover_app_root
from .export import ExportAPI
from .extract import ExtractAPI
from .health import HealthAPI, TranslateAPI
from .results import Document, HealthReport, Preflight, Report, Review
from .review import ReviewAPI
from .summarize import SummarizeAPI

def _resolve_version() -> str:
    """Prefer installed package metadata, fall back to the source constant.

    A hard-coded string silently drifts from pyproject.toml the moment the
    version is bumped, so read the real one when the package is installed.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("bookroom-sdk")
    except Exception:  # noqa: BLE001 - not installed, or metadata unavailable
        return _FALLBACK_VERSION


_FALLBACK_VERSION = "2.0.0"
__version__ = _resolve_version()


class Bookroom:
    """Integrate every Book Summarizer capability into your own application.

    An integrator supplies **only the two API keys**::

        from bookroom_sdk import Bookroom

        room = Bookroom(llm_api_key="...", jev_api_key="...")

        result = room.summarize.study_guide("book.epub")
        print(result.markdown.path)
        print(result.pdf.path)

    Everything else - endpoints, models, thresholds, budgets, output directory -
    is defaulted and can still be overridden, or read from the environment with
    :meth:`from_env`.
    """

    def __init__(self, llm_api_key: str | None = None, jev_api_key: str | None = None, *,
                 llm_base_url: str | None = None,
                 llm_model: str | None = None,
                 jev_base_url: str | None = None,
                 jev_model: str | None = None,
                 app_root: str | os.PathLike[str] | None = None,
                 output_dir: str | os.PathLike[str] | None = None,
                 exports: ExportSet | dict[str, bool] | None = None,
                 **options: Any):
        config = Config(
            llm_api_key=llm_api_key,
            jev_api_key=jev_api_key,
            **({"llm_base_url": llm_base_url} if llm_base_url else {}),
            **({"llm_model": llm_model} if llm_model else {}),
            **({"jev_base_url": jev_base_url} if jev_base_url else {}),
            **({"jev_model": jev_model} if jev_model else {}),
            **({"app_root": Path(app_root)} if app_root else {}),
            **({"output_dir": Path(output_dir)} if output_dir else {}),
            **({"exports": ExportSet.parse(exports)} if exports is not None else {}),
            **options,
        )
        self.config = config

        self.extract_api = ExtractAPI(config)
        self.summarize_api = SummarizeAPI(config)
        self.review_api = ReviewAPI(config)
        self.export_api = ExportAPI(config)
        self.health_api = HealthAPI(config)
        self.translate_api = TranslateAPI(config)

    # ------------------------------------------------------------- namespaces
    @property
    def extract(self) -> ExtractAPI:
        """EPUB/PDF extraction: sections, locators, outline, OCR."""
        return self.extract_api

    @property
    def summarize(self) -> SummarizeAPI:
        """Chapter notes, digests, and complete study guides."""
        return self.summarize_api

    @property
    def review(self) -> ReviewAPI:
        """JEv scoring, the 16-category quality gate, and claim audits."""
        return self.review_api

    @property
    def export(self) -> ExportAPI:
        """Markdown, PDF, concept map, claims, manifest, usage."""
        return self.export_api

    @property
    def health(self) -> HealthAPI:
        """Credential and reachability checks."""
        return self.health_api

    @property
    def translate(self) -> TranslateAPI:
        """Translation and chapter classification on the alternate transport."""
        return self.translate_api

    # ------------------------------------------------------------ constructors
    @classmethod
    def from_env(cls, **overrides: Any) -> "Bookroom":
        """Build from ``BOOKROOM_*`` variables, then the application's own names."""
        config = Config.from_env(**overrides)
        return cls.__new__(cls)._with_config(config)

    @classmethod
    def _with_config(cls, config: Config) -> "Bookroom":
        instance = cls.__new__(cls)
        instance.config = config
        instance.extract_api = ExtractAPI(config)
        instance.summarize_api = SummarizeAPI(config)
        instance.review_api = ReviewAPI(config)
        instance.export_api = ExportAPI(config)
        instance.health_api = HealthAPI(config)
        instance.translate_api = TranslateAPI(config)
        return instance

    def with_options(self, **overrides: Any) -> "Bookroom":
        """A reconfigured copy; secrets are carried over."""
        from dataclasses import replace as dataclass_replace

        known = {f for f in self.config.__dataclass_fields__}
        unknown = set(overrides) - known
        if unknown:
            raise ConfigError(f"Unknown option(s): {', '.join(sorted(unknown))}")
        if "exports" in overrides:
            overrides["exports"] = ExportSet.parse(overrides["exports"])
        if "app_root" in overrides and overrides["app_root"] is not None:
            overrides["app_root"] = Path(overrides["app_root"])
        if "output_dir" in overrides and overrides["output_dir"] is not None:
            overrides["output_dir"] = Path(overrides["output_dir"])
        return Bookroom._with_config(dataclass_replace(self.config, **overrides))

    # ------------------------------------------------------------- operations
    def check(self) -> HealthReport:
        """Verify both credentials before spending anything."""
        return self.health_api.check()

    def describe(self) -> dict[str, Any]:
        """The active configuration, with no secrets in it."""
        return {
            "sdk_version": __version__,
            "config": self.config.describe(),
            "capabilities": sorted(_CAPABILITIES),
        }

    def load(self) -> Path:
        """Load the wrapped application now and return its root."""
        return bootstrap.load(self.config)

    @property
    def app_root(self) -> Path:
        return self.config.resolved_app_root

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (f"Bookroom(sdk={__version__}, llm_endpoint={self.config.llm_base_url}, "
                f"llm_model={self.config.llm_model!r}, review={'on' if self.config.review_enabled else 'off'})")


# The full capability surface, reported by describe() so an integrator can
# confirm coverage without reading the source.
_CAPABILITIES = (
    "extract.extract",
    "extract.extract_epub",
    "extract.extract_pdf",
    "extract.outline",
    "extract.ocr_languages",
    "extract.metadata",
    "summarize.preflight",
    "summarize.summarize_section",
    "summarize.summarize_sections",
    "summarize.summarize_text",
    "summarize.digest",
    "summarize.study_guide",
    "summarize.study_guide_simple",
    "review.evaluate",
    "review.evaluate_summary",
    "review.evaluate_section",
    "review.report_sections",
    "review.review_report",
    "review.evaluations",
    "review.manifest",
    "review.audit_claims",
    "export.pdf",
    "export.markdown",
    "export.write_markdown",
    "export.validate",
    "export.render_report",
    "export.concept_map",
    "export.graph_from_markdown",
    "export.claim_audit",
    "export.manifest",
    "export.usage",
    "export.artifacts",
    "export.merge_markdown",
    "health.check",
    "health.check_cached",
    "translate.translate",
    "translate.translate_batch",
    "translate.classify_chapters",
    "translate.extract_notes",
)
