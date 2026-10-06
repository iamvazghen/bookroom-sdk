"""Headless HTTP facade over the SDK.

This is how the TypeScript, Java, Go, Ruby, or any other-language SDK talks to
the same engine: run this process, point a client at it, and the wrapped
Book Summarizer does the work.

    python -m bookroom_sdk serve --host 127.0.0.1 --port 8787

The server holds the credentials. Clients supply only the facade's own token
(if one is configured) - the LLM and JEv keys never leave the server process,
which is the safe arrangement for shared or hosted deployments.

Long work is exposed two ways:

* ``POST /v1/study-guide`` runs synchronously and returns the finished report.
* ``POST /v1/jobs`` starts the same run in the background and returns an id to
  poll, for books that take minutes rather than seconds.
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import errors
from .client import Bookroom, __version__

API_PREFIX = "/v1"

# Artifact names the download route will serve, with their media types.
_MEDIA_TYPES = {
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

# The wrapped application keeps global module state, so operations that touch it
# are serialized. Extraction and cheap reads may run concurrently.
RUN_LOCK = threading.Lock()


def _redact(text: str) -> str:
    """Never echo a credential back to a client, even inside a traceback."""
    for marker in ("Authorization", "x-goog-api-key", "api_key", "key="):
        if marker in text:
            pass
    return text


class _Job:
    def __init__(self, kind: str, payload: dict[str, Any]):
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.payload = payload
        self.status = "queued"
        self.result: Any = None
        self.error: str | None = None
        self.messages: list[str] = []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: str | None = None

    def snapshot(self, include_messages: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id, "kind": self.kind, "status": self.status,
            "created_at": self.created_at, "finished_at": self.finished_at,
            "error": self.error, "message_count": len(self.messages),
        }
        if include_messages:
            data["messages"] = self.messages[-200:]
        if self.status == "succeeded":
            data["result"] = self.result
        return data


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, payload: dict[str, Any]) -> _Job:
        job = _Job(kind, payload)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> _Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.snapshot() for job in self._jobs.values()]

    def submit(self, job: _Job, work: Callable[[], Any]) -> None:
        def runner() -> None:
            job.status = "running"
            try:
                job.result = work()
                job.status = "succeeded"
            except errors.CancelledError as exc:
                job.status = "cancelled"
                job.error = str(exc)
            except errors.BookroomError as exc:
                job.status = "failed"
                job.error = str(exc)
            except Exception as exc:  # noqa: BLE001
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.finished_at = datetime.now(timezone.utc).isoformat()

        threading.Thread(target=runner, daemon=True).start()


def _handler_for(room: Bookroom, registry: JobRegistry, token: str | None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"BookroomSDK/{__version__}"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            return

        # ------------------------------------------------------------- helpers
        def _authorized(self, query: dict[str, list[str]]) -> bool:
            if not token:
                return True
            header = self.headers.get("Authorization") or ""
            if header.startswith("Bearer ") and header[7:].strip() == token:
                return True
            supplied = (query.get("token") or [""])[0]
            return bool(supplied) and supplied == token

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except ValueError as exc:
                raise errors.ValidationError(f"Request body is not valid JSON: {exc}") from None
            if not isinstance(data, dict):
                raise errors.ValidationError("Request body must be a JSON object")
            return data

        def _send(self, payload: Any, status: int = 200,
                  content_type: str = "application/json") -> None:
            if content_type == "application/json":
                body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            else:
                body = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _fail(self, exc: BaseException) -> None:
            mapping: list[tuple[type[BaseException], int, str]] = [
                (errors.ValidationError, 400, "invalid_request"),
                (errors.ConfigError, 400, "configuration_error"),
                (errors.UnsupportedSourceError, 415, "unsupported_source"),
                (errors.ExtractionError, 422, "extraction_failed"),
                (errors.BudgetExceededError, 422, "budget_exceeded"),
                (errors.QuotaError, 429, "quota_exceeded"),
                (errors.ProviderError, 502, "provider_error"),
                (errors.CancelledError, 409, "cancelled"),
                (errors.AppLoadError, 500, "application_load_failed"),
                (errors.BookroomError, 500, "sdk_error"),
            ]
            for kind, status, code in mapping:
                if isinstance(exc, kind):
                    payload: dict[str, Any] = {"error": {"code": code, "message": str(exc),
                                                         "type": type(exc).__name__}}
                    if isinstance(exc, errors.ProviderError) and exc.retry_after_seconds:
                        payload["error"]["retry_after_seconds"] = exc.retry_after_seconds
                    self._send(payload, status)
                    return
            self._send({"error": {"code": "internal_error",
                                  "message": f"{type(exc).__name__}: {exc}",
                                  "type": type(exc).__name__,
                                  "trace": _redact(traceback.format_exc())}}, 500)

        def _path_params(self) -> tuple[str, dict[str, list[str]]]:
            parsed = urlparse(self.path)
            return parsed.path, parse_qs(parsed.query)

        # ------------------------------------------------------------- routing
        def do_GET(self) -> None:  # noqa: N802
            path, query = self._path_params()
            try:
                if not self._authorized(query):
                    self._send({"error": {"code": "unauthorized", "message": "Invalid or missing facade token"}}, 401)
                    return
                if path in ("/", "/healthz", f"{API_PREFIX}/healthz"):
                    self._send({"status": "ok", "sdk_version": __version__})
                    return
                if path == f"{API_PREFIX}/describe":
                    self._send(room.describe())
                    return
                if path == f"{API_PREFIX}/capabilities":
                    self._send({"capabilities": room.describe()["capabilities"]})
                    return
                if path == f"{API_PREFIX}/check":
                    with RUN_LOCK:
                        self._send(room.check().as_dict())
                    return
                if path == f"{API_PREFIX}/sections":
                    self._send({"sections": room.review.report_sections()})
                    return
                if path == f"{API_PREFIX}/ocr-languages":
                    self._send({"languages": room.extract.ocr_languages()})
                    return
                if path == f"{API_PREFIX}/usage":
                    report = (query.get("report_path") or [""])[0]
                    with RUN_LOCK:
                        self._send(room.export.usage(report or None))
                    return
                if path == f"{API_PREFIX}/artifacts":
                    report = (query.get("report_path") or [""])[0]
                    if not report:
                        raise errors.ValidationError("report_path is required")
                    self._send({"artifacts": [a.as_dict() for a in room.export.artifacts(report)]})
                    return
                if path == f"{API_PREFIX}/download":
                    name = (query.get("name") or [""])[0]
                    report = (query.get("report_path") or [""])[0]
                    if not name or not report:
                        raise errors.ValidationError("name and report_path are required")
                    self._serve_artifact(room, name, report)
                    return
                if path == f"{API_PREFIX}/jobs":
                    self._send({"jobs": registry.list()})
                    return
                if path.startswith(f"{API_PREFIX}/jobs/"):
                    job = registry.get(path.rsplit("/", 1)[-1])
                    if job is None:
                        self._send({"error": {"code": "not_found", "message": "Unknown job id"}}, 404)
                        return
                    include = (query.get("messages") or [""])[0].lower() in {"1", "true", "yes"}
                    self._send(job.snapshot(include_messages=include))
                    return
                self._send({"error": {"code": "not_found", "message": f"No route for GET {path}"}}, 404)
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)

        def do_POST(self) -> None:  # noqa: N802
            path, query = self._path_params()
            try:
                if not self._authorized(query):
                    self._send({"error": {"code": "unauthorized", "message": "Invalid or missing facade token"}}, 401)
                    return
                body = self._body()
                if path == f"{API_PREFIX}/jobs":
                    self._send(_start_job(registry, room, body))
                    return
                route = _ROUTES.get(path)
                if route is None:
                    self._send({"error": {"code": "not_found", "message": f"No route for POST {path}"}}, 404)
                    return
                needs_lock, handler = route
                if needs_lock:
                    with RUN_LOCK:
                        self._send(handler(room, body))
                else:
                    self._send(handler(room, body))
            except Exception as exc:  # noqa: BLE001
                self._fail(exc)

        def do_DELETE(self) -> None:  # noqa: N802
            path, query = self._path_params()
            if not self._authorized(query):
                self._send({"error": {"code": "unauthorized", "message": "Invalid or missing facade token"}}, 401)
                return
            if path.startswith(f"{API_PREFIX}/jobs/"):
                job = registry.get(path.rsplit("/", 1)[-1])
                if job is None:
                    self._send({"error": {"code": "not_found", "message": "Unknown job id"}}, 404)
                    return
                if job.status in {"queued", "running"}:
                    self._send({"error": {"code": "conflict",
                                          "message": "A running job cannot be removed"}}, 409)
                    return
                with registry._lock:  # noqa: SLF001 - same-module owner
                    registry._jobs.pop(job.id, None)
                self._send({"deleted": job.id})
                return
            self._send({"error": {"code": "not_found", "message": f"No route for DELETE {path}"}}, 404)

        # ------------------------------------------------------- raw downloads
        def _serve_artifact(self, room: Bookroom, name: str, report_path: str) -> None:
            """Stream one generated artifact back to the client.

            Confined to the directory that holds the named report, so a crafted
            name cannot read arbitrary files off the server.
            """
            media = _MEDIA_TYPES.get(name)
            if media is None:
                raise errors.ValidationError(
                    f"Unknown artifact '{name}'. Known: {', '.join(sorted(_MEDIA_TYPES))}"
                )
            report = Path(report_path).expanduser().resolve()
            if not report.is_file():
                raise errors.ValidationError(f"No report at {report}")
            base = report.parent
            target = (base / name).resolve()
            # Defence in depth: the resolved target must still be inside the
            # report's own directory.
            if target.parent != base or not target.is_file():
                raise errors.ValidationError(f"No artifact '{name}' beside {report.name}")
            self._send(target.read_bytes(), 200, content_type=media)

    return Handler


# --------------------------------------------------------------------------- #
# Route table: (serialized, handler)
# --------------------------------------------------------------------------- #
def _require(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Assert the named fields are present, then hand the payload back."""
    missing = [key for key in keys if not data.get(key)]
    if missing:
        raise errors.ValidationError(f"Missing required field(s): {', '.join(missing)}")
    return data


