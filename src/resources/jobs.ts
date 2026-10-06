/**
 * Background jobs: start a long run, poll it, and collect the result.
 *
 * A study guide can take minutes. `POST /v1/jobs` returns immediately with an
 * id, and the same work happens on the server while the caller polls — which
 * fits a request handler, a queue worker, or a CLI that can be interrupted.
 */

import { BookroomAbortError, BookroomJobError, BookroomTimeoutError } from '../errors.js';
import type { CallOptions, HttpTransport } from '../http.js';
import { isSignalAborted } from '../http.js';
import type {
  JobKind,
  JobSnapshot,
  Report,
  ReviewRecord,
  SummarizeOptions,
  TerminalJobStatus,
} from '../types.js';

/** Arguments for {@link JobsApi.create}. */
export interface CreateJobRequest {
  kind: JobKind;
  /** Source book, on the server's filesystem. */
  path: string;
  options?: SummarizeOptions;
  outputSlug?: string;
  review?: boolean;
}

/** Arguments for {@link JobsApi.reviewReport}. */
export interface ReviewReportJobRequest {
  reportPath: string;
  /**
   * Book to review against.
   *
   * The facade requires a `path` on every job; for a review-report job it only
   * needs the field to be present, and defaults to the report path when
   * omitted.
   */
  path?: string;
}

/** Options for {@link JobsApi.waitFor}. */
export interface WaitForJobOptions extends CallOptions {
  /** Delay between polls in milliseconds. Defaults to 500. */
  pollIntervalMs?: number;
  /** Give up after this many milliseconds. Defaults to the long-run timeout. */
  timeoutMs?: number;
  /** Called after every poll, so a CLI can show progress. */
  onUpdate?: (job: JobSnapshot) => void;
  /** Ask the server to include progress messages. Defaults to true. */
  messages?: boolean;
}

/** True for a job that has finished, one way or another. */
export function isTerminalStatus(status: JobSnapshot['status']): status is TerminalJobStatus {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled';
}

/** Job calls. */
export class JobsApi {
  readonly #transport: HttpTransport;

  constructor(transport: HttpTransport) {
    this.#transport = transport;
  }

  /** `POST /v1/jobs` — start a run in the background and return its id. */
  async create(request: CreateJobRequest, options?: CallOptions): Promise<JobSnapshot> {
    return this.#transport.request<JobSnapshot>(
      {
        method: 'POST',
        path: '/v1/jobs',
        long: true,
        body: {
          kind: request.kind,
          path: request.path,
          ...(request.options ? { options: request.options } : {}),
          ...(request.outputSlug === undefined ? {} : { output_slug: request.outputSlug }),
          ...(request.review === undefined ? {} : { review: request.review }),
        },
      },
      options,
    );
  }

  /** Start a `study-guide` job. */
  async studyGuide(
    request: Omit<CreateJobRequest, 'kind'>,
    options?: CallOptions,
  ): Promise<JobSnapshot> {
    return this.create({ ...request, kind: 'study-guide' }, options);
  }

  /** Start a `review-report` job. */
  async reviewReport(
    request: ReviewReportJobRequest,
    options?: CallOptions,
  ): Promise<JobSnapshot> {
    const reportPath = request.reportPath;
    return this.#transport.request<JobSnapshot>(
      {
        method: 'POST',
        path: '/v1/jobs',
        long: true,
        body: {
          kind: 'review-report',
          path: request.path ?? reportPath,
          report_path: reportPath,
        },
      },
      options,
    );
  }

  /** `GET /v1/jobs` — every job the server knows about, in creation order. */
  async list(options?: CallOptions): Promise<JobSnapshot[]> {
    const body = await this.#transport.request<{ jobs: JobSnapshot[] }>(
      { method: 'GET', path: '/v1/jobs' },
      options,
    );
    return body.jobs;
  }

  /** `GET /v1/jobs/{id}` — one job's snapshot. */
  async get(id: string, options?: CallOptions & { messages?: boolean }): Promise<JobSnapshot> {
    return this.#transport.request<JobSnapshot>(
      {
        method: 'GET',
        path: `/v1/jobs/${encodeURIComponent(id)}`,
        query: { messages: options?.messages === true ? 1 : undefined },
      },
      options,
    );
  }

  /**
   * `DELETE /v1/jobs/{id}` — forget a finished job and return its id.
   *
   * A queued or running job cannot be deleted; the server answers 409.
   */
  async delete(id: string, options?: CallOptions): Promise<string> {
    const body = await this.#transport.request<{ deleted: string }>(
      { method: 'DELETE', path: `/v1/jobs/${encodeURIComponent(id)}` },
      options,
    );
    return body.deleted;
  }

  /**
   * Poll a job until it finishes.
   *
   * Returns the final snapshot on success. Throws a {@link BookroomJobError}
   * when the job fails or is cancelled, and a {@link BookroomTimeoutError} when
   * `timeoutMs` elapses first.
   */
  async waitFor(id: string, options: WaitForJobOptions = {}): Promise<JobSnapshot> {
    const pollIntervalMs = options.pollIntervalMs ?? 500;
    const timeoutMs = options.timeoutMs ?? this.#transport.config.longRunningTimeoutMs;
    const includeMessages = options.messages !== false;
    const deadline = timeoutMs > 0 ? Date.now() + timeoutMs : Number.POSITIVE_INFINITY;

    for (;;) {
      if (isSignalAborted(options.signal)) {
        throw new BookroomAbortError(`The caller aborted while waiting for job ${id}.`, {
          cause: options.signal?.reason,
        });
      }

      const job = await this.get(id, { ...options, messages: includeMessages });
      options.onUpdate?.(job);
      if (isTerminalStatus(job.status)) {
        if (job.status === 'succeeded') return job;
        throw new BookroomJobError(job);
      }
      if (Date.now() + pollIntervalMs > deadline) {
        throw new BookroomTimeoutError(
          `Job ${id} was still ${job.status} after ${timeoutMs} ms.`,
          { url: this.#transport.url(`/v1/jobs/${encodeURIComponent(id)}`) },
        );
      }
      await this.#sleep(Math.min(pollIntervalMs, Math.max(0, deadline - Date.now())), options.signal);
    }
  }

  /**
   * Wait for a study-guide job and return its report.
   *
   * A convenience over {@link waitFor} for the common case.
   */
  async waitForReport(id: string, options: WaitForJobOptions = {}): Promise<Report> {
    const job = await this.waitFor(id, options);
    return job.result as Report;
  }

  /**
   * Wait for a review-report job and return its records.
   */
  async waitForRecords(id: string, options: WaitForJobOptions = {}): Promise<ReviewRecord[]> {
    const job = await this.waitFor(id, options);
    const result = job.result as { records?: ReviewRecord[] } | undefined;
    return result?.records ?? [];
  }

  /** Sleep between polls, honoring the caller's abort signal. */
  #sleep(ms: number, signal?: AbortSignal): Promise<void> {
    if (ms <= 0) return Promise.resolve();
    return new Promise<void>((resolve, reject) => {
      const onAbort = (): void => {
        clearTimeout(timer);
        reject(new BookroomAbortError('The caller aborted while waiting to poll.', { cause: signal?.reason }));
      };
      const timer = setTimeout(() => {
        signal?.removeEventListener('abort', onAbort);
        resolve();
      }, ms);
      if (signal) {
        if (signal.aborted) {
          onAbort();
          return;
        }
        signal.addEventListener('abort', onAbort, { once: true });
      }
    });
  }
}
