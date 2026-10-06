# React example (Vite)

A browser app that generates study guides. The page uses the React bindings from
`bookroom-sdk/react`, and a small Express proxy in `server.mjs` is the only
process that ever sees the facade token.

## The shape of it

```
browser (Vite :5173)  ──►  /api/bookroom/v1/...  ──►  server.mjs (:8788)  ──►  facade (:8787)
   no token, no URL        same origin in dev         BOOKROOM_FACADE_TOKEN      BOOKROOM_URL
```

`useBookroomClient({ baseUrl: '/api/bookroom' })` builds a client pointed at this
app's own path. The proxy adds `Authorization: Bearer <token>` on the way out and
strips `trace`, `type`, and internal URLs from error bodies on the way back.

## Requirements

- Node 20 or newer.
- A running Bookroom facade.
- The SDK installed and built.

## Setup

```bash
cd ../..
npm install
npm run build

cd examples/react
npm install
```

## Configure

```bash
export BOOKROOM_URL=http://127.0.0.1:8787
export BOOKROOM_FACADE_TOKEN=your-facade-token
```

**`BOOKROOM_FACADE_TOKEN` belongs in `server.mjs` and nowhere else.** Anything
prefixed `VITE_` is inlined into the browser bundle, so never name it that; there
is no `VITE_` variable in this example on purpose. The page itself knows only the
path `/api/bookroom`. Only the facade's token is needed here — the LLM and JEv
keys stay inside the facade process.

Start the facade with the same token:

```bash
python -m bookroom_sdk serve --host 127.0.0.1 --port 8787 --token "$BOOKROOM_FACADE_TOKEN"
```

## Run it

Two terminals.

```bash
# terminal 1 — the token-holding proxy
npm run proxy
```

```bash
# terminal 2 — the app, forwarding /api/bookroom to the proxy
npm run dev
```

Open <http://127.0.0.1:5173>, type a book path, and press a start button. A full
run takes minutes; the panel streams the server's progress messages while it waits.

To serve the built app from the same origin as the proxy, with no CORS setup:

```bash
npm run serve     # builds, then runs server.mjs on :8788
```

## Files

| File | What it shows |
| --- | --- |
| `src/App.tsx` | `useBookroomClient`, `BookroomProvider`, `useBookroomDescribe`, `StudyGuidePanel` |
| `src/CustomJobPanel.tsx` | `useBookroomJob` used directly, for your own markup |
| `src/main.tsx` | Mount point |
| `src/styles.css` | Plain CSS, no framework |
| `server.mjs` | The proxy, and the only reader of the token |
| `vite.config.ts` | Dev proxy from `/api/bookroom` to `server.mjs` |

The two panels are independent jobs against the same path, which is why each has
its own button. The facade serializes paid work behind a lock, so start one rather
than both.

## Artifact links

The facade serves artifact *metadata* but no file *bytes*, so it has no download
route. `StudyGuidePanel` takes an `artifactHref` builder for exactly this reason:

```tsx
<StudyGuidePanel path={path} artifactHref={(artifact) => `/api/files/${artifact.name}`} />
```

Without one, the panel prints each artifact's server path as text instead of
inventing a link.

## Uncontrolled and controlled modes

By default the panel manages its own job, which is what `App.tsx` and
`CustomJobPanel.tsx` use. Pass a `job` and it renders that hook result instead,
which is useful when the surrounding UI already owns the job:

```tsx
const job = useBookroomJob({ path: 'book.epub', pollIntervalMs: 1000 });
return <StudyGuidePanel job={job} path="book.epub" onStart={job.start} />;
```

## What was verified

- `tsc --noEmit` over `src/` with `strict: true`: clean.
- `node --check server.mjs`: clean.
- The React module was exercised for real outside the repo: `StudyGuidePanel`
  was server-rendered in both uncontrolled and controlled mode with
  `react-dom/server`, and 11 of 11 assertions passed (status, progress messages,
  report summary, artifact rendering, and `toBookroomError`).
- `vite.config.ts` was checked for syntax and semantics; its `vite` and
  `@vitejs/plugin-react` imports could not resolve because those packages are not
  installed in the verification environment.

**Not verified:** `npm install`, `vite build`, and an actual browser run. Those
need the dependencies installed, and a live facade, so the proxy path has not been
exercised end to end here.