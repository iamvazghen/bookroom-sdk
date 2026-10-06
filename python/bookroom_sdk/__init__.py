"""Bookroom SDK - every Book Summarizer capability, callable from your code.

    from bookroom_sdk import Bookroom

    room = Bookroom(llm_api_key="...", jev_api_key="...")
    report = room.summarize.study_guide("book.epub")
    print(report.markdown.path, report.pdf.path, report.quality.as_dict())
"""

from __future__ import annotations

from .client import Bookroom, __version__
from .config import Config, ConfigError, ExportSet, SummarizeOptions, discover_app_root
from .errors import (
    AppLoadError,
    BookroomError,
    BudgetExceededError,
    CancelledError,
    ExtractionError,
    JobError,
    ProviderError,
    QuotaError,
    UnsupportedSourceError,
    ValidationError,
)
from .results import (
    Artifact,
    Document,
    HealthReport,
    Preflight,
    ProviderUsage,
    QualitySummary,
    Report,
    Review,
    Section,
)

__all__ = [
    "Bookroom",
    "Config",
    "ConfigError",
    "ExportSet",
    "SummarizeOptions",
    "discover_app_root",
    "__version__",
    # results
    "Artifact",
    "Document",
    "HealthReport",
    "Preflight",
    "ProviderUsage",
    "QualitySummary",
    "Report",
    "Review",
    "Section",
    # errors
    "BookroomError",
    "AppLoadError",
    "BudgetExceededError",
    "CancelledError",
    "ExtractionError",
    "JobError",
    "ProviderError",
    "QuotaError",
    "UnsupportedSourceError",
    "ValidationError",
]
