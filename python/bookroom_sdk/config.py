"""Configuration for the Bookroom SDK.

Design rule: an integrator supplies **only credentials**. Every endpoint, model,
threshold, and directory has a working default here and can still be overridden.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from .errors import ConfigError

__all__ = [
    "Config", "ConfigError", "ExportSet", "SummarizeOptions",
    "discover_app_root", "DEFAULT_LLM_BASE_URL", "DEFAULT_LLM_MODEL",
    "DEFAULT_JEV_BASE_URL", "DEFAULT_JEV_MODEL",
]

# Defaults lifted from the application so the SDK behaves identically out of the box.
DEFAULT_LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_LLM_MODEL = "gemini-3.8-flash"
DEFAULT_JEV_BASE_URL = "https://api.typesafe.ai/v1"
DEFAULT_JEV_MODEL = "jev-latest"

# Where the application source lives when the caller does not say. Built
# defensively: a shallow install layout has fewer parents than this list
# assumes, and indexing past the end raises IndexError at import time.
def _app_root_candidates() -> tuple[Path, ...]:
    parents = Path(__file__).resolve().parents
    candidates: list[Path] = []
    if len(parents) > 4:
        candidates.append(parents[4] / "src")
    for depth in (3, 2, 1):
        if len(parents) > depth:
            candidates.append(parents[depth])
    candidates.append(parents[0])
    return tuple(candidates)


_APP_ROOT_CANDIDATES = _app_root_candidates()

ENV_PREFIX = "BOOKROOM_"


def _as_bool(value: Any, *, default: bool | None = None) -> bool:
    if value is None:
        if default is None:
            raise ConfigError("Expected a boolean value but received None")
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Expected a boolean value but received {value!r}")


def _as_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Expected an integer but received {value!r}") from exc


def _as_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Expected a number but received {value!r}") from exc


def discover_app_root() -> Path:
    """Locate the Book Summarizer source tree that the SDK wraps."""
    override = os.getenv(ENV_PREFIX + "APP_ROOT") or os.getenv("BOOKROOM_APP_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if not (root / "book_pipeline.py").is_file():
            raise ConfigError(
                f"BOOKROOM_APP_ROOT={root} does not contain book_pipeline.py; "
                "point it at the application source root."
            )
        return root

    env_dir = os.getenv(ENV_PREFIX + "SRC")
    if env_dir:
        root = Path(env_dir).expanduser().resolve()
        if (root / "book_pipeline.py").is_file():
            return root

    for candidate in _APP_ROOT_CANDIDATES:
        if (candidate / "book_pipeline.py").is_file():
            return candidate.resolve()

    # Walk up from this file and also consider a sibling or child "src" folder,
    # so the SDK keeps working when installed elsewhere in a checkout.
    for parent in Path(__file__).resolve().parents:
        for option in (parent, parent / "src", parent / "app"):
            if (option / "book_pipeline.py").is_file():
                return option.resolve()

    raise ConfigError(
        "Could not locate the Book Summarizer source tree (the directory that "
        "contains book_pipeline.py). Fix it in one of these ways:\n"
        "  - pass app_root=/path/to/summarizer/src to Bookroom(...)\n"
        "  - set BOOKROOM_APP_ROOT=/path/to/summarizer/src in the environment\n"
        "  - or add BOOKROOM_APP_ROOT=... to a .env file next to your script\n"
        f"Searched: {', '.join(str(path) for path in _APP_ROOT_CANDIDATES)}"
    )


def parse_env_file(path: Path) -> dict[str, str]:
    """Read a ``.env`` file into a dict. Handles quotes, comments and ``export``."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            # Strip a trailing unquoted comment.
            hash_index = value.find(" #")
            if hash_index != -1:
                value = value[:hash_index].rstrip()
        values[key] = value
    return values


def load_env_files(environ: dict[str, str] | None = None,
                   app_root: str | Path | None = None) -> list[str]:
    """Merge ``.env`` files into the process environment without overriding it.

    The wrapped application loads its own ``.env`` at import time, so the SDK
    must see the same values or it would report "not configured" for a setup that
    actually works. Precedence, strongest first:

    1. the real process environment (never overridden),
    2. ``.env`` in the current working directory,
    3. ``.env`` in the application root.

    Returns the list of files that were actually read.
    """
    target = os.environ if environ is None else environ
    candidates: list[Path] = []
    try:
        candidates.append(Path.cwd() / ".env")
    except OSError:  # pragma: no cover - unreadable cwd
        pass
    # An explicit app_root wins over the environment variable: the caller told us
    # where the engine is, so that is the .env that governs it.
    hint = app_root or target.get(ENV_PREFIX + "APP_ROOT") or target.get(ENV_PREFIX + "SRC")
    if hint:
        candidates.append(Path(hint).expanduser() / ".env")
    if not hint:
        try:
            candidates.append(discover_app_root() / ".env")
        except ConfigError:
            pass

    seen: set[Path] = set()
    read: list[str] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:  # pragma: no cover - defensive
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        read.append(str(resolved))
        for key, value in parse_env_file(resolved).items():
            target.setdefault(key, value)
    return read


