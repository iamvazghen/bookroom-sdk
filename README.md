<div align="center">

# Bookroom

**Turn a book into a complete, independently reviewed study guide — from any codebase.**

[![npm](https://img.shields.io/npm/v/bookroom-sdk?logo=npm&label=npm)](https://www.npmjs.com/package/bookroom-sdk)
[![PyPI](https://img.shields.io/pypi/v/bookroom-sdk?logo=pypi&color=blue&label=PyPI)](https://pypi.org/project/bookroom-sdk/)
[![Live demo](https://img.shields.io/badge/live%20demo-bookroom--summarizer.vercel.app-0052ff?logo=vercel&logoColor=white)](https://bookroom-summarizer.vercel.app/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Node](https://img.shields.io/badge/node-18%2B-green?logo=node.js&logoColor=white)](https://nodejs.org/)
[![TypeScript](https://img.shields.io/badge/typescript-strict-blue?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![React](https://img.shields.io/badge/react-18%2B-61dafb?logo=react&logoColor=black)](https://react.dev/)
[![Next.js](https://img.shields.io/badge/next.js-13%2B-black?logo=next.js&logoColor=white)](https://nextjs.org/)
[![Code of Conduct](https://img.shields.io/badge/Code%20of%20Conduct-Contributor%20Covenant-blue)](CODE_OF_CONDUCT.md)
[![Security](https://img.shields.io/badge/security-policy-informational)](SECURITY.md)

`EPUB` `PDF` `Markdown` `study guide` `summarization` `LLM` `JEv review` `concept map` `RAG`

### [Try it live →](https://bookroom-summarizer.vercel.app/)

Upload a book and see the whole pipeline in a browser before you write a line of
code. That deployment is the same engine this SDK wraps — use it to find out
whether the output is what you want, then install the SDK to get it into your
own codebase.

</div>

---

## What it is

Bookroom reads a book — an **EPUB or PDF** — and produces a **complete 16-section
study guide**: thesis, argument flow, chapter-by-chapter notes with page
locators, takeaways, quotes, glossary, FAQ, a plain-language explanation, a
concept map, critical questions, and personal reflection prompts.

Then it does the part most tools skip: an **independent reviewer (JEv) scores
every one of the 16 sections** for faithfulness, coverage, clarity and
structure against the source, and drives a bounded number of revisions. A weak
score is recorded and shown, never hidden.

Everything is exported: **Markdown**, **PDF**, a **concept-map graph**, a
**claim audit**, a reproducible **manifest**, and token accounting.

It is an **SDK first**. There is no UI. The engine is a library, so you decide
where it runs.

<div align="center">
  <table>
    <tr>
      <td align="center"><b>Python</b></td>
      <td align="center"><b>TypeScript</b></td>
      <td align="center"><b>JavaScript</b></td>
      <td align="center"><b>React</b></td>
      <td align="center"><b>Next.js</b></td>
    </tr>
    <tr>
      <td align="center">in-process, no server</td>
      <td align="center">typed HTTP client</td>
      <td align="center">plain ESM/CJS</td>
      <td align="center">hooks + component</td>
      <td align="center">actions + routes</td>
    </tr>
  </table>
</div>

---

## The two-key rule

**You supply exactly two values.** Everything else — endpoints, models,
thresholds, budgets, retry policy — is defaulted and overridable.

| Key | Required? | What it does |
|---|---|---|
| `GEMINI_API_KEY` | **yes** | Generation |
| `TYPESAFE_API_KEY` | for review | JEv review. Omit it and review is skipped — and the run says so out loud |

The provider keys **never reach a browser**. The TypeScript, React and Next.js
clients talk to the Python facade, which holds the keys; clients authenticate
with a separate **facade token** that belongs on your server. The React hook
`useBookroomClient` throws if you try to pass a token in the browser.

---

## Install

> **Not yet on a registry.** `bookroom-sdk` is not published to PyPI or npm, so
> `pip install bookroom-sdk` will fail with 404 today. Install from GitHub — the
> forms below are tested by `verify_stranger_install.py` on every change.

### Python

```bash
pip install "bookroom-sdk @ git+https://github.com/iamvazghen/bookroom-sdk.git#subdirectory=python"
```

The `#subdirectory=python` part is required: the Python project lives in
`python/`, so pip needs to be told where to look. Cloning and installing
locally works identically:

```bash
git clone https://github.com/iamvazghen/bookroom-sdk.git
cd bookroom-sdk
pip install "./python[all]"
```

<details>
<summary>Other Python package handlers</summary>

```bash
# pipx — install the CLI as an app, isolated from your project
pipx install "bookroom-sdk @ git+https://github.com/iamvazghen/bookroom-sdk.git#subdirectory=python"
bookroom --version

# uv
uv pip install "bookroom-sdk @ git+https://github.com/iamvazghen/bookroom-sdk.git#subdirectory=python"
uv tool install "bookroom-sdk @ git+https://github.com/iamvazghen/bookroom-sdk.git#subdirectory=python"

# poetry
poetry add "bookroom-sdk @ git+https://github.com/iamvazghen/bookroom-sdk.git#subdirectory=python"

# pipenv
pipenv install "bookroom-sdk @ git+https://github.com/iamvazghen/bookroom-sdk.git#subdirectory=python"
```

</details>

### TypeScript / JavaScript

```bash
npm install "github:iamvazghen/bookroom-sdk"
```

<details>
<summary>Other Node package managers</summary>

```bash
pnpm add "github:iamvazghen/bookroom-sdk"
yarn add "github:iamvazghen/bookroom-sdk"
bun add "github:iamvazghen/bookroom-sdk"
deno add "github:iamvazghen/bookroom-sdk"
```

> **One registry, many clients.** `pnpm`, `yarn`, `bun` and `deno` all install
> from the same npm registry. There is nothing separate to register for each of
> them — they differ in resolver and cache, not in where a package lives.

</details>

### Talking to a non-Google provider

The engine speaks Google's `:generateContent` dialect. Many providers —
MiniMax, OpenRouter, vLLM, Together — speak OpenAI's `/chat/completions`
instead, so redirecting the endpoint at one of those returns 404: the *shapes*
differ, not only the host. The SDK ships a bridge that translates both ways:

```bash
bookroom bridge \
  --upstream https://api.minimax.io/v1 \
  --model MiniMax-Text-01
```

Then point the SDK at it and keep your key out of the SDK's own config:

```bash
export BOOKROOM_LLM_BASE_URL=http://127.0.0.1:8899
export GEMINI_API_KEY=$MINIMAX_API_KEY
```

The bridge forwards the `x-goog-api-key` header as an upstream bearer token,
rebuilds a Gemini-shaped response with token accounting, strips `<think>`
reasoning blocks that reasoning models put inside `content`, and widens the
upstream token allowance so reasoning cannot consume the whole answer budget
(`BOOKROOM_BRIDGE_TOKEN_MULTIPLIER`, default 3).

Prefer a non-reasoning model for this workload. A reasoning model will happily
spend an entire small `maxOutputTokens` on chain-of-thought and return no answer.

### With the alternate transport

Translation and chapter classification also run over Ollama or any
OpenAI-compatible endpoint. That needs two extra packages:

```bash
pip install "bookroom-sdk[legacy]"
```

### Docker

```bash
docker build -t bookroom .
docker run --rm -v "$PWD/books:/books" -v "$PWD/out:/out" \
  -e GEMINI_API_KEY -e TYPESAFE_API_KEY \
  bookroom extract /books/book.pdf
```

### Verify your install in one line

```bash
bookroom --version && bookroom extract /path/to/book.epub
```

No engine checkout, no `PYTHONPATH`, no `BOOKROOM_APP_ROOT`. The engine ships
inside the package.

---

## Quickstart

### Python — 20 seconds to a PDF

```python
from bookroom_sdk import Bookroom

room = Bookroom.from_env()          # reads GEMINI_API_KEY / TYPESAFE_API_KEY

room.check()                        # credentials, before you spend anything

plan = room.summarize.preflight("book.epub")
print(f"~{plan.estimated_llm_input_tokens:,} input tokens, "
      f"~{plan.estimated_jev_credits:,} review credits")

report = room.summarize.study_guide("book.epub")

print(report.markdown.path)          # study-guide.md
print(report.pdf.path)               # study-guide.pdf
print(report.quality.as_dict())      # 16 categories, scores, pass counts
```

### TypeScript — long runs are jobs, not blocking calls

```ts
import { Bookroom, isQuotaError } from "bookroom-sdk";

const room = new Bookroom({
  baseUrl: process.env.BOOKROOM_URL!,
  token: process.env.BOOKROOM_FACADE_TOKEN!,
});

try {
  const job = await room.jobs.studyGuide({ path: "book.epub" });
  const done = await room.jobs.waitFor(job.id, { timeoutMs: 900_000 });
  console.log(done.result?.quality);
} catch (error) {
  if (isQuotaError(error)) console.error("retry after", error.retryAfterSeconds);
  else throw error;
}
```

### React

```tsx
import { useBookroomJob, StudyGuidePanel } from "bookroom-sdk/react";

export function Generate() {
  const job = useBookroomJob({ pollIntervalMs: 1000 });
  return <StudyGuidePanel job={job} path="book.epub" onStart={job.start} />;
}
```

`baseUrl` must point at **your** backend, which proxies to the facade. A ready-made
Express proxy is in [`examples/react/`](examples/react/).

### Next.js

```ts
// app/actions.ts — server only
"use server";
import { createSummarizeAction, createJobStatusAction } from "bookroom-sdk/next";

export const summarize = createSummarizeAction();
export const jobStatus = createJobStatusAction();
```

The token is read from the server environment and never crosses to the client.
See [`examples/nextjs/`](examples/nextjs/).

### From the command line

```bash
bookroom check                          # verify both credentials
bookroom guide book.epub --out ./out    # the full job
bookroom extract book.pdf --text        # just read the structure
bookroom serve --port 8787 --token "$TOKEN"   # the facade for other languages
```

---

## For AI agents

**Give your agent this one command.** It is written to be pasted as-is and
points at the integration guide:

> Install and integrate the `bookroom-sdk` Python package. Before writing any
> code, read `SKILL.md` in the installed package — it states the credential
> rule, the required call order, the failure modes, and what a correct
> integration looks like. The only two values you must supply are the LLM API
> key and the JEv API key. Never put a provider key in client-side or browser
> code.

`SKILL.md` is shipped inside the package, so it is available offline at:

- Python: `python -c "import bookroom_sdk, pathlib; print(pathlib.Path(bookroom_sdk.__file__).parent / 'SKILL.md')"`
- Node: `node -e "console.log(require.resolve('bookroom-sdk'))"`

---

## Configuration

Copy `.env.example` to `.env`. A real environment variable always beats a file.

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | **Required.** Generation. |
| `TYPESAFE_API_KEY` | — | JEv review. Omit to skip review. |
| `BOOKROOM_LLM_BASE_URL` | Google Generative Language | **Exported** LLM endpoint. Point at a proxy or self-hosted model. |
| `BOOKROOM_LLM_MODEL` | `gemini-3.8-flash` | Generation model. |
| `BOOKROOM_JEV_BASE_URL` | `https://api.typesafe.ai/v1` | **Exported** review endpoint. |
| `BOOKROOM_JEV_MODEL` | `jev-latest` | Review model. |
| `JEV_SCORE_THRESHOLD` | `3.5` | Pass mark on the 0–4 scale. |
| `JEV_CONFIDENCE_THRESHOLD` | `0.55` | Minimum confidence to pass. |
| `JEV_MAX_REVISIONS` | `2` | Revision budget per section (0–3). |
| `MAX_ESTIMATED_LLM_INPUT_TOKENS` | `1500000` | Per-batch budget cap. |
| `MAX_ESTIMATED_JEV_CREDITS` | `12000` | Per-batch review cap. |
| `MIN_WORD_COUNT` | `200` | Smallest section that is summarized. |
| `OCR_ENABLED` / `OCR_LANGUAGE` | `false` / `eng` | Scanned PDFs (needs Tesseract). |
| `OUTPUT_DIR` | `output` | Where reports are written. |
| `BOOKROOM_APP_ROOT` | — | **Optional.** Use an engine checkout instead of the bundled copy. |
| `BOOKROOM_FACADE_TOKEN` | — | Token the HTTP facade requires. |

`room.describe()` returns all of this with **no secret values in it** — safe to
log or show on a status page.

---

## Use cases

- **Reading triage** — decide whether a book is worth your time before spending
  five hours on it, from a 10-minute digest.
- **Study and revision** — 16 sections with a concept map, glossary and
  reflection prompts, generated from the actual text.
- **Research intake** — a searchable Markdown artifact per source, with page
  locators back to the original.
- **Course and team onboarding** — pre-read a book, then discuss the digest
  instead of the first 40 pages.
- **Content pipelines** — batch-convert a library of EBOOKs to structured
  notes; the exports are machine-readable JSON as well as prose.
- **Reading-notes systems** — Obsidian, Logseq, Notion: the Markdown and the
  concept-map graph drop straight in.
- **Agent memory** — a long book compressed into a few thousand tokens that fit
  in a context window, without inventing detail.
- **Audit trails** — every report carries a manifest: source hash, model,
  threshold, and how many categories passed.
- **Quality gates** — wire the review into CI so a report cannot ship below
  threshold without a human deciding.
- **Accessible and multilingual editions** — `--language` and the alternate
  transport produce a study guide in another language.

---

## Results

### What one run produces

Nine artifacts, from one call:

| Artifact | What it is |
|---|---|
| `study-guide.md` | The 16 canonical sections |
| `study-guide.pdf` | A typeset, paginated PDF with a table of contents |
| `chapter-notes.md` | One note per chapter, with page ranges or EPUB locators |
| `study-maps.json` | A validated concept graph — nodes and relationships |
| `claim-audit.json` | Every claim traced to its closest source, with overlap scores |
| `manifest.json` | Source SHA-256, model, thresholds, categories passed |
| `evaluations.json` | Full review history, including failures |
| `usage.json` | Calls and tokens, for cost accounting |
| `preflight.json` | The cost estimate and the work-batch plan |

### Time saved

Measured, not asserted. Pages-per-book and words-per-page come from **25 real
books, 8,170 pages**, measured with `tools/measure_books.py`: a median of **321
words per page** and **257 pages per book**. Reading speed and digest time are
stated assumptions. Re-run the model yourself:

```bash
python tools/measure_books.py    # the corpus
python tools/time_model.py       # the arithmetic
```

**Per book** — a median book is 82,497 words:

| | |
|---|---|
| Time to read it (250 wpm) | **5.5 hours** (330 min) |
| Time with Bookroom (10 min digest + 10 min review) | **20 minutes** |
| **Saved per book** | **≈ 5.2 hours** |

**Per year**, at your habit of 10 pages a day (3,650 pages/year ≈ 14.2 books):

| | |
|---|---|
| **Time saved per year** | **≈ 73 hours** |
| As working days (8 h) | **≈ 9.2 days** |
| As calendar days (24 h) | **≈ 3.1 days** |

Range, because books and readers vary:

| Scenario | Read time | Saved/book | Books/yr | Saved/yr |
|---|---|---|---|---|
| Short book, fast reader (150 pp, 300 wpm) | 2.7 h | 2.3 h | 24.3 | ≈ 57 h |
| **Median book, average reader (257 pp, 250 wpm)** | **5.5 h** | **5.2 h** | **14.2** | **≈ 73 h** |
| Long book, careful reader (500 pp, 200 wpm) | 13.4 h | 13.0 h | 7.3 | ≈ 95 h |

**What this claim does and does not mean.** It is *replacement* time: the hours
you would have spent reading a book you only needed summarised. It is not a
claim that you stop reading — the books that deserve a full read still deserve
one. The larger benefit is **coverage**: 14 books a year leave behind 14
structured, searchable, auditable artifacts instead of 14 fading impressions.

### Verification

Every suite runs against a real book with a local provider mock that speaks the
actual Gemini and JEv wire formats, so nothing is simulated and no credits are
spent.

| Suite | Checks | What it proves |
|---|---|---|
| `verify_clean_install.py` | 17 | A fresh venv installs the package and runs a book with no checkout, no `PYTHONPATH`, no `BOOKROOM_APP_ROOT` |
| `verify_sdk.py` | 68 | Extraction → guide → review → every export |
| `verify_facade.py` | 40 | Every HTTP route, auth, and error mapping |
| `verify_examples.py` | 15 | The shipped examples and CLI actually run |
| `verify_typescript.py` | 53 | The compiled TS client against the live facade |
| `npm test` | 41 | ESM/CJS interop, retries, timeouts, error mapping |
| `verify_equivalence.py` | — | The SDK and the engine's own code path produce identical artifacts and identical call counts |

**Measured equivalence**: on a real book, the SDK path and the engine's own path
produced a **100% prose match**, identical section counts, and **identical
provider calls (16 calls / 2,322 tokens)**. The SDK is a wrapper, not a
reimplementation.

**Known limitation, stated plainly:** the end-to-end run against a **live**
provider has not completed — the provider returned HTTP 429 with a multi-hour
retry window. The suites prove packaging, the pipeline, the exports and wrapper
equivalence. They do **not** yet prove summary *quality* against a live model.
`retry_run.py` resumes from the last checkpoint when quota returns.

---

## How it works

```
source book (EPUB / PDF)
        |
        v
   extraction ......... outline, page ranges, locators, optional Tesseract OCR
        |
        v
  preflight .......... cost estimate; budget caps enforced BEFORE any paid call
        |
        v
 chapter notes ....... one per chapter, each independently reviewed
        |
        v
  digest ............. the remaining 15 sections, generated separately
        |
        v
  quality gate ....... JEv scores all 16; bounded revisions; failures retained
        |
        v
   exports ........... md, pdf, graph, claims, manifest, usage
```

Two properties that matter in production:

**Checkpointing.** Every stage is saved as it completes. An interrupted or
quota-paused run **resumes from the last finished stage** rather than paying
twice.

**Honest failure.** A category that stays below threshold is kept with its
history. Low claim-audit overlap is flagged for a human, never auto-rejected.
The `claim-audit` is *lexical overlap, not fact-checking* — the README will
not pretend otherwise.

---

## API surface

39 capabilities, reachable from every supported language.

| Namespace | Python | TypeScript |
|---|---|---|
| Extract | `extract`, `extract_epub`, `extract_pdf`, `outline`, `ocr_languages`, `metadata` | `extract`, `metadata`, `outline` |
| Summarize | `preflight`, `summarize_section`, `summarize_sections`, `summarize_text`, `digest`, `study_guide` | `preflight`, `summarizeSection`, `summarizeText`, `digest`, `studyGuide` |
| Review | `evaluate`, `evaluate_section`, `report_sections`, `review_report`, `evaluations`, `manifest`, `audit_claims` | `evaluate`, `evaluateSection`, `report`, `evaluations` |
| Export | `pdf`, `markdown`, `validate`, `render_report`, `concept_map`, `claim_audit`, `usage`, `artifacts`, `merge_markdown` | `pdf`, `markdown`, `validate`, `render`, `conceptMap`, `claimAudit`, `manifest`, `usage`, `artifacts`, `merge` |
| Health | `check`, `check_cached` | `check`, `ping`, `describe`, `capabilities`, `sections` |
| Jobs | checkpointed by default | `create`, `studyGuide`, `list`, `get`, `delete`, `waitFor` |
| Legacy | `translate`, `translate_batch`, `classify_chapters`, `extract_notes` | `translate`, `translateBatch`, `classify`, `notes` |

Full reference: [Python README](python/README.md) · [TypeScript README](typescript/README.md).

---

## Errors

Python raises a stable hierarchy, so you never catch an application internal:

```python
from bookroom_sdk import errors

try:
    report = room.summarize.study_guide("scanned.pdf")
except errors.QuotaError as exc:
    print("resume in", exc.retry_after_seconds, "seconds")   # re-run to continue
except errors.BudgetExceededError:
    print("raise the cap, or split the book")
except errors.UnsupportedSourceError as exc:
    print("needs .pdf or .epub:", exc)
```

`ConfigError` · `UnsupportedSourceError` · `ExtractionError` ·
`BudgetExceededError` · `ValidationError` · `QuotaError` · `ProviderError` ·
`CancelledError` · `JobError`

TypeScript throws `BookroomError` with `code` and `status`, plus guards:
`isQuotaError`, `isBudgetExceededError`, `isUnsupportedSourceError`,
`isExtractionFailedError`, `isProviderError`, `isUnauthorizedError`,
`isNotFoundError`, `isTimeoutError`, `isRetryableError` and more. Retries happen
on 429 and 5xx only, honouring `retry_after_seconds`.

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The one
rule: **never commit a credential or copyrighted book content.**

```bash
python verify_sdk.py && python verify_facade.py && npm test
```

## Security

[SECURITY.md](SECURITY.md) documents the threat model. In short: provider keys
never reach a browser, `.env` is git-ignored, and the facade's artifact download
route is confined to the report's own directory. **The facade has no user
authentication beyond its token** — bind it to loopback and put real
authorization in front of it before exposing it.

## License

[MIT](LICENSE) © 2026 Vazghen Vardanian. Cite with [CITATION.cff](CITATION.cff).

<div align="center">
  <sub>
    Built for people who have more books than time — and would rather know
    which ones deserve the time.
  </sub>
</div>
