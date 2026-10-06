/**
 * The HTTP transport: URL building, auth, timeouts, aborts, retries, and the
 * translation of every failure into a {@link BookroomError}.
 *
 * The retry policy is deliberately narrow, matching the facade contract: only
 * 429 and 5xx responses are retried, a server-supplied `retry_after_seconds`
 * (or `Retry-After` header) wins over backoff, and a 4xx client error is never
 * retried.
 */

import type { ResolvedConfig } from './config.js';
import {
  BookroomAbortError,
  BookroomError,
  BookroomNetworkError,
  BookroomProtocolError,
  BookroomTimeoutError,
} from './errors.js';
import type { FacadeErrorBody, FacadeErrorCode } from './types.js';

/** Query values accepted by the transport. */
export type QueryValue = string | number | boolean | undefined | null;

/** Per-call options accepted by every SDK method. */
export interface CallOptions {
  /** Caller abort signal, honoured during the request and during retry waits. */
  signal?: AbortSignal;
  /**
   * Timeout in milliseconds for this call only.
   *
   * Defaults to the client timeout, or to the longer timeout for long-running
   * routes. Pass 0 to wait indefinitely.
   */
  timeoutMs?: number;
  /** Extra headers for this call. */
  headers?: Record<string, string>;
}

/** One HTTP exchange to perform. */
export interface RequestSpec {
  method: 'GET' | 'POST' | 'DELETE';
  /** Path including the `/v1` prefix, for example `/v1/study-guide`. */
  path: string;
  query?: Record<string, QueryValue>;
  /** JSON request body; omitted for GET and DELETE. */
  body?: unknown;
  /** Use the long-running timeout for routes that can take minutes. */
  long?: boolean;
}

/**
 * Read a signal's current state through a call, so the value is never narrowed
 * from an earlier check: a signal can flip at any await point.
 */
export function isSignalAborted(signal?: AbortSignal): boolean {
  return signal !== undefined && signal.aborted;
}

