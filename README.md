# Bookroom SDK

An SDK for the **Bookroom** book summarizer. It wraps every capability the
engine has — EPUB/PDF extraction, chapter notes, the 16-section study guide,
independent JEv review with bounded revisions, and Markdown / PDF /
concept-map / claim-audit / manifest exports — as a library you can call
directly, for Python, TypeScript, JavaScript, React and Next.js.

**An integrator supplies only two values: the LLM API key and the JEv API key.**
Every endpoint, model, threshold and budget is defaulted and overridable, and
the endpoints are exported so you can point the SDK at a proxy, a self-hosted
model, or a JEv-compatible service.

There is no UI in this repository. Everything here is code and a CLI.

## Layout

| Path | What it is |
|---|---|
| `python/bookroom_sdk/` | Python SDK. Imports the engine in-process. Reference implementation. |
| `src/` | TypeScript/JavaScript SDK. HTTP client, plus `react` and `next` entry points. |
| `run_summary.py` | Full summarization cycle through the SDK. CLI, no UI. |
| `run_baseline.py` | The same cycle through the engine's own code path, for comparison. |
| `compare_runs.py` | Diffs two runs and reports whether anything functionally diverged. |
| `SKILL.md` | Integration guide for AI agents. |
| `examples/` | Runnable `react`, `nextjs`, `javascript`, `typescript` integrations. |

## Install

### Python

The Python SDK drives the engine application in-process, so it needs the
application's dependencies and its path.

```powershell
$env:PYTHONPATH = "D:\summarizer-sdk\python"
$env:BOOKROOM_APP_ROOT = "D:\summarizer\src"   # contains book_pipeline.py
```

### TypeScript / JavaScript

```bash
npm install
npm run build
```

## Configuration

Copy `.env.example` to `.env` and fill it in. Only two values are required:

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes | Generation. |
| `TYPESAFE_API_KEY` | for review | JEv review. Omit to run without it. |
| `BOOKROOM_APP_ROOT` | yes (Python) | Path to the engine source root. |

A real environment variable always wins over a `.env` value. The SDK reads
`.env` from the working directory and from the engine root, so the same file
that configures the application configures the SDK.

Endpoints are exported and overridable:

| Variable | Default |
|---|---|
| `BOOKROOM_LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` |
| `BOOKROOM_LLM_MODEL` | `gemini-3.8-flash` |
| `BOOKROOM_JEV_BASE_URL` | `https://api.typesafe.ai/v1` |
| `BOOKROOM_JEV_MODEL` | `jev-latest` |

## Quickstart

### Python

```python
from bookroom_sdk import Bookroom

room = Bookroom.from_env()

room.check()                                  # credentials, before spending
plan = room.summarize.preflight("book.epub")  # cost estimate + budget check
report = room.summarize.study_guide("book.epub")

print(report.markdown.path)      # study-guide.md
print(report.pdf.path)           # study-guide.pdf
print(report.quality.as_dict())  # 16 categories, scores, pass counts
```

### TypeScript

```ts
import { Bookroom } from "bookroom-sdk";

const room = new Bookroom({
  baseUrl: process.env.BOOKROOM_URL!,
  token: process.env.BOOKROOM_FACADE_TOKEN!,
});

const job = await room.jobs.studyGuide({ path: "book.epub" });
const done = await room.jobs.waitFor(job.id, { timeoutMs: 900_000 });
console.log(done.result?.quality);
```

### React

```tsx
import { useBookroomJob, StudyGuidePanel } from "bookroom-sdk/react";

function App() {
  const job = useBookroomJob({ pollIntervalMs: 1000 });
  return <StudyGuidePanel job={job} path="book.epub" onStart={job.start} />;
}
```

`baseUrl` must point at **your** backend, which proxies to the facade. The
facade token must never reach the browser.

### Next.js

```ts
// app/actions.ts  (server only)
"use server";
import { createSummarizeAction, createJobStatusAction } from "bookroom-sdk/next";

export const summarize = createSummarizeAction();
export const jobStatus = createJobStatusAction();
```

The token is read from the server environment and never crosses to the client.

## Running a book end to end

```powershell
# through the SDK
python run_summary.py "C:\path\to\book.pdf" --out runs\sdk --slug mybook

# through the engine's own code path, for comparison
python run_baseline.py "C:\path\to\book.pdf" --out runs\baseline --slug mybook

# diff the two
python compare_runs.py runs\sdk runs\baseline
```

`run_summary.py` writes a `run-report.json` with stage timings, artifact sizes,
format-validation results, claim counts and token usage, so two runs can be
compared without re-reading the prose.

## What a run produces

1. **Preflight** — cost estimate and work-batch plan, with budget caps enforced
   before any paid call.
2. **Chapter notes** — one per section, with page-range or EPUB locators.
3. **Digest** — all 15 remaining sections.
4. **JEv review** — all 16 categories scored independently, with bounded
   revisions. Categories still below threshold are kept with their history.
5. **Exports** — `study-guide.md`, `study-guide.pdf`, `chapter-notes.md`,
   `study-maps.json`, `claim-audit.json`, `manifest.json`, `usage.json`,
   `preflight.json`, `evaluations.json`.

Every stage is saved as it completes, so an interrupted or quota-paused run
resumes from the last finished stage rather than paying twice.

## The credential model

The two provider keys never need to leave your deployment.

- **Python** — the caller holds them in the process.
- **Every other language** — the Python facade holds them:

  ```bash
  python -m bookroom_sdk serve --host 127.0.0.1 --port 8787 --token "$BOOKROOM_FACADE_TOKEN"
  ```

  Clients send only the facade token, and only from a server.

`describe()` returns the full active configuration — endpoints, models,
thresholds, budget caps — with no secret values in it, so it is safe to log.

## Errors

Python raises `BookroomError` subclasses: `ConfigError`,
`UnsupportedSourceError`, `ExtractionError`, `BudgetExceededError`,
`ValidationError`, `QuotaError`, `ProviderError`, `CancelledError`, `JobError`.
TypeScript throws `BookroomError` with `code`/`status` and guards such as
`isQuotaError`. A quota error carries `retryAfterSeconds`; re-run to resume.

## Reading results honestly

- `quality` reports how many of the 16 categories met the threshold. A run with
  some below it is a legitimate outcome, not a bug.
- `claim-audit` is **lexical overlap, not fact-checking**. Low-overlap claims are
  flagged for a human.
- OCR confidence is a recognition signal, not a correctness guarantee.
- JEv scores are advisory signals, not proof that a summary is right.

## For AI agents

Read [`SKILL.md`](SKILL.md) before integrating. It states the credential rule,
the required sequence (check → preflight → run → report honestly), the job
pattern for long runs, and the failure modes to expect.

## Security

`.env` holds real credentials and is **git-ignored** — it is never committed.
`.env.example` is the committed template and contains no secrets. The facade
token is a separate, non-provider credential for the HTTP surface.
