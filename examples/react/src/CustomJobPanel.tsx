import { useState } from 'react';
import type { ReactElement } from 'react';
import { useBookroomJob } from 'bookroom-sdk/react';
import type { Artifact, SummarizeOptions } from 'bookroom-sdk';

/** Props shared by both job examples on the page. */
export interface CustomJobPanelProps {
  title: string;
  path: string;
  review: boolean;
  pollIntervalMs: number;
  summarizeOptions: SummarizeOptions;
}

/**
 * The same job, driven by hand.
 *
 * `useBookroomJob` is the whole state machine: it creates the job, polls until
 * it finishes, and hands back status, progress messages, the finished report, and
 * a typed error. This component only decides what that looks like.
 */
export function CustomJobPanel(props: CustomJobPanelProps): ReactElement {
  const { title, path, review, pollIntervalMs, summarizeOptions } = props;
  const [showAllMessages, setShowAllMessages] = useState(false);

  const job = useBookroomJob({ path, review, pollIntervalMs, summarizeOptions });

  const visibleMessages = showAllMessages ? job.messages : job.messages.slice(-6);
  const hiddenCount = job.messages.length - visibleMessages.length;
  const report = job.result;

  return (
    <section className="panel">
      <header className="panel__header">
        <h3 className="panel__title">{title}</h3>
        <code className="panel__job">
          {job.jobId ?? 'no job yet'}
          {job.snapshot === null ? '' : ` · ${job.snapshot.message_count} messages`}
        </code>
      </header>

      <div className="panel__row">
        <button
          type="button"
          className="button"
          onClick={() => void job.start()}
          disabled={job.isRunning || path.trim() === ''}
        >
          {job.isRunning ? 'Generating…' : 'Start job'}
        </button>
        {job.isRunning ? (
          <button type="button" className="button button--ghost" onClick={job.cancel}>
            Stop watching
          </button>
        ) : null}
        <span className={`chip chip--${job.status}`}>{job.status}</span>
        {job.jobId !== null && !job.isRunning ? (
          <button type="button" className="button button--ghost" onClick={job.reset}>
            Reset
          </button>
        ) : null}
      </div>

      {job.isRunning ? (
        <p className="hint">
          The facade reports progress as messages, not a percentage, so the bar would be
          a guess. Message {job.messages.length}.
        </p>
      ) : null}

      {job.error !== null ? (
        <p className="alert alert--error">
          <strong>{job.error.code}</strong> (HTTP {job.error.status}): {job.error.message}
          {job.error.retryAfterSeconds === undefined
            ? ''
            : ` Retry after ${job.error.retryAfterSeconds}s.`}
        </p>
      ) : null}

      {job.messages.length > 0 ? (
        <div className="messages">
          {hiddenCount > 0 ? (
            <button
              type="button"
              className="linkbutton"
              onClick={() => setShowAllMessages(true)}
            >
              show {hiddenCount} earlier message{hiddenCount === 1 ? '' : 's'}
            </button>
          ) : null}
          <ol className="messages__list">
            {visibleMessages.map((message, index) => (
              <li key={`${job.jobId ?? 'job'}-${index}`}>{message}</li>
            ))}
          </ol>
        </div>
      ) : null}

      {report !== null ? (
        <div className="report">
          <h4 className="report__title">{report.document.title}</h4>
          <dl className="report__grid">
            <dt>Format</dt>
            <dd>{report.document.kind}</dd>
            <dt>Sections</dt>
            <dd>{report.document.section_count}</dd>
            <dt>Words</dt>
            <dd>{report.document.total_words.toLocaleString('en-US')}</dd>
            <dt>Output</dt>
            <dd>
              <code>{report.output_dir}</code>
            </dd>
          </dl>

          <ul className="artifacts">
            {report.artifacts.map((artifact: Artifact) => (
              <li key={artifact.name}>
                <span className={artifact.exists ? 'artifacts__name' : 'artifacts__name artifacts__name--missing'}>
                  {artifact.name}
                </span>
                <span className="artifacts__meta">
                  {artifact.media_type}
                  {artifact.path === null ? '' : ` · ${artifact.path}`}
                </span>
              </li>
            ))}
          </ul>
          <p className="hint">
            Paths are server-side. A public app would serve the files itself and pass an
            <code> artifactHref</code> builder to link them.
          </p>
        </div>
      ) : null}
    </section>
  );
}