/** Sleep that resolves early, and rejects, when the caller's signal fires. */
function delay(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  return new Promise<void>((resolve, reject) => {
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(new BookroomAbortError('The call was aborted while waiting to retry.'));
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

/** Map an HTTP status onto a facade code, for bodies that are not JSON. */
function codeForStatus(status: number): FacadeErrorCode {
  switch (status) {
    case 400:
      return 'invalid_request';
    case 401:
    case 403:
      return 'unauthorized';
    case 404:
      return 'not_found';
    case 409:
      return 'conflict';
    case 415:
      return 'unsupported_source';
    case 422:
      return 'invalid_request';
    case 429:
      return 'quota_exceeded';
    case 502:
      return 'provider_error';
    default:
      return status >= 500 ? 'internal_error' : 'invalid_request';
  }
}

function parseRetryAfterHeader(value: string | null): number | undefined {
  if (value === null) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds;
  const asDate = Date.parse(value);
  if (Number.isFinite(asDate)) return Math.max(0, (asDate - Date.now()) / 1000);
  return undefined;
}

/** The transport shared by every resource namespace. */
export class HttpTransport {
  readonly config: ResolvedConfig;

  constructor(config: ResolvedConfig) {
    this.config = config;
  }

  /** Absolute URL for a path and query, without the auth header. */
  url(path: string, query?: Record<string, QueryValue>): string {
    const suffix = path.startsWith('/') ? path : `/${path}`;
    let url = `${this.config.baseUrl}${suffix}`;
    if (query) {
      const search = new URLSearchParams();
      for (const [key, value] of Object.entries(query)) {
        if (value === undefined || value === null) continue;
        search.append(key, String(value));
      }
      const encoded = search.toString();
      if (encoded !== '') url += `?${encoded}`;
    }
    return url;
  }

  /**
   * Perform one request, with retries, and return the parsed JSON body.
   *
   * Resolves to `undefined` when the server returns an empty body, which is how
   * a few routes answer.
   */
  async request<T>(spec: RequestSpec, options: CallOptions = {}): Promise<T> {
    const url = this.url(spec.path, spec.query);
    const method = spec.method;
    const hasBody = spec.body !== undefined;

    const headers: Record<string, string> = {
      accept: 'application/json',
      ...this.config.defaultHeaders,
      ...options.headers,
    };
    if (this.config.userAgent !== undefined) headers['user-agent'] = this.config.userAgent;
    if (this.config.token !== undefined) {
      headers['authorization'] = `Bearer ${this.config.token}`;
    }
    if (hasBody) headers['content-type'] = 'application/json';

    const timeoutMs =
      options.timeoutMs ??
      (spec.long === true ? this.config.longRunningTimeoutMs : this.config.timeoutMs);

    const body = hasBody ? JSON.stringify(spec.body) : undefined;
    const maxAttempts = this.config.maxRetries + 1;

    let lastError: BookroomError | undefined;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      if (isSignalAborted(options.signal)) {
        throw new BookroomAbortError('The call was aborted before it started.', {
          method,
          url,
        });
      }

      let response;
      let timedOut = false;
      const controller = new AbortController();
      const timer =
        timeoutMs > 0
          ? setTimeout(() => {
              timedOut = true;
              controller.abort();
            }, timeoutMs)
          : undefined;
      const onExternalAbort = (): void => controller.abort();
      options.signal?.addEventListener('abort', onExternalAbort, { once: true });

      try {
        response = await this.config.fetch(url, {
          method,
          headers,
          ...(body !== undefined ? { body } : {}),
          signal: controller.signal,
        });
      } catch (cause) {
        if (timedOut) {
          throw new BookroomTimeoutError(
            `${method} ${spec.path} timed out after ${timeoutMs} ms.`,
            { method, url, cause },
          );
        }
        if (isSignalAborted(options.signal)) {
          throw new BookroomAbortError(`${method} ${spec.path} was aborted by the caller.`, {
            method,
            url,
            cause,
          });
        }
        const networkError = new BookroomNetworkError(
          `Could not reach the Bookroom facade at ${this.config.baseUrl}: ${
            cause instanceof Error ? cause.message : String(cause)
          }`,
          { method, url, cause },
        );
        if (this.config.retryOnNetworkError && attempt < maxAttempts) {
          lastError = networkError;
          await this.waitBeforeRetry(attempt, undefined, options.signal);
          continue;
        }
        throw networkError;
      } finally {
        if (timer !== undefined) clearTimeout(timer);
        options.signal?.removeEventListener('abort', onExternalAbort);
      }

      const raw = await this.readBody(response, method, url);

      if (response.ok) {
        if (raw.trim() === '') return undefined as T;
        try {
          return JSON.parse(raw) as T;
        } catch (cause) {
          throw new BookroomProtocolError(
            `${method} ${spec.path} returned a body that is not valid JSON.`,
            { method, url, body: raw, cause },
          );
        }
      }

      const error = this.toBookroomError(raw, response, method, url);
      if (error.isRetryable && attempt < maxAttempts) {
        lastError = error;
        await this.waitBeforeRetry(attempt, error, options.signal);
        continue;
      }
      throw error;
    }

    /* c8 ignore next 2 -- unreachable: the loop either returns or throws. */
    throw lastError ?? new BookroomError('The request failed for an unknown reason.', { code: 'internal_error', status: 500 });
  }

  /** Read the response text, mapping a read failure to a protocol error. */
  private async readBody(
    response: { ok: boolean; status: number; text(): Promise<string> },
    method: string,
    url: string,
  ): Promise<string> {
    try {
      return await response.text();
    } catch (cause) {
      throw new BookroomProtocolError(
        `${method} ${url} failed while reading the response body (HTTP ${response.status}).`,
        { method, url, cause },
      );
    }
  }

  /** Turn a non-2xx response into a typed error. */
  private toBookroomError(
    raw: string,
    response: { status: number; statusText?: string; headers: { get(name: string): string | null } },
    method: string,
    url: string,
  ): BookroomError {
    let body: unknown;
    let envelope: FacadeErrorBody | undefined;
    try {
      body = raw.trim() === '' ? undefined : JSON.parse(raw);
      if (typeof body === 'object' && body !== null && 'error' in body) {
        envelope = (body as { error?: FacadeErrorBody }).error;
      }
    } catch {
      body = raw;
    }

    const retryAfterSeconds =
      envelope?.retry_after_seconds ?? parseRetryAfterHeader(response.headers.get('retry-after'));

    const message =
      envelope?.message ??
      (typeof body === 'string' && body.trim() !== ''
        ? body.trim().slice(0, 500)
        : `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ''}`);

    return new BookroomError(message, {
      code: envelope?.code ?? codeForStatus(response.status),
      status: response.status,
      ...(retryAfterSeconds !== undefined ? { retryAfterSeconds } : {}),
      ...(envelope?.type !== undefined ? { type: envelope.type } : {}),
      ...(envelope?.trace !== undefined ? { trace: envelope.trace } : {}),
      method,
      url,
      ...(body !== undefined ? { body } : {}),
    });
  }

  /**
   * Wait before the next attempt.
   *
   * A server-supplied retry-after wins over exponential backoff, and every wait
   * is capped so a hostile value cannot stall the caller forever.
   */
  private async waitBeforeRetry(
    attempt: number,
    error: BookroomError | undefined,
    signal?: AbortSignal,
  ): Promise<void> {
    const requested = error?.retryAfterSeconds;
    const backoff = this.config.retryBaseDelayMs * 2 ** (attempt - 1);
    const jittered = backoff / 2 + Math.random() * (backoff / 2);
    const ms = Math.min(this.config.retryMaxDelayMs, Math.max(0, requested ?? jittered));
    await delay(ms, signal);
  }
}
