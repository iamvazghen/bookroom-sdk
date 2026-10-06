"""Error types raised by the SDK.

The wrapped application raises its own exceptions; the SDK translates the ones
that matter into a stable hierarchy so callers can branch on failure kind
without importing application internals.
"""

from __future__ import annotations


class BookroomError(RuntimeError):
    """Base class for every SDK error."""


class ConfigError(BookroomError):
    """The SDK was not configured well enough to run."""


class AppLoadError(BookroomError):
    """The wrapped application could not be imported or lacks an expected symbol."""


class UnsupportedSourceError(BookroomError):
    """The file type is not supported (only EPUB and PDF are)."""


class ExtractionError(BookroomError):
    """Text could not be extracted from the source document."""


class ValidationError(BookroomError):
    """A generated artifact failed the application's deterministic checks."""


class ProviderError(BookroomError):
    """The LLM or JEv provider rejected a request or was unreachable."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None,
                 provider: str | None = None, status: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.provider = provider
        self.status = status


class QuotaError(ProviderError):
    """A provider quota window was hit; work is checkpointed and can resume."""


class BudgetExceededError(BookroomError):
    """The estimated provider spend exceeds the configured caps."""


class CancelledError(BookroomError):
    """A run was cancelled by the caller."""


class JobError(BookroomError):
    """A job failed. ``detail`` carries the redacted traceback when available."""


__all__ = [
    "BookroomError",
    "ConfigError",
    "AppLoadError",
    "UnsupportedSourceError",
    "ExtractionError",
    "ValidationError",
    "ProviderError",
    "QuotaError",
    "BudgetExceededError",
    "CancelledError",
    "JobError",
]
