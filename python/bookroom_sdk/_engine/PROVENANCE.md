# Bundled engine

These files are the Bookroom summarization engine, vendored into the SDK
package so that `pip install bookroom-sdk` is sufficient on its own. There is
no separate checkout to clone, no `PYTHONPATH` to set, and no
`BOOKROOM_APP_ROOT` to configure.

## Why they look like loose modules

The engine is a flat tree of top-level modules that import each other by bare
name — `book_pipeline.py` does `from gemini_provider import generate`, and
`gemini_provider.py` does not know it lives inside a package. Renaming or
relocating them would mean rewriting the engine, which would defeat the point
of shipping an unmodified copy.

So this directory is deliberately **not** a Python package (there is no
`__init__.py`). `bookroom_sdk.bootstrap` puts this directory on `sys.path` at
load time, and the modules import normally from there. Upgrading the engine is
therefore a file copy, never a merge.

## What is included, and what is not

The SDK needs 19 modules. They are listed here so the set is auditable rather
than accidental:

`book_pipeline`, `claim_audit`, `cost_estimation`, `epub_extractor`,
`gemini_provider`, `jev`, `llm`, `map_export`, `merge_markdowns`, `pdf_export`,
`pdf_extractor`, `prompts`, `provider_health`, `quality_gate`, `report_format`,
`report_manifest`, `resumable_pipeline`, `translate`, `utils`

Deliberately **excluded** — they belong to the hosted web application, not the
SDK, and they pull in Clerk, Prisma, PostgreSQL, S3 and a React frontend:

`artifact_storage`, `calibrate_quality`, `clerk_auth`, `database_config`,
`frontend_server`, `improvement_evaluation`, `job_store`, `main`,
`migrate_postgres`, `prepare_quality_review`, `production_config`,
`rerun_quality_gate`, `webapp`, `webapp_jev`, `worker`, `worker_control`

The included set is derived from the actual import closure of the modules the
SDK calls, not chosen by hand. Re-derive it before upgrading the engine.

## Overriding the engine

The bundled copy is always used unless you explicitly set `BOOKROOM_APP_ROOT`
to a different directory containing `book_pipeline.py`. That is the supported
way to develop against a live checkout, or to pin a specific engine build:

```python
room = Bookroom.from_env(app_root=r"D:\path\to\engine\src")
```

`room.app_root` reports which engine is actually loaded, and
`room.describe()["config"]["app_root"]` is safe to log.

## Updating

Replace the files, then run the SDK's verification suites before committing:

```
python verify_sdk.py          # in-process behaviour
python verify_facade.py       # the HTTP surface
python verify_equivalence.py <book>   # SDK vs the engine's own path
```
