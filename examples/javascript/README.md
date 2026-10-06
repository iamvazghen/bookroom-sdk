# JavaScript example

The same flow as `examples/typescript`, written in plain ESM JavaScript. There is
no TypeScript here: the shapes live in JSDoc comments, so an editor and
`tsc --checkJs` still catch a wrong argument or a renamed option, while the file
runs directly on Node with no build step.

## Requirements

- Node 20 or newer.
- A running Bookroom facade.
- The SDK installed and built.

## Setup

```bash
cd ../..
npm install
npm run build

cd examples/javascript
npm install
```

To run against a local checkout rather than the registry:

```bash
npm link ../..
```

## Configure

```bash
export BOOKROOM_URL=http://127.0.0.1:8787
export BOOKROOM_FACADE_TOKEN=your-facade-token
export BOOKROOM_PATH=/books/attention.epub   # optional; --path also works
```

**`BOOKROOM_FACADE_TOKEN` belongs on a server.** It is a bearer credential that
anyone holding can spend your provider quota. This script runs on Node, so reading
it from the environment is correct. Never ship it to a browser. Only the facade's
token is needed; the LLM and JEv keys stay inside the facade process.

## Run

```bash
npm start -- --path /books/attention.epub
```

Or run the file directly, with no npm script in the way:

```bash
node src/study-guide.mjs --path /books/attention.epub
```

Flags are identical to the TypeScript example: `--path`, `--slug`, `--base-url`,
`--poll-ms`, `--no-review`, `--skip-check`, `--skip-preflight`.

## Typecheck the JSDoc

```bash
npm run typecheck
```

`tsconfig.json` sets `allowJs` and `checkJs`, so this is a real typecheck of the
JavaScript, not a parse. It maps `bookroom-sdk` to `../../src/index.js` so it works
against the local source tree; remove that `paths` entry once the package is
installed.

## What was verified

- `tsc -p tsconfig.json` with `checkJs: true` and `strict: true`: clean.
- `node --check src/study-guide.mjs`: clean.
- The file was executed end to end against a local stub facade: exit code 0, with
  the report summary and all artifacts printed. The executed copy was
  byte-identical to the shipped file (same SHA-256).
- Failure paths: a wrong token printed
  `BookroomError [unauthorized] HTTP 401`; an unreachable facade printed
  `BookroomNetworkError [network_error]`. Both exited 1.

It has **not** been run against a real facade with real provider keys, because
that would spend credits.