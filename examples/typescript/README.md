# TypeScript example

A typed Node script that drives one complete study-guide run through the SDK:
`describe()` → `check()` → `preflight()` → `jobs.studyGuide()` → `jobs.waitFor()` →
print the report and its artifacts.

## Requirements

- Node 20 or newer.
- A running Bookroom facade.
- The SDK installed and built (see below).

## Setup

From the repository root, build the SDK first:

```bash
cd ../..
npm install
npm run build
```

Then install and build this example:

```bash
cd examples/typescript
npm install
```

`npm install` pulls `bookroom-sdk` from the registry. To run against your local
checkout instead, link it:

```bash
npm install
npm link ../..          # from this directory, once the SDK is built
```

## Configure

```bash
export BOOKROOM_URL=http://127.0.0.1:8787
export BOOKROOM_FACADE_TOKEN=your-facade-token   # only if you started the facade with --token
export BOOKROOM_PATH=/books/attention.epub      # optional; --path also works
```

**`BOOKROOM_FACADE_TOKEN` belongs on a server.** It is a bearer credential: anyone
who has it can spend your provider quota. This script runs on Node, so reading it
from the environment is correct. Never copy it into a browser bundle, a
`NEXT_PUBLIC_` variable, or a client-side `.env`. Only the facade's own token is
needed here — the LLM and JEv keys stay inside the facade process.

Start the facade with the same token:

```bash
python -m bookroom_sdk serve --host 127.0.0.1 --port 8787 --token "$BOOKROOM_FACADE_TOKEN"
```

## Run

```bash
npm run build
npm start -- --path /books/attention.epub
```

Flags:

| Flag | Meaning |
| --- | --- |
| `--path <path>` | Book to summarize. Falls back to `BOOKROOM_PATH`. |
| `--slug <name>` | Output folder name. The server picks one when omitted. |
| `--base-url <url>` | Facade URL. Falls back to `BOOKROOM_URL`, then `http://127.0.0.1:8787`. |
| `--poll-ms <n>` | Milliseconds between polls. Defaults to 1500. |
| `--no-review` | Skip the JEv quality gate. |
| `--skip-check` | Skip the provider health probe. |
| `--skip-preflight` | Skip the cost estimate. |

A full run takes minutes. Press Ctrl-C to stop waiting; the job keeps going on the
server.

## Typecheck

```bash
npm run typecheck
```

The bundled `tsconfig.json` maps `bookroom-sdk` to `../../src/index.js`, so the
example typechecks against the local source tree before the package is published.
Once you install the real package, delete that `paths` entry.

## What was verified

- `tsc --noEmit` against the SDK source tree: clean.
- The compiled script was executed end to end against a local stub facade that
  mimics the real routes (`/v1/describe`, `/v1/check`, `/v1/preflight`,
  `POST /v1/jobs`, `GET /v1/jobs/{id}`): exit code 0, with the report summary and
  all five artifacts printed.
- The failure paths were exercised too: a wrong token produced
  `BookroomError [unauthorized] HTTP 401`, and an unreachable facade produced
  `BookroomNetworkError [network_error]`. Both exited 1.

It has **not** been run against a real facade with real provider keys, because
that would spend credits.