@dataclass(frozen=True)
class ExportSet:
    """Which artifacts a run should produce."""

    markdown: bool = True
    pdf: bool = True
    chapter_notes: bool = True
    concept_map: bool = True
    claim_audit: bool = True
    manifest: bool = True
    usage: bool = True
    preflight: bool = True
    evaluations: bool = True

    def as_dict(self) -> dict[str, bool]:
        return {
            "markdown": self.markdown,
            "pdf": self.pdf,
            "chapter_notes": self.chapter_notes,
            "concept_map": self.concept_map,
            "claim_audit": self.claim_audit,
            "manifest": self.manifest,
            "usage": self.usage,
            "preflight": self.preflight,
            "evaluations": self.evaluations,
        }

    @classmethod
    def parse(cls, value: "ExportSet | Mapping[str, bool] | None") -> "ExportSet":
        if value is None:
            return cls()
        if isinstance(value, ExportSet):
            return value
        if isinstance(value, Mapping):
            defaults = cls()
            allowed = set(defaults.as_dict())
            unknown = set(value) - allowed
            if unknown:
                raise ConfigError(f"Unknown export option(s): {', '.join(sorted(unknown))}")
            resolved = {
                key: _as_bool(flag, default=getattr(defaults, key))
                for key, flag in value.items()
            }
            return cls(**resolved)
        raise ConfigError(f"Cannot interpret exports={value!r}")


@dataclass(frozen=True)
class SummarizeOptions:
    """Reader-facing preferences forwarded to the application's prompt builder."""

    language: str = "English"
    reading_level: str = "general"
    digest_length: str = "standard"          # brief | standard | deep
    book_type: str = "auto"
    ocr_enabled: bool = False
    ocr_language: str = "eng"

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "reading_level": self.reading_level,
            "digest_length": self.digest_length,
            "book_type": self.book_type,
            "ocr_enabled": self.ocr_enabled,
            "ocr_language": self.ocr_language,
        }

    @classmethod
    def parse(cls, value: "SummarizeOptions | Mapping[str, Any] | None") -> "SummarizeOptions":
        if value is None:
            return cls()
        if isinstance(value, SummarizeOptions):
            return value
        if isinstance(value, Mapping):
            defaults = cls()
            unknown = set(value) - set(defaults.as_dict())
            if unknown:
                raise ConfigError(f"Unknown summarize option(s): {', '.join(sorted(unknown))}")
            data: dict[str, Any] = {}
            for key, raw in value.items():
                if key == "ocr_enabled":
                    data[key] = _as_bool(raw, default=defaults.ocr_enabled)
                else:
                    data[key] = raw
            return cls(**data)
        raise ConfigError(f"Cannot interpret options={value!r}")


