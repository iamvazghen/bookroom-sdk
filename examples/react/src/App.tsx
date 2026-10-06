import { useMemo, useState } from 'react';
import type { ReactElement } from 'react';
import {
  BookroomProvider,
  StudyGuidePanel,
  useBookroomClient,
  useBookroomDescribe,
} from 'bookroom-sdk/react';

import { CustomJobPanel } from './CustomJobPanel';

/**
 * The whole page.
 *
 * `useBookroomClient` builds one client pointed at this app's own proxy, and
 * `BookroomProvider` shares it with everything below. Nothing here holds a token:
 * the proxy in `server.mjs` attaches `BOOKROOM_FACADE_TOKEN` on the way out.
 *
 * The page shows both ways to run a job:
 *
 * - `CustomJobPanel` drives `useBookroomJob` directly, for your own layout.
 * - `StudyGuidePanel` is the batteries-included version of the same hook.
 *
 * They are two independent jobs against the same book path, which is why each
 * has its own button. The facade serializes paid work behind a lock, so start
 * one or the other rather than both.
 */
export function App(): ReactElement {
  // `/api/bookroom` is a path, so the hook resolves it against this page's
  // origin. Pass an absolute URL instead when your proxy lives on another host.
  const client = useBookroomClient({ baseUrl: '/api/bookroom' });
  const [path, setPath] = useState('/books/attention.epub');
  const [review, setReview] = useState(true);

  const pollIntervalMs = 1500;
  const shared = useMemo(
    () => ({ path, pollIntervalMs, review, summarizeOptions: { language: 'English' } }),
    [path, pollIntervalMs, review],
  );

  return (
    <BookroomProvider client={client}>
      <main className="page">
        <header className="page__header">
          <h1 className="page__title">Bookroom study guide</h1>
          <ServerBanner />
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
          <p className="controls__hint">
            This path is resolved by the machine running the facade, not by your browser.
          </p>
        </section>

        <section className="stack">
          <div className="stack__heading">
            <h2>Batteries included</h2>
            <p>
              <code>StudyGuidePanel</code> wraps the same hook with status, progress, a
              report summary, and artifact links.
            </p>
          </div>
          <StudyGuidePanel
            title="StudyGuidePanel"
            startLabel="Generate with StudyGuidePanel"
            {...shared}
          />
        </section>

        <section className="stack">
          <div className="stack__heading">
            <h2>Bring your own layout</h2>
            <p>
              <code>useBookroomJob</code> exposes the raw state machine, so the markup can be
              whatever your design system wants.
            </p>
          </div>
          <CustomJobPanel title="CustomJobPanel" {...shared} />
        </section>
      </main>
    </BookroomProvider>
  );
}

/**
 * A one-shot `describe()` rendered as a small banner.
 *
 * `describe()` returns the server's configuration with every API key reduced to
 * a `*_api_key_set` boolean, so it is safe to show.
 */
function ServerBanner(): ReactElement {
  const { description, loading, error, reload } = useBookroomDescribe();

  if (loading) {
    return (
      <p className="banner banner--muted">
        Asking the server what it can do…
        <button type="button" className="linkbutton" onClick={reload}>
          retry
        </button>
      </p>
    );
  }
  if (error !== null) {
    return (
      <p className="banner banner--error">
        <strong>{error.code}</strong> (HTTP {error.status}): {error.message}
        <button type="button" className="linkbutton" onClick={reload}>
          retry
        </button>
      </p>
    );
  }
  if (description === null) return <></>;

  const config = description.config;
  return (
    <p className="banner">
      <span>
        facade <strong>{description.sdk_version}</strong>
      </span>
      <span>
        model <strong>{String(config.llm_model ?? 'unknown')}</strong>
      </span>
      <span>
        LLM key <strong>{config.llm_api_key_set === true ? 'set' : 'missing'}</strong>
      </span>
      <span>
        JEv <strong>{config.jev_enabled === true ? 'on' : 'off'}</strong>
      </span>
      <span>
        {description.capabilities.length} capabilities
      </span>
      <button type="button" className="linkbutton" onClick={reload}>
        refresh
      </button>
    </p>
  );
}