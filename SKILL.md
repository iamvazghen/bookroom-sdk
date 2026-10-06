---
name: bookroom-summarizer
description: >-
  Use when integrating the Bookroom book-summarizer SDK into an application, or
  when asked to summarize, extract, review, or export a book (EPUB or PDF) with
  it. Covers Python, TypeScript, JavaScript, React and Next.js, the two required
  API keys, the credential model, the full capability surface, the async job
  pattern for long runs, and the failure modes to expect.
---

# Bookroom summarizer SDK

Bookroom turns an EPUB or PDF into a complete 16-section study guide, has an
independent AI reviewer (JEv) score every section, and exports the result as
Markdown, PDF, a concept-map graph, a claim audit, and a manifest.

## The one rule that matters most

**Never put the LLM or JEv API key in browser or client-side code.**

- **Python** holds the keys in the process. It is the reference implementation.
- **TypeScript / JavaScript / React / Next.js** talk to the Python **facade**
  over HTTP. The facade process holds both keys; the client supplies only the
  facade's own token, and that token belongs on your **server**, never in a
  bundle, `NEXT_PUBLIC_*` variable, or browser fetch.

If a user asks for a client-only integration that calls providers directly,
stop and explain that this would publish the keys, and offer the facade or a
server route instead.

## Two required values

| Value | Purpose |
|---|---|
| `GEMINI_API_KEY` | Generation. Required. |
| `TYPESAFE_API_KEY` | JEv review. Optional; without it, review is skipped. |

Everything else is defaulted. Never invent a value for these; read them from the
environment and fail loudly if absent.

## Setup

The engine ships inside the Python package. Installing the SDK is the whole
setup — there is no separate checkout, no `PYTHONPATH`, and no
`BOOKROOM_APP_ROOT`.

```bash
pip install bookroom-sdk
```

```python
import os
os.environ["GEMINI_API_KEY"] = "..."      # or read from your own config
os.environ["TYPESAFE_API_KEY"] = "..."    # optional; without it, review is skipped

from bookroom_sdk import Bookroom
room = Bookroom.from_env()
print(room.app_root)      # the bundled engine, inside site-packages
```

If `from_env()` reports no credentials, that is expected and correct: the SDK
has no `.env` of its own. Set the variables, or drop a `.env` file beside your
script — one is read automatically, and a real environment variable always wins
over the file.

`BOOKROOM_APP_ROOT` exists only to point the SDK at an engine checkout instead
of the bundled copy, for engine development. You should not need it.

### TypeScript / JavaScript / React / Next.js

Start the facade, which is part of the same installed package:

```bash
bookroom serve --host 127.0.0.1 --port 8787 --token "$BOOKROOM_FACADE_TOKEN"
```

```ts
const room = new Bookroom({ baseUrl, token: process.env.BOOKROOM_FACADE_TOKEN });
```

Server-side only: read `BOOKROOM_URL` and `BOOKROOM_FACADE_TOKEN` from the
server environment and construct the client there. For Next.js, put that logic
in a Server Action or a Route Handler, and have the browser call *your* route.

## Always check credentials first

```python
health = room.check()          # Python
const health = await room.check();   // TS
```

This sends a tiny synthetic request and never sends book content. If
`health.ok` is false, stop — do not start a paid run against a bad key.

**What `check()` does not tell you.** It verifies that the provider is
*reachable* and that the key is *accepted*. It does **not** guarantee quota. A
minimal probe can succeed while the account's quota for the real workload is
already exhausted, so a green check can still be followed by a `QuotaError`
mid-run. Treat `check()` as a credential test, and handle `QuotaError` as a
normal, expected outcome rather than an anomaly.

## Always preflight before spending

```python
plan = room.summarize.preflight(source)
print(plan.estimated_llm_input_tokens, plan.estimated_jev_credits, plan.batch_count)
```

Preflight enforces the budget caps *before* any paid call. A book that exceeds a
cap raises `BudgetExceededError`; raise the cap or split the book rather than
letting it fail halfway.