@dataclass(frozen=True)
class Config:
    """Full SDK configuration.

    ``llm_api_key`` and ``jev_api_key`` are the only secrets an integrator must
    supply. Everything else is defaulted, and the endpoints are exported so a
    caller can point the SDK at a proxy, Ollama, OpenRouter, or a self-hosted
    Jev-compatible service.
    """

    llm_api_key: str | None = None
    jev_api_key: str | None = None

    # --- exported endpoints -------------------------------------------------
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    jev_base_url: str = DEFAULT_JEV_BASE_URL
    jev_model: str = DEFAULT_JEV_MODEL

    # --- review behaviour ---------------------------------------------------
    jev_enabled: bool | None = None          # None -> on when a JEv key exists
    jev_max_revisions: int = 2               # application clamps to 0..3
    jev_score_threshold: float = 3.5
    jev_confidence_threshold: float = 0.55

    # --- generation behaviour ----------------------------------------------
    thinking_level: str = "low"
    max_retries: int = 5
    max_actual_llm_tokens: int = 2_000_000
    min_word_count: int = 200

    # --- budget caps (applied per work batch) ------------------------------
    max_estimated_llm_input_tokens: int = 1_500_000
    max_estimated_jev_credits: int = 12_000

    # --- legacy / alternate LLM transport (Ollama, OpenRouter) -------------
    legacy_base_url: str = "http://localhost:11434"
    legacy_model: str | None = None
    legacy_concurrency: int = 6

    # --- OCR ----------------------------------------------------------------
    ocr_enabled: bool = False
    ocr_language: str = "eng"
    tesseract_cmd: str | None = None

    # --- filesystem ---------------------------------------------------------
    app_root: Path | None = None
    output_dir: Path = Path("output")
    working_dir: Path | None = None

    # --- SDK behaviour ------------------------------------------------------
    timeout_seconds: float = 120.0
    exports: ExportSet = field(default_factory=ExportSet)
    extra_env: Mapping[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ utils
    @property
    def resolved_app_root(self) -> Path:
        return discover_app_root() if self.app_root is None else Path(self.app_root).expanduser().resolve()

    @property
    def review_enabled(self) -> bool:
        """Review runs automatically whenever a JEv key is present."""
        if self.jev_enabled is not None:
            return self.jev_enabled
        return bool(self.jev_api_key)

    def require_llm_key(self) -> str:
        if not self.llm_api_key:
            raise ConfigError(
                "llm_api_key is required for generation. Pass llm_api_key=... to Bookroom(...) "
                "or set BOOKROOM_LLM_API_KEY (GEMINI_API_KEY is also read)."
            )
        return self.llm_api_key

    def require_jev_key(self) -> str:
        if not self.jev_api_key:
            raise ConfigError(
                "jev_api_key is required for review. Pass jev_api_key=... to Bookroom(...) "
                "or set BOOKROOM_JEV_API_KEY (TYPESAFE_API_KEY is also read)."
            )
        return self.jev_api_key

    def with_overrides(self, **kwargs: Any) -> "Config":
        return replace(self, **kwargs)

    def describe(self) -> dict[str, Any]:
        """A secret-free view of the active configuration, safe to log or return over HTTP."""
        return {
            "llm_endpoint": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_api_key_set": bool(self.llm_api_key),
            "jev_endpoint": self.jev_base_url,
            "jev_model": self.jev_model,
            "jev_api_key_set": bool(self.jev_api_key),
            "jev_enabled": self.review_enabled,
            "jev_score_threshold": self.jev_score_threshold,
            "jev_confidence_threshold": self.jev_confidence_threshold,
            "jev_max_revisions": self.jev_max_revisions,
            "thinking_level": self.thinking_level,
            "legacy_llm_endpoint": self.legacy_base_url,
            "legacy_llm_model": self.legacy_model,
            "legacy_concurrency": self.legacy_concurrency,
            "max_actual_llm_tokens": self.max_actual_llm_tokens,
            "max_estimated_llm_input_tokens": self.max_estimated_llm_input_tokens,
            "max_estimated_jev_credits": self.max_estimated_jev_credits,
            "min_word_count": self.min_word_count,
            "ocr_enabled": self.ocr_enabled,
            "ocr_language": self.ocr_language,
            "output_dir": str(self.output_dir),
            "app_root": str(self.resolved_app_root),
            "exports": self.exports.as_dict(),
        }

    def environment(self) -> dict[str, str]:
        """The exact environment the wrapped application will read.

        Set before the application modules are imported: they read configuration
        at import time. ``load_dotenv`` does not override existing variables, so
        these values win over any stray ``.env`` file in the source tree.
        """
        review = self.review_enabled
        env: dict[str, str] = {
            # Generation
            "GEMINI_API_KEY": self.llm_api_key or "",
            "GEMINI_MODEL": self.llm_model,
            "GEMINI_ENABLED": "true" if self.llm_api_key else "false",
            "GEMINI_THINKING_LEVEL": self.thinking_level,
            "GEMINI_MAX_RETRIES": str(self.max_retries),
            "MAX_ACTUAL_GEMINI_TOKENS": str(self.max_actual_llm_tokens),
            # Review
            "JEV_ENABLED": "true" if review else "false",
            "TYPESAFE_API_KEY": self.jev_api_key or "",
            "JEV_BASE_URL": self.jev_base_url.rstrip("/"),
            "JEV_MODEL": self.jev_model,
            "JEV_MAX_REVISIONS": str(max(0, min(3, self.jev_max_revisions))),
            "JEV_SCORE_THRESHOLD": str(self.jev_score_threshold),
            "JEV_CONFIDENCE_THRESHOLD": str(self.jev_confidence_threshold),
            # Budget
            "MAX_ESTIMATED_GEMINI_INPUT_TOKENS": str(self.max_estimated_llm_input_tokens),
            "MAX_ESTIMATED_JEV_CREDITS": str(self.max_estimated_jev_credits),
            # Extraction
            "MIN_WORD_COUNT": str(self.min_word_count),
            "OCR_ENABLED": "true" if self.ocr_enabled else "false",
            "OCR_LANGUAGE": self.ocr_language,
            # Filesystem
            "OUTPUT_DIR": str(self.output_dir),
            # Legacy / alternate transport
            "LLM_BASE_URL": self.legacy_base_url,
            "LLM_API_KEY": self.llm_api_key or "",
            "REMOTE_CONCURRENCY": str(self.legacy_concurrency),
        }
        if self.legacy_model:
            env["LLM_MODEL"] = self.legacy_model
        if self.tesseract_cmd:
            env["TESSERACT_CMD"] = self.tesseract_cmd
        for key, value in self.extra_env.items():
            env[str(key)] = str(value)
        return env

    # ------------------------------------------------------------- constructors
    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, *,
                 use_env_files: bool = True,
                 **overrides: Any) -> "Config":
        """Build a config from environment variables, with SDK overrides winning.

        ``.env`` files are merged in first (see :func:`load_env_files`) so a setup
        that works for the application also works for the SDK. Reads
        ``BOOKROOM_*`` first, then the application's native names
        (``GEMINI_API_KEY``, ``TYPESAFE_API_KEY``, ...).
        """
        if use_env_files and environ is None:
            load_env_files(app_root=overrides.get("app_root"))
        source: Mapping[str, str] = os.environ if environ is None else environ

        def get(*names: str, default: str = "") -> str:
            for name in names:
                value = source.get(name)
                if value:
                    return value
            return default

        data: dict[str, Any] = {
            "llm_api_key": get("BOOKROOM_LLM_API_KEY", "GEMINI_API_KEY") or None,
            "jev_api_key": get("BOOKROOM_JEV_API_KEY", "TYPESAFE_API_KEY") or None,
            "llm_base_url": get("BOOKROOM_LLM_BASE_URL", default=DEFAULT_LLM_BASE_URL) or DEFAULT_LLM_BASE_URL,
            # Mirrors gemini_provider: GEMINI_MODEL, then LLM_MODEL, then default.
            "llm_model": get("BOOKROOM_LLM_MODEL", "GEMINI_MODEL", "LLM_MODEL",
                             default=DEFAULT_LLM_MODEL) or DEFAULT_LLM_MODEL,
            "jev_base_url": get("BOOKROOM_JEV_BASE_URL", default=DEFAULT_JEV_BASE_URL) or DEFAULT_JEV_BASE_URL,
            "jev_model": get("BOOKROOM_JEV_MODEL", default=DEFAULT_JEV_MODEL) or DEFAULT_JEV_MODEL,
            "jev_max_revisions": _as_int(get("BOOKROOM_JEV_MAX_REVISIONS", "JEV_MAX_REVISIONS"), 2),
            "jev_score_threshold": _as_float(get("BOOKROOM_JEV_SCORE_THRESHOLD", "JEV_SCORE_THRESHOLD"), 3.5),
            "jev_confidence_threshold": _as_float(
                get("BOOKROOM_JEV_CONFIDENCE_THRESHOLD", "JEV_CONFIDENCE_THRESHOLD"), 0.55
            ),
            "thinking_level": get("BOOKROOM_THINKING_LEVEL", "GEMINI_THINKING_LEVEL", default="low") or "low",
            "min_word_count": _as_int(get("BOOKROOM_MIN_WORD_COUNT", "MIN_WORD_COUNT"), 200),
            "legacy_base_url": get("BOOKROOM_LEGACY_BASE_URL", "LLM_BASE_URL", default="http://localhost:11434")
            or "http://localhost:11434",
            "legacy_model": get("BOOKROOM_LEGACY_MODEL", "LLM_MODEL") or None,
            "legacy_concurrency": _as_int(get("BOOKROOM_LEGACY_CONCURRENCY", "REMOTE_CONCURRENCY"), 6),
            "ocr_language": get("BOOKROOM_OCR_LANGUAGE", "OCR_LANGUAGE", default="eng") or "eng",
            "tesseract_cmd": get("BOOKROOM_TESSERACT_CMD", "TESSERACT_CMD") or None,
            "output_dir": Path(get("BOOKROOM_OUTPUT_DIR", "OUTPUT_DIR", default="output") or "output"),
        }
        jev_flag = get("BOOKROOM_JEV_ENABLED", "JEV_ENABLED")
        data["jev_enabled"] = _as_bool(jev_flag) if jev_flag else None
        ocr_flag = get("BOOKROOM_OCR_ENABLED", "OCR_ENABLED")
        data["ocr_enabled"] = _as_bool(ocr_flag) if ocr_flag else False
        app_root = get("BOOKROOM_APP_ROOT", "BOOKROOM_SRC")
        if app_root:
            data["app_root"] = Path(app_root)
        data.update(overrides)
        return cls(**data)
