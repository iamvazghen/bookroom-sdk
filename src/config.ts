/**
 * Client configuration: constructor options first, then `BOOKROOM_*` variables.
 *
 * Only the facade token is ever needed by the caller. The LLM and JEv API keys
 * live in the facade process; this client neither accepts nor sends them.
 */

import { BookroomConfigError } from './errors.js';

/** Base URL used when nothing else is configured. */
export const DEFAULT_BASE_URL = 'http://127.0.0.1:8787';

/**
 * Default per-call timeout.
 *
 * Generous on purpose: the facade serializes runs behind a lock, so a request
 * can queue behind another one and a study guide legitimately takes minutes.
 */
export const DEFAULT_TIMEOUT_MS = 300_000;

/** Default timeout for routes that can take many minutes. */
export const DEFAULT_LONG_TIMEOUT_MS = 1_800_000;

/** Default number of retries after the first attempt, for 429 and 5xx only. */
export const DEFAULT_MAX_RETRIES = 2;

/** Base backoff, doubled per attempt and capped by `retryMaxDelayMs`. */
export const DEFAULT_RETRY_BASE_DELAY_MS = 500;

/** Ceiling applied to any single wait, including a server-requested retry-after. */
export const DEFAULT_RETRY_MAX_DELAY_MS = 60_000;

/** The slice of the environment this SDK reads. */
export type EnvironmentLike = Record<string, string | undefined>;

/**
 * The `fetch` signature this client needs.
 *
 * The global `fetch` satisfies it, and so does any injected implementation with
 * compatible behavior.
 */
export interface HttpResponseLike {
  ok: boolean;
  status: number;
  statusText?: string;
  headers: { get(name: string): string | null };
  text(): Promise<string>;
}

/** Init passed to {@link FetchLike}; a structural subset of `RequestInit`. */
export interface RequestInitLike {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  signal?: AbortSignal;
}

/** An injectable `fetch`. */
export type FetchLike = (url: string, init: RequestInitLike) => Promise<HttpResponseLike>;

/** Options accepted by the {@link Bookroom} constructor. */
export interface BookroomClientOptions {
  /**
   * Base URL of the facade server, without a trailing slash.
   *
   * Defaults to `BOOKROOM_URL`, then to `http://127.0.0.1:8787`.
   */
  baseUrl?: string;
  /**
   * Facade token, sent as `Authorization: Bearer <token>`.
   *
   * Optional: leave it unset when the server was started without a token.
   * Defaults to `BOOKROOM_FACADE_TOKEN`.
   */
  token?: string;
  /**
   * Per-call timeout in milliseconds.
   *
   * Defaults to `BOOKROOM_TIMEOUT_MS`, then to 300000. Use 0 to disable.
   */
  timeoutMs?: number;
  /**
   * Timeout for long-running routes (study guide, jobs, heavy review and
   * exports). Defaults to `BOOKROOM_LONG_TIMEOUT_MS`, then to 1800000.
   */
  longRunningTimeoutMs?: number;
  /**
   * Local directory that relative file paths are resolved against, for
   * readability in logs. It is never sent to the server, which resolves every
   * path on its own filesystem. Defaults to `BOOKROOM_APP_ROOT`.
   */
  appRoot?: string;
  /** Retries after the first attempt, for 429 and 5xx only. Defaults to 2. */
  maxRetries?: number;
  /** Base backoff in milliseconds; doubled per attempt. Defaults to 500. */
  retryBaseDelayMs?: number;
  /** Ceiling for any single wait, including a server-requested retry-after. Defaults to 60000. */
  retryMaxDelayMs?: number;
  /**
   * Also retry transport failures, not just 429 and 5xx.
   *
   * Off by default so the retry policy is exactly what the contract states.
   */
  retryOnNetworkError?: boolean;
  /** Custom `fetch`; defaults to the global one. */
  fetch?: FetchLike;
  /** Extra headers sent with every request. */
  defaultHeaders?: Record<string, string>;
  /** `User-Agent` to send; ignored by browsers. Defaults to `bookroom-sdk/1.0.0`. */
  userAgent?: string;
  /** Environment to read instead of `process.env`, for tests and edge runtimes. */
  env?: EnvironmentLike;
  /** Override for the environment reader, for exotic runtimes. */
  readEnv?: () => EnvironmentLike;
}

/** Configuration after merging options, environment, and defaults. */
export interface ResolvedConfig {
  baseUrl: string;
  token?: string;
  timeoutMs: number;
  longRunningTimeoutMs: number;
  appRoot?: string;
  maxRetries: number;
  retryBaseDelayMs: number;
  retryMaxDelayMs: number;
  retryOnNetworkError: boolean;
  fetch: FetchLike;
  defaultHeaders: Record<string, string>;
  userAgent?: string;
}

/** Read `process.env` when it exists, and an empty object elsewhere. */
export function readProcessEnv(): EnvironmentLike {
  const candidate = (globalThis as { process?: { env?: EnvironmentLike } }).process;
  return candidate?.env ?? {};
}

