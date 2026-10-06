/**
 * The SDK error hierarchy.
 *
 * Every failure that leaves the client is a {@link BookroomError} carrying the
 * server's own `code`, HTTP `status`, and `retry_after_seconds`, so callers can
 * branch on failure kind without parsing strings. A handful of client-side
 * conditions (timeouts, aborts, transport failures, unparsable bodies) use their
 * own codes and are documented as such.
 */

import type { FacadeErrorCode, JobSnapshot } from './types.js';

/** Brand used for cross-realm `instanceof` replacement. */
const BRAND: unique symbol = Symbol.for('bookroom.BookroomError');

/** Fields carried by every error the SDK raises. */
export interface BookroomErrorInit {
  /** Server error code, or a client-side code such as `timeout`. */
  code: FacadeErrorCode;
  /** HTTP status; 0 for a failure that never produced a response. */
  status: number;
  retryAfterSeconds?: number;
  /** The Python exception class the server reported, when it reported one. */
  type?: string;
  /** Server-side traceback, present on `internal_error`. */
  trace?: string;
  method?: string;
  url?: string;
  /** Parsed response body, when one was received. */
  body?: unknown;
  cause?: unknown;
}

/** Base class for every SDK error. */
export class BookroomError extends Error {
  readonly code: FacadeErrorCode;
  readonly status: number;
  readonly retryAfterSeconds?: number;
  readonly type?: string;
  readonly trace?: string;
  readonly method?: string;
  readonly url?: string;
  readonly body?: unknown;

  readonly [BRAND] = true;

  constructor(message: string, init: BookroomErrorInit) {
    super(message, 'cause' in init ? { cause: init.cause } : undefined);
    this.name = 'BookroomError';
    this.code = init.code;
    this.status = init.status;
    if (init.retryAfterSeconds !== undefined) this.retryAfterSeconds = init.retryAfterSeconds;
    if (init.type !== undefined) this.type = init.type;
    if (init.trace !== undefined) this.trace = init.trace;
    if (init.method !== undefined) this.method = init.method;
    if (init.url !== undefined) this.url = init.url;
    if (init.body !== undefined) this.body = init.body;
  }

  /** True when the status is one this SDK retries (429 or any 5xx). */
  get isRetryable(): boolean {
    return this.status === 429 || this.status >= 500;
  }

  /** A plain object suitable for structured logging. */
  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      code: this.code,
      status: this.status,
      message: this.message,
      ...(this.retryAfterSeconds !== undefined ? { retry_after_seconds: this.retryAfterSeconds } : {}),
      ...(this.type !== undefined ? { type: this.type } : {}),
      ...(this.method !== undefined ? { method: this.method } : {}),
      ...(this.url !== undefined ? { url: this.url } : {}),
    };
  }
}

/** The client was not configured well enough to run. */
export class BookroomConfigError extends BookroomError {
  constructor(message: string, init?: Partial<BookroomErrorInit>) {
    super(message, { code: 'invalid_request', status: 0, ...init });
    this.name = 'BookroomConfigError';
  }
}

/** The request exceeded its timeout (`code: 'timeout'`, `status: 408`). */
export class BookroomTimeoutError extends BookroomError {
  constructor(message: string, init?: Partial<BookroomErrorInit>) {
    super(message, { code: 'timeout', status: 408, ...init });
    this.name = 'BookroomTimeoutError';
  }
}

/** The caller's `AbortSignal` fired (`code: 'aborted'`, `status: 499`). */
export class BookroomAbortError extends BookroomError {
  constructor(message: string, init?: Partial<BookroomErrorInit>) {
    super(message, { code: 'aborted', status: 499, ...init });
    this.name = 'BookroomAbortError';
  }
}

/** The facade could not be reached (`code: 'network_error'`, `status: 0`). */
export class BookroomNetworkError extends BookroomError {
  constructor(message: string, init?: Partial<BookroomErrorInit>) {
    super(message, { code: 'network_error', status: 0, ...init });
    this.name = 'BookroomNetworkError';
  }
}

/** The server answered with a body the SDK could not parse. */
export class BookroomProtocolError extends BookroomError {
  constructor(message: string, init?: Partial<BookroomErrorInit>) {
    super(message, { code: 'invalid_response', status: 0, ...init });
    this.name = 'BookroomProtocolError';
  }
}

/** A background job ended in `failed` or `cancelled`. */
export class BookroomJobError extends BookroomError {
  /** The final job snapshot, for status, messages, and error text. */
  readonly job: JobSnapshot;

  constructor(job: JobSnapshot, init?: Partial<BookroomErrorInit>) {
    const reason = job.error ?? `job ${job.id} ended as ${job.status}`;
    super(`Job ${job.id} ${job.status}: ${reason}`, {
      code: job.status === 'cancelled' ? 'cancelled' : 'job_failed',
      status: job.status === 'cancelled' ? 409 : 500,
      ...init,
    });
    this.name = 'BookroomJobError';
    this.job = job;
  }
}

/* -------------------------------------------------------------------------- */
/* Type guards                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * True for any error raised by this SDK.
 *
 * Uses a registered symbol rather than `instanceof`, so it keeps working when
 * two copies of the package end up in one process (ESM plus CJS, or a
 * duplicated install).
 */
export function isBookroomError(value: unknown): value is BookroomError {
  return typeof value === 'object' && value !== null && BRAND in value;
}

/** True when the error carries the given server or client-side code. */
export function hasErrorCode(value: unknown, code: string): boolean {
  return isBookroomError(value) && value.code === code;
}

/** A provider quota window was hit; the server told us when to retry. */
export function isQuotaError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'quota_exceeded');
}

/** Estimated provider spend exceeds the configured caps. */
export function isBudgetExceededError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'budget_exceeded');
}

/** The file type is not supported; only EPUB and PDF are. */
export function isUnsupportedSourceError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'unsupported_source');
}

/** Text could not be extracted from the source document. */
export function isExtractionFailedError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'extraction_failed');
}

/** The LLM or JEv provider rejected the request or was unreachable. */
export function isProviderError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'provider_error');
}

/** The facade token was missing or wrong. */
export function isUnauthorizedError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'unauthorized');
}

/** The route, job, report, or file does not exist. */
export function isNotFoundError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'not_found');
}

/** The resource is in a state that forbids the operation, such as deleting a running job. */
export function isConflictError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'conflict');
}

/** The server could not be configured well enough to run. */
export function isConfigurationError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'configuration_error');
}

/** A job or request was cancelled, by the server or by the caller's signal. */
export function isCancelledError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'cancelled') || hasErrorCode(value, 'aborted');
}

/** The request ran out of time. */
export function isTimeoutError(value: unknown): value is BookroomError {
  return hasErrorCode(value, 'timeout');
}

/** A background job failed. */
export function isJobFailedError(value: unknown): value is BookroomJobError {
  return value instanceof BookroomJobError;
}

/** True when the status is one this SDK would retry (429 or any 5xx). */
export function isRetryableError(value: unknown): value is BookroomError {
  if (isBookroomError(value)) return value.isRetryable;
  return false;
}

/**
 * Seconds to wait before retrying, from the error body or the `Retry-After`
 * header. Returns undefined when the server did not say.
 */
export function retryDelaySeconds(value: unknown): number | undefined {
  if (!isBookroomError(value)) return undefined;
  if (value.retryAfterSeconds !== undefined) return value.retryAfterSeconds;
  const body = value.body;
  if (typeof body === 'object' && body !== null) {
    const raw = (body as { error?: { retry_after_seconds?: unknown } }).error?.retry_after_seconds;
    if (typeof raw === 'number') return raw;
  }
  return undefined;
}
