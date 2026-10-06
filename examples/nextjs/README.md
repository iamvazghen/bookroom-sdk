# Next.js example (App Router)

A Next.js 15 app that shows both halves of the SDK integration:

- **Route handler** — `app/api/bookroom/[...path]/route.ts` proxies the browser's
  calls to the facade and attaches the token.
- **Server actions** — `app/actions.ts` calls the facade directly, so the token
  never crosses the boundary at all.

`app/page.tsx` is a client component that uses `useBookroomJob` and
`StudyGuidePanel` against the route handler, and a server action against the
other half.

## Requirements

- Node 20 or newer.
- A running Bookroom facade.
- The SDK installed and built.

## Setup

```bash
cd ../..
npm install
npm run build

cd examples/nextjs
npm install
```

## Configure

Copy `.env.example` to `.env.local` and fill it in, or export the variables:

```bash
BOOKROOM_URL=http://127.0.0.1:8787
BOOKROOM_FACADE_TOKEN=your-facade-token
```

**`BOOKROOM_FACADE_TOKEN` belongs on the server.** A `NEXT_PUBLIC_`-prefixed
variable is inlined into the browser bundle, so never name it that. It is read
only by `getServerBookroom()`, which runs inside a route handler or a server
action. Only the facade's token is needed here — the LLM and JEv keys stay inside
the facade process.

Start the facade with the same token:

```bash
python -m bookroom_sdk serve --host 127.0.0.1 --port 8787 --token "$BOOKROOM_FACADE_TOKEN"
```

## Run

```bash
npm run dev
```

Open <http://127.0.0.1:3000>, enter a book path, and start a run.

```bash
npm run build && npm start    # production
npm run typecheck             # tsc --noEmit
```

## Files

| File | What it shows |
| --- | --- |
| `app/layout.tsx` | Server component; owns the metadata |
| `app/page.tsx` | Client component: `useBookroomClient`, `BookroomProvider`, `useBookroomJob`, `StudyGuidePanel`, plus a server-action panel |
| `app/actions.ts` | `'use server'`; `createSummarizeAction()`, `createJobStatusAction()`, `createPreflightAction()` |
| `app/api/bookroom/[...path]/route.ts` | The proxy the browser hooks call, built on `handleBookroomRequest` |
| `app/api/jobs/[id]/route.ts` | A trimmed job snapshot via `getJobForClient` |
| `app/globals.css` | Plain CSS, no Tailwind |

## How the two halves differ

**Route handler** (`handleBookroomRequest`). It gives you a token-bearing client,
awaits route params for you (Next.js 15 passes them as a promise), and turns a
thrown `BookroomError` into the right status:

| Error | Status |
| --- | --- |
| `not_found` | 404 |
| `conflict`, `cancelled` | 409 |
| `unauthorized` | 401 |
| `unsupported_source` | 415 |
| `quota_exceeded` | 429, with a `Retry-After` header |
| `network_error`, `invalid_response` | 502 |
| `configuration_error` | 503 |

The body is always `{ "error": { name, code, status, message } }`, with `trace`,
`type`, `url`, and `method` removed.

**Server action** (the `create*Action` factories). Returns instead of throwing,
because a rejected action reaches the browser as a framework error page with a
digest rather than a usable message:

```ts
const result = await startStudyGuide({ path: '/books/attention.epub' });
if (result.ok) console.log(result.data.id);
else console.error(result.error.code, result.error.message);
```

## Two levels of detail

The catch-all route forwards job snapshots in the facade's own shape, because the
browser SDK reads `job.result` to render the report — and that `result` still
contains server-side file paths. Fine for a local tool.

`app/api/jobs/[id]/route.ts` is the stricter version: `getJobForClient(id, {
exposePaths: false })` replaces `result` with a summary and sends no paths at all.
Use that shape for anything reachable from the internet, and add an `artifactHref`
builder so links point at a download route you own.

## What was verified

- `tsc --noEmit` over `app/` with `strict: true`: clean.
- Both route handlers and `app/actions.ts` were included in that check.

**Not verified:** `npm install`, `next build`, `next dev`, and an actual browser
run. Next.js is not installed in the verification environment, so its own types
were stubbed and the build was never executed. The route handlers' runtime
behavior — params, status mapping, token injection — has therefore been reasoned
about and typechecked, but not run.