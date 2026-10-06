"""Load the wrapped Book Summarizer application into this process.

The application is a flat tree of top-level modules (``book_pipeline``,
``gemini_provider``, ...) that import each other by bare name and read their
configuration from ``os.environ`` **at import time**. This module performs the
two things required to drive that tree safely from another program:

1. publish the SDK configuration into ``os.environ`` before anything is imported
   (``load_dotenv`` does not override existing variables, so this also wins over
   any stray ``.env`` file that happens to sit in the source tree), and
2. put the application root on ``sys.path``.

A few application constants are not environment-driven and are patched after
import - most importantly ``gemini_provider.BASE_URL``, which is the LLM
endpoint and is hardcoded in the application. Patching it is what lets an
integrator export and redirect the endpoint.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Callable, TypeVar

from .config import Config, ConfigError

T = TypeVar("T")

_LOCK = threading.RLock
_locks: dict[str, "threading.RLock"] = {}
_ENGINE_MODULES = ("book_pipeline", "gemini_provider", "quality_gate",
                   "resumable_pipeline", "pdf_extractor", "epub_extractor",
                   "report_format", "map_export", "claim_audit",
                   "cost_estimation", "report_manifest", "provider_health",
                   "jev", "epub_extractor", "pdf_export", "merge_markdowns",
                   "translate", "utils", "prompts")
_loaded_root: Path | None = None
_loaded_app_root: str | None = None
_loaded_fingerprint: str | None = None
_cache: dict[str, ModuleType] = {}


class AppLoadError(RuntimeError):
    """The wrapped application could not be imported."""


def _lock_for(key: str) -> "threading.RLock":
    with _LOCK():
        return _locks.setdefault(key, threading.RLock())


def _fingerprint(config: Config) -> str:
    """Identify a load by root plus the settings baked in at import time."""
    return "|".join(
        [
            str(config.resolved_app_root),
            config.llm_base_url,
            config.llm_model,
            config.jev_base_url,
            config.jev_model,
            str(config.review_enabled),
            str(config.output_dir),
        ]
    )


def _import(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - surfaced with actionable context
        raise AppLoadError(
            f"Could not import '{name}' from the Book Summarizer source tree. "
            "Install the application dependencies (uv sync) into the interpreter running the SDK. "
            f"Underlying error: {type(exc).__name__}: {exc}"
        ) from exc


def ensure_on_path(config: Config) -> Path:
    """Make the application root importable, ahead of anything else."""
    root = config.resolved_app_root
    if not root.is_dir():
        raise ConfigError(f"Application root {root} does not exist")
    if not (root / "book_pipeline.py").is_file():
        raise ConfigError(f"Application root {root} does not contain book_pipeline.py")
    text = str(root)
    if text in sys.path:
        sys.path.remove(text)
    sys.path.insert(0, text)
    return root


def apply_environment(config: Config) -> None:
    """Publish SDK configuration so the application's import-time reads see it."""
    for key, value in config.environment().items():
        os.environ[key] = value


def _patch_constants(config: Config) -> None:
    """Override application constants that are not read from the environment."""
    gemini = _import("gemini_provider")
    # The LLM endpoint. Hardcoded upstream; this is the SDK's exported override.
    gemini.BASE_URL = config.llm_base_url.rstrip("/")
    gemini.MODEL = config.llm_model
    gemini.API_KEY = config.llm_api_key or ""
    gemini.THINKING_LEVEL = str(config.thinking_level).lower()

    pipeline = _import("book_pipeline")
    # Review wiring, thresholds and the revision budget.
    pipeline.JEV_ENABLED = config.review_enabled
    pipeline.JEV_API_KEY = config.jev_api_key or ""
    pipeline.JEV_BASE_URL = config.jev_base_url.rstrip("/")
    pipeline.JEV_MODEL = config.jev_model
    pipeline.QUALITY_THRESHOLD = config.jev_score_threshold
    pipeline.CONFIDENCE_THRESHOLD = config.jev_confidence_threshold
    pipeline.MAX_REVISIONS = max(0, min(3, config.jev_max_revisions))

    extractor = _import("pdf_extractor")
    extractor.OCR_ENABLED = config.ocr_enabled
    extractor.OCR_LANGUAGE = config.ocr_language


def _app_root_of(config: Config) -> str:
    return str(config.resolved_app_root)


def load(config: Config, *, force: bool = False) -> Path:
    """Make ``config`` the engine's active configuration.

    Two cases, and the difference matters:

    * a different application root - the module set changes, so the modules are
      dropped and re-imported;
    * the same root but a different provider, model, key or review endpoint -
      the modules are already loaded, so their constants are simply re-patched.

    Without the second case, a second client in the same process would silently
    keep running against the first client's endpoint, because the engine reads
    its configuration into module-level constants.
    """
    global _loaded_root, _loaded_fingerprint, _loaded_app_root

    with _lock_for("bookroom.bootstrap"):
        fingerprint = _fingerprint(config)
        app_root = _app_root_of(config)
        if not force and fingerprint == _loaded_fingerprint and app_root == _loaded_app_root:
            return _loaded_root  # type: ignore[return-value]

        apply_environment(config)
        if force or _loaded_root is None or app_root != _loaded_app_root:
            root = ensure_on_path(config)
            # The engine reads os.environ at import time, so a different root
            # means a genuinely different module set: drop and re-import.
            for module_name in _ENGINE_MODULES:
                sys.modules.pop(module_name, None)
            _cache.clear()
        else:
            root = _loaded_root  # type: ignore[assignment]
        _patch_constants(config)
        _loaded_root = root
        _loaded_app_root = app_root
        _loaded_fingerprint = fingerprint
        return root  # type: ignore[return-value]


def module(name: str, config: Config) -> ModuleType:
    """Return an application module, loading the tree on first use."""
    load(config)
    with _lock_for(f"bookroom.module.{name}"):
        cached = _cache.get(name)
        if cached is not None:
            return cached
        loaded = _import(name)
        _cache[name] = loaded
        return loaded


def call(module_name: str, config: Config, function_name: str, *args, **kwargs):
    """Resolve ``module.function`` lazily and invoke it."""
    target = module(module_name, config)
    try:
        function: Callable[..., T] = getattr(target, function_name)
    except AttributeError as exc:
        raise AppLoadError(
            f"Book Summarizer module '{module_name}' has no attribute '{function_name}'. "
            "The wrapped application may have changed; check the SDK version against the app."
        ) from exc
    return function(*args, **kwargs)


def reset() -> None:
    """Forget the loaded tree (used by tests)."""
    global _loaded_root, _loaded_fingerprint, _loaded_app_root
    with _lock_for("bookroom.bootstrap"):
        _cache.clear()
        _loaded_root = None
        _loaded_fingerprint = None
        _loaded_app_root = None