/** The global `fetch`, resolved lazily so a missing runtime fails clearly. */
export function globalFetch(): FetchLike {
  const candidate = (globalThis as { fetch?: unknown }).fetch;
  if (typeof candidate !== 'function') {
    throw new BookroomConfigError(
      'No global fetch is available. Use Node 18 or newer, or pass options.fetch.',
    );
  }
  return (url, init) => (candidate as FetchLike)(url, init);
}

function pickInt(
  value: string | undefined,
  fallback: number,
  label: string,
  { allowZero = false }: { allowZero?: boolean } = {},
): number {
  if (value === undefined || value.trim() === '') return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < 0 || (!allowZero && parsed === 0)) {
    throw new BookroomConfigError(`${label} must be a non-negative integer, received "${value}"`);
  }
  return parsed;
}

function normalizeBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, '');
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch (cause) {
    throw new BookroomConfigError(
      `baseUrl must be an absolute http(s) URL, received "${value}"`,
      { cause },
    );
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new BookroomConfigError(`baseUrl must use http or https, received "${value}"`);
  }
  return trimmed;
}

/**
 * Merge constructor options over environment variables over defaults.
 *
 * Exported so an integrator can validate configuration once at start-up and
 * reuse the result.
 */
export function resolveConfig(options: BookroomClientOptions = {}): ResolvedConfig {
  const env = options.env ?? (options.readEnv ?? readProcessEnv)();

  const baseUrl = normalizeBaseUrl(options.baseUrl ?? env['BOOKROOM_URL'] ?? DEFAULT_BASE_URL);

  const tokenSource = options.token ?? env['BOOKROOM_FACADE_TOKEN'];
  const token = tokenSource && tokenSource.trim() !== '' ? tokenSource.trim() : undefined;

  const timeoutMs = options.timeoutMs ?? pickInt(env['BOOKROOM_TIMEOUT_MS'], DEFAULT_TIMEOUT_MS, 'BOOKROOM_TIMEOUT_MS', { allowZero: true });
  const longRunningTimeoutMs =
    options.longRunningTimeoutMs ??
    pickInt(env['BOOKROOM_LONG_TIMEOUT_MS'], DEFAULT_LONG_TIMEOUT_MS, 'BOOKROOM_LONG_TIMEOUT_MS', { allowZero: true });

  for (const [label, value] of [
    ['timeoutMs', timeoutMs],
    ['longRunningTimeoutMs', longRunningTimeoutMs],
  ] as const) {
    if (!Number.isFinite(value) || value < 0 || !Number.isInteger(value)) {
      throw new BookroomConfigError(`${label} must be a non-negative integer, received ${value}`);
    }
  }

  const appRootSource = options.appRoot ?? env['BOOKROOM_APP_ROOT'];
  const appRoot = appRootSource && appRootSource.trim() !== '' ? appRootSource.trim() : undefined;

  const maxRetries = options.maxRetries ?? pickInt(env['BOOKROOM_MAX_RETRIES'], DEFAULT_MAX_RETRIES, 'maxRetries');
  const retryBaseDelayMs =
    options.retryBaseDelayMs ?? pickInt(env['BOOKROOM_RETRY_BASE_DELAY_MS'], DEFAULT_RETRY_BASE_DELAY_MS, 'retryBaseDelayMs');
  const retryMaxDelayMs =
    options.retryMaxDelayMs ?? pickInt(env['BOOKROOM_RETRY_MAX_DELAY_MS'], DEFAULT_RETRY_MAX_DELAY_MS, 'retryMaxDelayMs');

  const userAgentSource = options.userAgent ?? env['BOOKROOM_USER_AGENT'];
  const userAgent = userAgentSource !== undefined && userAgentSource !== '' ? userAgentSource : undefined;

  const resolved: ResolvedConfig = {
    baseUrl,
    timeoutMs,
    longRunningTimeoutMs,
    maxRetries,
    retryBaseDelayMs,
    retryMaxDelayMs,
    retryOnNetworkError: options.retryOnNetworkError ?? false,
    fetch: options.fetch ?? globalFetch(),
    defaultHeaders: { ...options.defaultHeaders },
  };
  if (token !== undefined) resolved.token = token;
  if (appRoot !== undefined) resolved.appRoot = appRoot;
  if (userAgent !== undefined) resolved.userAgent = userAgent;
  return resolved;
}

/**
 * Join a possibly relative path to the configured app root, for readable logs.
 *
 * Absolute paths are returned unchanged. This is purely cosmetic: the server
 * resolves every path on its own filesystem, so this value is never sent.
 */
export function joinAppRoot(appRoot: string, candidate: string): string {
  if (candidate === '') return appRoot;
  const isAbsolute =
    candidate.startsWith('/') ||
    candidate.startsWith('\\') ||
    /^[A-Za-z]:[\\/]/.test(candidate) ||
    candidate.startsWith('\\\\');
  if (isAbsolute) return candidate;
  const separator = appRoot.includes('\\') && !appRoot.includes('/') ? '\\' : '/';
  const base = appRoot.replace(/[\\/]+$/, '');
  return `${base}${separator}${candidate.replace(/^[\\/]+/, '')}`;
}