## Long operations are jobs, not calls

A full study guide takes minutes. Never hold an HTTP request open for it in the
browser, and never assume a synchronous call returns promptly.

```python
report = room.summarize.study_guide(source)   # Python: blocking, checkpointed
```

```ts
const job = await room.jobs.studyGuide({ path, outputSlug });
const done = await room.jobs.waitFor(job.id, { timeoutMs: 900_000, intervalMs: 500 });
```

In React, use `useBookroomJob` from `bookroom-sdk/react`, which starts the job,
polls, and cleans up on unmount.

## Checkpointing and quotas

Every stage is saved as it completes. A run interrupted by a quota limit or a
crash **resumes from the last finished stage** when re-run with the same output
directory. Do not delete the output directory to "start clean" — that throws away
paid work. Catch `QuotaError` (Python) / `isQuotaError` (TS), read
`retryAfterSeconds`, and re-run later.

## Capability map

| Need | Python | TypeScript |
|---|---|---|
| Read a book | `room.extract.extract(path)` | `room.extract.extract({ path })` |
| Cost estimate | `room.summarize.preflight(path)` | `room.summarize.preflight({ path })` |
| Full study guide | `room.summarize.study_guide(path)` | `room.summarize.studyGuide({ path })` |
| One section / raw text | `summarize_section`, `summarize_text` | `summarizeSection`, `summarizeText` |
| Digest only | `room.summarize.digest(...)` | `room.summarize.digest(...)` |
| Score a summary | `room.review.evaluate(src, sum)` | `room.review.evaluate({ sourceExcerpt, summary })` |
| Re-review a report | `room.review.review_report(path)` | `room.review.report(path)` |
| PDF / Markdown | `room.export.pdf(md)`, `room.export.markdown(md)` | `room.export.pdf({ reportPath })`, `room.export.markdown(md)` |
| Concept graph | `room.export.concept_map(md)` | `room.export.conceptMap(md)` |
| Claim audit | `room.export.claim_audit(md)` | `room.export.claimAudit({ reportPath })` |
| Check markdown | `room.export.validate(md)` | `room.export.validate(md)` |
| Credentials | `room.check()` | `room.check()` |

## Reading the results honestly

- `report.quality` shows how many of the 16 categories met the threshold. A run
  where some categories are below it is a **legitimate outcome, not a bug**.
  Report the number; do not describe a partial run as a full pass.
- `claim_audit` is **lexical overlap, not fact-checking**. A low-overlap claim
  is flagged for a human. Never present it as verification.
- OCR confidence is a recognition signal. A low-confidence name or number is a
  prompt to check the page image, not a claim that the text is right.
- JEv scores are advisory signals about faithfulness, coverage, clarity and
  structure. They are not a guarantee of correctness.

## Failure modes and what to do

| Symptom | Cause | Fix |
|---|---|---|
| `ConfigError: llm_api_key is required` | key not loaded | set `GEMINI_API_KEY` |
| `check()` says `not_configured` | SDK has no credentials to read | set the key; a `.env` beside your script is also read |
| `UnsupportedSourceError` | not a `.pdf`/`.epub` | convert the file |
| `ExtractionError` | no text found | scanned PDF: enable OCR and install Tesseract |
| `BudgetExceededError` | over a per-batch cap | raise the cap or split the book |
| `QuotaError` / HTTP 429 | provider quota | wait `retryAfterSeconds`, re-run to resume |
| `ModuleNotFoundError: book_pipeline` | the `_engine` directory was stripped from the install | reinstall; do not copy only the `.py` files at the package root |
| `ValidationError` | report formatting broken | file the bug; do not paper over it |
| HTTP 401 from the facade | token missing or wrong | `Authorization: Bearer <token>` |

## Definition of done

An integration is complete when: `check()` passes, `preflight` was reviewed
before spending, a real book produced a validated report, every artifact the
caller asked for exists, and the quality summary was reported honestly —
including categories that fell below threshold. Do not report success on the
strength of a unit test alone.
