'use client';

/**
 * The page, as a client component.
 *
 * It shows the two halves of the integration working side by side:
 *
 * 1. **Route handler** — the hooks below call this app's own
 *    `/api/bookroom` route, which forwards to the facade with the token.
 * 2. **Server action** — `jobStatus` is imported from `./actions`, so its body
 *    runs on the server and only its return value crosses back.
 *
 * `useBookroomClient` is given the path `/api/bookroom`; the hook resolves it
 * against the page's own origin, so no URL or token is baked into the bundle.
 */

import { useState } from 'react';
import type { ReactElement } from 'react';
import {
  BookroomProvider,
  StudyGuidePanel,
  useBookroomClient,
  useBookroomJob,
} from 'bookroom-sdk/react';

import { jobStatus, startStudyGuide } from './actions';
import type { ClientJob } from 'bookroom-sdk/next';

const POLL_INTERVAL_MS = 1500;

export default function Page(): ReactElement {
  const client = useBookroomClient({ baseUrl: '/api/bookroom' });
  const [path, setPath] = useState('/books/attention.epub');
  const [review, setReview] = useState(true);

  return (
    <BookroomProvider client={client}>
      <main className="page">
        <header className="page__header">
          <h1 className="page__title">Bookroom study guide</h1>
          <p className="page__subtitle">
            The browser talks to <code>/api/bookroom</code>. The token lives only in the server
            runtime, read from <code>BOOKROOM_FACADE_TOKEN</code>.
          </p>
        </header>

        <section className="controls">
          <label className="controls__field">
            <span className="controls__label">Book path on the server</span>
            <input
              className="controls__input"
              value={path}
              onChange={(event) => setPath(event.target.value)}
              placeholder="/books/title.epub"
              spellCheck={false}
            />
          </label>
          <label className="controls__check">
            <input
              type="checkbox"
              checked={review}
              onChange={(event) => setReview(event.target.checked)}
            />
            <span>Run the JEv quality gate</span>
          </label>
        </section>

        <section className="stack">
          <div className="stack__heading">
            <h2>Through a route handler</h2>
            <p>
              <code>useBookroomJob</code> drives the job; <code>StudyGuidePanel</code> is the
              ready-made version of the same hook.
            </p>
          </div>
          <HookJob path={path} review={review} />
          <StudyGuidePanel
            title="StudyGuidePanel"
            path={path}
            review={review}
            pollIntervalMs={POLL_INTERVAL_MS}
          />
        </section>

        <section className="stack">
          <div className="stack__heading">
            <h2>Through a server action</h2>
            <p>
              The same job, started by a server action. The action body never leaves the server,
              so it can read the token directly.
            </p>
          </div>
          <ActionStudyGuide path={path} review={review} />
        </section>
      </main>
    </BookroomProvider>
  );
}

/**
 * The hook half, driven by hand.
 *
 * `useBookroomJob` is the whole state machine; this component only decides what
 * it looks like, and shows the job id that the server action below re-reads.
 */
function HookJob({ path, review }: { path: string; review: boolean }): ReactElement {
  const job = useBookroomJob({ path, review, pollIntervalMs: POLL_INTERVAL_MS });
  return (
    <section className="panel">
      <div className="panel__row">
        <button
          type="button"
          className="button"
          onClick={() => void job.start()}
          disabled={job.isRunning || path.trim() === ''}
        >
          {job.isRunning ? 'Generating…' : 'Start via route handler'}
        </button>
        {job.isRunning ? (
          <button type="button" className="button button--ghost" onClick={job.cancel}>
            Stop watching
          </button>
        ) : null}
        <span className={`chip chip--${job.status}`}>{job.status}</span>
        <code className="panel__job">{job.jobId ?? 'no job yet'}</code>
      </div>
      {job.error !== null ? (
        <p className="alert alert--error">
          <strong>{job.error.code}</strong> (HTTP {job.error.status}): {job.error.message}
        </p>
      ) : null}
      {job.result !== null ? (
        <p className="hint">
          {job.result.document.title} · {job.result.document.section_count} sections ·{' '}
          {job.result.document.total_words.toLocaleString('en-US')} words
        </p>
      ) : null}
    </section>
  );
}

/**
 * The server-action half.
 *
 * A React server action imported into a client component is a reference, not an
 * import of the body: `startStudyGuide` runs on the server and returns plain
 * data. The result is a discriminated union, so a failure is a value to render
 * rather than an exception.
 */
function ActionStudyGuide({ path, review }: { path: string; review: boolean }): ReactElement {
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState<ClientJob | null>(null);
  const [status, setStatus] = useState<ClientJob | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  async function start(): Promise<void> {
    setBusy(true);
    setFailure(null);
    const result = await startStudyGuide({ path, review });
    setBusy(false);
    if (result.ok) {
      setStarted(result.data);
      setStatus(result.data);
    } else {
      setFailure(`${result.error.code} (HTTP ${result.error.status}): ${result.error.message}`);
    }
  }

  async function refresh(): Promise<void> {
    if (started === null) return;
    setBusy(true);
    const result = await jobStatus({ id: started.id });
    setBusy(false);
    if (result.ok) {
      setStatus(result.data);
      setFailure(null);
    } else {
      setFailure(`${result.error.code} (HTTP ${result.error.status}): ${result.error.message}`);
    }
  }

  return (
    <section className="panel">
      <div className="panel__row">
        <button
          type="button"
          className="button"
          onClick={() => void start()}
          disabled={busy || path.trim() === ''}
        >
          {busy ? 'Working…' : 'Start via server action'}
        </button>
        {started !== null ? (
          <button type="button" className="button button--ghost" onClick={() => void refresh()}>
            Refresh status
          </button>
        ) : null}
        {status !== null ? <span className={`chip chip--${status.status}`}>{status.status}</span> : null}
      </div>

      {failure !== null ? <p className="alert alert--error">{failure}</p> : null}

      {status !== null ? (
        <dl className="report__grid">
          <dt>Job</dt>
          <dd>
            <code>{status.id}</code>
          </dd>
          <dt>Status</dt>
          <dd>{status.status}</dd>
          <dt>Messages</dt>
          <dd>{status.message_count}</dd>
          <dt>Report</dt>
          <dd>
            {status.report === null
              ? 'not finished yet'
              : `${status.report.title} · ${status.report.section_count} sections · ${status.report.quality === null ? 'not reviewed' : `${status.report.quality.categories_passed}/${status.report.quality.categories_reviewed} categories passed`}`}
          </dd>
        </dl>
      ) : (
        <p className="hint">
          The action returns a trimmed payload: no server traceback, and no filesystem paths.
        </p>
      )}
    </section>
  );
}