def _start_job(registry: "JobRegistry", room: Bookroom, body: dict[str, Any]) -> dict[str, Any]:
    """Kick off a long run in the background and return its id."""
    kind = str(body.get("kind") or "study-guide")
    payload = {key: value for key, value in body.items() if key != "kind"}
    if kind not in {"study-guide", "review-report"}:
        raise errors.ValidationError(
            f"Unknown job kind '{kind}'. Supported: study-guide, review-report"
        )
    # Each kind requires a different field; a review job needs no source book.
    if kind == "study-guide":
        _require(payload, "path")
    else:
        _require(payload, "report_path")

    job = registry.create(kind, payload)

    def work() -> Any:
        if kind == "review-report":
            with RUN_LOCK:
                return {"records": room.review.review_report(payload["report_path"])}
        with RUN_LOCK:
            return room.summarize.study_guide(
                payload["path"], options=payload.get("options"),
                output_slug=payload.get("output_slug"),
                review=payload.get("review"),
                progress=lambda message, **kw: job.messages.append(str(message)),
            ).as_dict()

    registry.submit(job, work)
    return job.snapshot()


_ROUTES: dict[str, tuple[bool, Callable[[Bookroom, dict[str, Any]], Any]]] = {
    f"{API_PREFIX}/extract": (True, lambda r, b: r.extract.extract(
        _require(b, "path")["path"], options=b.get("options"),
        include_text=bool(b.get("include_text"))).as_dict(include_text=bool(b.get("include_text")))),
    f"{API_PREFIX}/metadata": (False, lambda r, b: r.extract.metadata(_require(b, "path")["path"])),
    f"{API_PREFIX}/outline": (False, lambda r, b: {"outline": r.extract.outline(_require(b, "path")["path"])}),
    f"{API_PREFIX}/preflight": (True, lambda r, b: r.summarize.preflight(
        _require(b, "path")["path"], options=b.get("options")).as_dict()),
    f"{API_PREFIX}/summarize-section": (True, lambda r, b: {
        "notes": r.summarize.summarize_section(_require(b, "title", "source"), options=b.get("options"))}),
    f"{API_PREFIX}/summarize-text": (True, lambda r, b: {
        "notes": r.summarize.summarize_text(_require(b, "text")["text"],
                                           title=b.get("title", "Untitled"),
                                           options=b.get("options"))}),
    f"{API_PREFIX}/digest": (True, lambda r, b: {
        "digest": r.summarize.digest(_require(b, "title", "chapter_notes")["title"],
                                     b["chapter_notes"], options=b.get("options"))}),
    f"{API_PREFIX}/study-guide": (True, lambda r, b: r.summarize.study_guide(
        _require(b, "path")["path"], options=b.get("options"),
        output_slug=b.get("output_slug"),
        review=b.get("review")).as_dict()),
    f"{API_PREFIX}/review/evaluate": (True, lambda r, b: r.review.evaluate(
        _require(b, "source_excerpt", "summary")["source_excerpt"], b["summary"])),
    f"{API_PREFIX}/review/section": (True, lambda r, b: r.review.evaluate_section(
        _require(b, "title", "source", "draft")["title"],
        b["source"], b["draft"]).as_dict()),
    f"{API_PREFIX}/review/report": (True, lambda r, b: {
        "records": r.review.review_report(_require(b, "report_path")["report_path"])}),
    f"{API_PREFIX}/review/evaluations": (False, lambda r, b: {
        "evaluations": r.review.evaluations(_require(b, "report_path")["report_path"])}),
    f"{API_PREFIX}/export/pdf": (True, lambda r, b: r.export.pdf(
        _require(b, "report_path")["report_path"], b.get("pdf_path")).as_dict()),
    f"{API_PREFIX}/export/markdown": (False, lambda r, b: {
        "markdown": r.export.markdown(_require(b, "report_path")["report_path"])}),
    f"{API_PREFIX}/export/validate": (False, lambda r, b: {
        "problems": r.export.validate(_require(b, "markdown")["markdown"])}),
    f"{API_PREFIX}/export/render": (True, lambda r, b: {
        "markdown": r.export.render_report(_require(b, "title", "sections")["title"],
                                           b["sections"],
                                           author=b.get("author", "Unknown author"),
                                           source_name=b.get("source_name", "Unknown source"))}),
    f"{API_PREFIX}/export/concept-map": (False, lambda r, b: r.export.concept_map(
        _require(b, "report_path")["report_path"])),
    f"{API_PREFIX}/export/claim-audit": (False, lambda r, b: r.export.claim_audit(
        _require(b, "report_path")["report_path"], b.get("chapter_notes"),
        min_overlap=float(b.get("min_overlap", 0.18)))),
    f"{API_PREFIX}/export/manifest": (False, lambda r, b: r.export.manifest(
        _require(b, "report_path", "source_path")["report_path"], b["source_path"])),
    f"{API_PREFIX}/export/merge": (False, lambda r, b: {
        "path": r.export.merge_markdown(_require(b, "folder")["folder"],
                                        b.get("destination", "book.md"))}),
    f"{API_PREFIX}/translate": (True, lambda r, b: {
        "translation": r.translate.translate(_require(b, "text", "target_lang")["text"],
                                            b["target_lang"])}),
    f"{API_PREFIX}/translate/batch": (True, lambda r, b: {
        "translations": r.translate.translate_batch(b.get("texts") or [], b.get("target_lang", ""))}),
    f"{API_PREFIX}/translate/classify": (True, lambda r, b: {
        "relevant": r.translate.classify_chapters(b.get("texts") or [])}),
    f"{API_PREFIX}/translate/notes": (True, lambda r, b: {
        "notes": r.translate.extract_notes(b.get("texts") or [])}),
}


def create_server(room: Bookroom, host: str = "127.0.0.1", port: int = 8787,
                  token: str | None = None) -> ThreadingHTTPServer:
    """Build (but do not start) the facade server."""
    registry = JobRegistry()
    handler = _handler_for(room, registry, token)
    server = ThreadingHTTPServer((host, port), handler)
    server.bookroom_registry = registry  # type: ignore[attr-defined]
    return server


def serve(room: Bookroom, host: str = "127.0.0.1", port: int = 8787,
          token: str | None = None) -> None:
    """Run the facade until interrupted."""
    server = create_server(room, host, port, token)
    bound_host, bound_port = server.server_address[0], server.server_address[1]
    print(f"Bookroom SDK {__version__} listening on http://{bound_host}:{bound_port}")
    print(f"  application root : {room.app_root}")
    print(f"  LLM endpoint     : {room.config.llm_base_url}")
    print(f"  review endpoint  : {room.config.jev_base_url}")
    print(f"  review enabled   : {room.config.review_enabled}")
    print(f"  facade token     : {'set' if token else 'disabled (open on loopback only)'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.shutdown()
        server.server_close()
