"""Verify the HTTP facade the other-language SDKs depend on.

Starts the facade on loopback with mock providers behind it, then exercises the
routes over real HTTP and checks the responses.

    python verify_facade.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
# The package lives under python/, so a checkout run needs that on the path too.
sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))

from fixtures import build_epub, build_pdf          # noqa: E402
from mock_providers import MockProviders            # noqa: E402

from bookroom_sdk import Bookroom                   # noqa: E402
from bookroom_sdk.server import create_server       # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))


def request(base: str, method: str, path: str, body: dict | None = None,
            token: str | None = None) -> tuple[int, dict]:
    url = f"{base}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="bookroom-facade-"))
    token = "facade-test-token"
    print(f"workdir: {workdir}")

    try:
        epub = build_epub(workdir / "src" / "attention.epub")
        build_pdf(workdir / "src" / "attention.pdf")

        with MockProviders() as mock:
            room = Bookroom(
                llm_api_key="mock-llm-key",
                jev_api_key="mock-jev-key",
                llm_base_url=mock.llm_base_url,
                jev_base_url=mock.jev_base_url,
                output_dir=workdir / "output",
            )
            server = create_server(room, host="127.0.0.1", port=0, token=token)
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print(f"facade: {base}")

            try:
                print("\n=== auth ===")
                status, _ = request(base, "GET", "/v1/describe")
                check("unauthenticated request rejected", status == 401, f"HTTP {status}")
                status, _ = request(base, "GET", "/v1/describe", token=token)
                check("authenticated request allowed", status == 200, f"HTTP {status}")

                print("\n=== metadata routes ===")
                status, body = request(base, "GET", "/v1/describe", token=token)
                check("describe returns capabilities",
                      status == 200 and len(body.get("capabilities", [])) >= 35,
                      f"{len(body.get('capabilities', []))} capabilities")
                check("describe hides secrets", "mock-llm-key" not in json.dumps(body))
                check("describe exports endpoints",
                      body["config"]["llm_endpoint"] == mock.llm_base_url)

                status, body = request(base, "GET", "/v1/check", token=token)
                check("provider check over HTTP", status == 200 and body.get("ok") is True,
                      json.dumps(body)[:80])

                status, body = request(base, "GET", "/v1/sections", token=token)
                check("16 report categories over HTTP",
                      status == 200 and len(body.get("sections", [])) == 16,
                      f"{len(body.get('sections', []))}")

                print("\n=== extraction ===")
                status, body = request(base, "POST", "/v1/extract",
                                       {"path": str(epub)}, token=token)
                check("extract over HTTP", status == 200 and body.get("section_count") == 4,
                      f"{body.get('section_count')} sections")

                status, body = request(base, "POST", "/v1/extract", {"path": str(epub)})
                check("extract without token rejected", status == 401, f"HTTP {status}")

                status, body = request(base, "POST", "/v1/extract", {}, token=token)
                check("missing field is a 400",
                      status == 400 and body.get("error", {}).get("code") == "invalid_request",
                      json.dumps(body)[:90])

                status, body = request(base, "POST", "/v1/extract",
                                       {"path": str(workdir / "src" / "nope.pdf")}, token=token)
                check("missing file is reported cleanly",
                      status in {400, 415} and "error" in body, f"HTTP {status}")

                print("\n=== preflight ===")
                status, body = request(base, "POST", "/v1/preflight",
                                       {"path": str(epub)}, token=token)
                check("preflight over HTTP",
                      status == 200 and body.get("batch_count", 0) >= 1,
                      f"{body.get('batch_count')} batches")

                print("\n=== summarization ===")
                status, body = request(base, "POST", "/v1/summarize-text",
                                       {"text": "Attention is scarce. " * 60,
                                        "title": "T"}, token=token)
                check("summarize-text over HTTP", status == 200 and bool(body.get("notes")),
                      f"{len(body.get('notes', ''))} chars")

                print("\n=== study guide (synchronous) ===")
                status, body = request(base, "POST", "/v1/study-guide",
                                       {"path": str(epub), "output_slug": "attention"},
                                       token=token)
                check("study-guide over HTTP", status == 200, f"HTTP {status}")
                if status == 200:
                    artifacts = {a["name"] for a in body.get("artifacts", [])}
                    check("study-guide produced markdown", "study-guide.md" in artifacts,
                          str(sorted(artifacts)))
                    check("study-guide produced pdf", "study-guide.pdf" in artifacts)
                    check("study-guide produced concept map", "study-maps.json" in artifacts)
                    check("study-guide produced manifest", "manifest.json" in artifacts)
                    quality = body.get("quality") or {}
                    check("study-guide reports quality",
                          quality.get("categories_reviewed") == 16,
                          f"{quality.get('categories_reviewed')} categories")
                    report_path = body.get("report_path")
                else:
                    report_path = None
                    check("study-guide error payload", False, json.dumps(body)[:160])

                if report_path:
                    print("\n=== exports over HTTP ===")
                    status, body = request(base, "GET", f"/v1/artifacts?report_path={report_path}",
                                           token=token)
                    check("artifact listing over HTTP", status == 200 and bool(body.get("artifacts")))
                    status, body = request(base, "POST", "/v1/export/markdown",
                                           {"report_path": report_path}, token=token)
                    check("markdown export over HTTP",
                          status == 200 and len(body.get("markdown", "")) > 2000,
                          f"{len(body.get('markdown', ''))} chars")
                    status, body = request(base, "POST", "/v1/export/validate",
                                           {"markdown": body.get("markdown", "")}, token=token)
                    check("validation over HTTP returns no problems",
                          status == 200 and body.get("problems") == [],
                          str(body.get("problems"))[:80])
                    status, body = request(base, "POST", "/v1/export/pdf",
                                           {"report_path": report_path}, token=token)
                    check("pdf export over HTTP", status == 200 and body.get("exists") is True,
                          f"{body.get('path')}")
                    status, body = request(base, "POST", "/v1/export/concept-map",
                                           {"report_path": report_path}, token=token)
                    check("concept map over HTTP", status == 200 and "nodes" in body,
                          f"{len(body.get('nodes', []))} nodes")
                    status, body = request(base, "POST", "/v1/export/claim-audit",
                                           {"report_path": report_path}, token=token)
                    check("claim audit over HTTP", status == 200 and body.get("claim_count", 0) > 0,
                          f"{body.get('claim_count')} claims")
                    status, body = request(base, "POST", "/v1/export/manifest",
                                           {"report_path": report_path, "source_path": str(epub)},
                                           token=token)
                    check("manifest over HTTP", status == 200 and bool(body.get("generation_model")))

                    print("\n=== review over HTTP ===")
                    status, body = request(base, "POST", "/v1/review/evaluate",
                                           {"source_excerpt": "Water freezes at 0C.",
                                            "summary": "Water freezes at 0C."}, token=token)
                    check("standalone review over HTTP", status == 200 and "answers" in body)
                    status, body = request(base, "POST", "/v1/review/report",
                                           {"report_path": report_path}, token=token)
                    check("16-category gate over HTTP",
                          status == 200 and len(body.get("records", [])) == 16,
                          f"{len(body.get('records', []))} records")

                print("\n=== async job ===")
                status, body = request(base, "POST", "/v1/jobs",
                                       {"kind": "study-guide", "path": str(epub),
                                        "output_slug": "jobbed"}, token=token)
                job_id = body.get("id")
                check("job created", status == 200 and bool(job_id), str(body)[:80])
                if job_id:
                    deadline = time.time() + 300
                    final: dict = {}
                    while time.time() < deadline:
                        _, final = request(base, "GET", f"/v1/jobs/{job_id}?messages=1", token=token)
                        if final.get("status") in {"succeeded", "failed", "cancelled"}:
                            break
                        time.sleep(0.5)
                    check("job reached a terminal state",
                          final.get("status") == "succeeded", str(final.get("status")))
                    check("job recorded progress messages",
                          final.get("message_count", 0) > 0, f"{final.get('message_count')} messages")
                    check("job returned a report",
                          bool((final.get("result") or {}).get("report_path")))
                    status, _ = request(base, "DELETE", f"/v1/jobs/{job_id}", token=token)
                    check("completed job can be removed", status == 200, f"HTTP {status}")

                status, body = request(base, "GET", "/v1/jobs", token=token)
                check("job listing over HTTP", status == 200 and "jobs" in body)

                if report_path:
                    print("\n=== review-report job needs no source book ===")
                    status, body = request(base, "POST", "/v1/jobs",
                                           {"kind": "review-report",
                                            "report_path": report_path}, token=token)
                    review_job = body.get("id")
                    check("review-report job created without a path",
                          status == 200 and bool(review_job), str(body)[:90])
                    if review_job:
                        deadline = time.time() + 300
                        final_review: dict = {}
                        while time.time() < deadline:
                            _, final_review = request(
                                base, "GET", f"/v1/jobs/{review_job}", token=token)
                            if final_review.get("status") in {"succeeded", "failed", "cancelled"}:
                                break
                            time.sleep(0.5)
                        check("review-report job succeeded",
                              final_review.get("status") == "succeeded",
                              f"{final_review.get('status')}: {final_review.get('error')}")
                        check("review-report job returned 16 records",
                              len((final_review.get("result") or {}).get("records", [])) == 16)
                    status, body = request(base, "POST", "/v1/jobs",
                                           {"kind": "review-report"}, token=token)
                    check("review-report job without report_path is a 400",
                          status == 400, f"HTTP {status}")

                print("\n=== error mapping ===")
                status, body = request(base, "POST", "/v1/review/evaluate", {}, token=token)
                check("review without fields is 400",
                      status == 400 and body.get("error", {}).get("code") == "invalid_request")
                status, body = request(base, "GET", "/v1/nope", token=token)
                check("unknown route is 404", status == 404, f"HTTP {status}")

            finally:
                server.shutdown()
                server.server_close()

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n" + "=" * 62)
    print(f"PASSED {len(PASSED)}   FAILED {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All facade checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
