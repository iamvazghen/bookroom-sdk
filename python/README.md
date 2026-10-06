# Bookroom — Python SDK

Turn an EPUB or PDF into a complete, independently reviewed study guide, from
your own code. The engine ships inside this package, so installing it is the
whole setup: **no separate checkout, no `PYTHONPATH`, no `BOOKROOM_APP_ROOT`.**

[![PyPI](https://img.shields.io/pypi/v/bookroom-sdk?logo=pypi&color=blue)](https://pypi.org/project/bookroom-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Install

```bash
pip install bookroom-sdk
```

With the alternate Ollama/OpenRouter transport (translation, chapter
classification):

```bash
pip install "bookroom-sdk[legacy]"
```

Installs a `bookroom` console command:

```bash
bookroom --version
bookroom extract book.epub --text
bookroom guide book.epub --out ./out
bookroom serve --port 8787 --token "$TOKEN"   # HTTP facade for other languages
```

## The two-key rule

You supply exactly two values. Everything else is defaulted and overridable.

| Key | Required? | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | **yes** | Generation |
| `TYPESAFE_API_KEY` | for review | JEv review. Omit it and review is skipped, and the run says so |

```python
from bookroom_sdk import Bookroom

room = Bookroom.from_env()      # reads the two keys from the environment
# or explicitly:
room = Bookroom(llm_api_key="...", jev_api_key="...")

room.check()                    # credentials, before you spend anything
plan = room.summarize.preflight("book.epub")   # cost estimate, before you spend anything
report = room.summarize.study_guide("book.epub")

print(report.markdown.path)      # study-guide.md
print(report.pdf.path)           # study-guide.pdf
print(report.quality.as_dict())  # 16 categories, scores, pass counts
```

`room.describe()` returns the full configuration — endpoints, models,
thresholds, budget caps — with **no secret values**, so it is safe to log.

## What you get

Nine artifacts per run: `study-guide.md`, `study-guide.pdf`,
`chapter-notes.md`, `study-maps.json` (a validated concept graph),
`claim-audit.json`, `manifest.json`, `evaluations.json`, `usage.json`,
`preflight.json`.

Two properties that matter in production:

- **Checkpointed.** Every stage is saved as it completes, so an interrupted or
  quota-paused run resumes from the last finished stage instead of paying twice.
- **Honest failure.** Categories below the review threshold are kept with their
  full history, never hidden. The claim audit is *lexical overlap, not
  fact-checking*, and is documented as such.

## API

39 capabilities under six namespaces:

| Namespace | Methods |
|---|---|
| `room.extract` | `extract`, `extract_epub`, `extract_pdf`, `outline`, `ocr_languages`, `metadata` |
| `room.summarize` | `preflight`, `summarize_section`, `summarize_sections`, `summarize_text`, `digest`, `study_guide` |
| `room.review` | `evaluate`, `evaluate_section`, `report_sections`, `review_report`, `evaluations`, `manifest`, `audit_claims` |
| `room.export` | `pdf`, `markdown`, `validate`, `render_report`, `concept_map`, `claim_audit`, `usage`, `artifacts`, `merge_markdown` |
| `room.health` | `check`, `check_cached` |
| `room.translate` | `translate`, `translate_batch`, `classify_chapters`, `extract_notes` |

## Errors

A stable hierarchy, so you never catch an application internal:

```python
from bookroom_sdk import errors

try:
    report = room.summarize.study_guide("scanned.pdf")
except errors.QuotaError as exc:
    print("resume in", exc.retry_after_seconds, "seconds")   # re-run to continue
except errors.BudgetExceededError:
    print("raise the cap, or split the book")
```

`ConfigError` · `UnsupportedSourceError` · `ExtractionError` ·
`BudgetExceededError` · `ValidationError` · `QuotaError` · `ProviderError` ·
`CancelledError` · `JobError`

## Non-Python clients

Run the facade, which ships with this package, and point the TypeScript, React
or Next.js client at it. **The provider keys stay in the facade process**; the
client sends only the facade token.

```bash
bookroom serve --host 127.0.0.1 --port 8787 --token "$BOOKROOM_FACADE_TOKEN"
```

The facade has no user authentication beyond its token. Bind it to loopback and
put real authorization in front of it before exposing it — see
[SECURITY.md](https://github.com/iamvazghen/bookroom-sdk/blob/main/SECURITY.md).

## Documentation

- [Full README](https://github.com/iamvazghen/bookroom-sdk#readme)
- [`SKILL.md`](https://github.com/iamvazghen/bookroom-sdk/blob/main/SKILL.md) — integration guide for AI agents
- [Security model](https://github.com/iamvazghen/bookroom-sdk/blob/main/SECURITY.md)
- [Contributing](https://github.com/iamvazghen/bookroom-sdk/blob/main/CONTRIBUTING.md)

## License

[MIT](https://github.com/iamvazghen/bookroom-sdk/blob/main/LICENSE) © 2026 Vazghen Vardanian
