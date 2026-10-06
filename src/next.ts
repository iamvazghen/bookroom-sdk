/**
 * Next.js server-side integration for the Bookroom SDK.
 *
 * Everything in this module runs on the server. It is the other half of
 * `src/react.tsx`: the browser calls your route handler or server action, this
 * module attaches the facade token, and it hands back a payload with every
 * server-only field removed.
 *
 * This file imports nothing from `next/*`. It depends only on the SDK and on web
 * globals (`Response`, `AbortSignal`), so it compiles in a project that has not
 * installed Next.js, and it works in the Node and edge runtimes alike.
 *
 * ## Wiring
 *
 * Server action, in `app/actions.ts`:
 *
 * ```ts
 * 'use server';
 * import { createSummarizeAction, createJobStatusAction } from 'bookroom-sdk/next';
 *
 * export const startStudyGuide = createSummarizeAction();
 * export const jobStatus = createJobStatusAction();
 * ```
 *
 * Route handler, in `app/api/bookroom/[...path]/route.ts`:
 *
 * ```ts
 * import { handleBookroomRequest, jsonResponse } from 'bookroom-sdk/next';
 *
 * export const GET = (request: Request, context: { params: Promise<{ path: string[] }> }) =>
 *   handleBookroomRequest(async ({ client, params }) => {
 *     const segment = params.path.join('/');
 *     if (segment === 'jobs') return client.jobs.list();
 *     return client.jobs.get(segment);
 *   }, request, context.params);
 * ```
 *
 * The facade token stays in `BOOKROOM_FACADE_TOKEN` on the server. Nothing here
 * reads a `NEXT_PUBLIC_` variable, and no function returns the token, the facade
 * URL, a server traceback, or a server file path unless you ask for it.
 *
 * @packageDocumentation
 */

import { Bookroom } from './client.js';
import type { BookroomClientOptions } from './config.js';
import { DEFAULT_BASE_URL, readProcessEnv } from './config.js';
import { BookroomConfigError, BookroomError } from './errors.js';
import { isBookroomError } from './errors.js';
import type {
  Artifact,
  FacadeErrorCode,
  JobSnapshot,
  JobStatus,
  Preflight,
  Report,
  SummarizeOptions,
} from './types.js';

/* -------------------------------------------------------------------------- */
/* Server client                                                               */
/* -------------------------------------------------------------------------- */

/** Options for {@link getServerBookroom}. */
export interface ServerBookroomOptions extends BookroomClientOptions {
  /**
   * Fail when no facade token is configured. Defaults to `true`.
   *
   * Set it to `false` only when you started the facade without `--token`.
   */
  requireToken?: boolean;
}

/**
 * Clients built so far, keyed by their connection settings.
 *
 * One client per process is the point: it holds one `fetch`, one retry policy,
 * and one token, and sharing it keeps the facade's run lock from being
 * contended by duplicate connection pools.
 */
const CLIENT_CACHE = new Map<string, Bookroom>();

/** Environment variables this module reads, in priority order. */
export const SERVER_ENV_VARS = {
  /** Facade base URL. */
  baseUrl: ['BOOKROOM_URL', 'BOOKROOM_BASE_URL'] as const,
  /** Facade bearer token. */
  token: ['BOOKROOM_FACADE_TOKEN', 'BOOKROOM_TOKEN'] as const,
};

function readFirst(env: Record<string, string | undefined>, names: readonly string[]): string | undefined {
  for (const name of names) {
    const value = env[name];
    if (value !== undefined && value.trim() !== '') return value.trim();
  }
  return undefined;
}

/**
 * Build the server-side client from the environment, cached per process.
 *
 * Reads `BOOKROOM_URL` and `BOOKROOM_FACADE_TOKEN`, falling back to
 * `BOOKROOM_BASE_URL` and `BOOKROOM_TOKEN`. Explicit options win over the
 * environment. The returned client is memoized, so repeated calls in the same
 * process share one instance.
 *
 * @throws {@link BookroomConfigError} when no token is configured and
 * `requireToken` is on. The message names the exact variable to set.
 */
export function getServerBookroom(options: ServerBookroomOptions = {}): Bookroom {
  const env = options.env ?? readProcessEnv();
  const baseUrl = options.baseUrl ?? readFirst(env, SERVER_ENV_VARS.baseUrl) ?? DEFAULT_BASE_URL;
  const token = options.token ?? readFirst(env, SERVER_ENV_VARS.token);

  if (options.requireToken !== false && token === undefined) {
    throw new BookroomConfigError(
      `getServerBookroom: no facade token found. Set ${SERVER_ENV_VARS.token[0]} in the server ` +
        'environment. Never put it in a NEXT_PUBLIC_ variable or send it to the browser. If the ' +
        'facade was started without --token, pass { requireToken: false }.',
    );
  }

  const key = JSON.stringify([
    baseUrl,
    token ?? null,
    options.timeoutMs ?? null,
    options.longRunningTimeoutMs ?? null,
    options.maxRetries ?? null,
    options.appRoot ?? null,
  ]);
  const cached = CLIENT_CACHE.get(key);
  if (cached !== undefined) return cached;

  const client = new Bookroom({
    baseUrl,
    env,
    ...(token !== undefined ? { token } : {}),
    ...(options.timeoutMs !== undefined ? { timeoutMs: options.timeoutMs } : {}),
    ...(options.longRunningTimeoutMs !== undefined
      ? { longRunningTimeoutMs: options.longRunningTimeoutMs }
      : {}),
    ...(options.maxRetries !== undefined ? { maxRetries: options.maxRetries } : {}),
    ...(options.appRoot !== undefined ? { appRoot: options.appRoot } : {}),
    ...(options.retryOnNetworkError !== undefined
      ? { retryOnNetworkError: options.retryOnNetworkError }
      : {}),
    ...(options.fetch !== undefined ? { fetch: options.fetch } : {}),
  });
  CLIENT_CACHE.set(key, client);
  return client;
}

/** Drop every cached client. Use after rotating the token, or between tests. */
export function clearServerBookroomCache(): void {
  CLIENT_CACHE.clear();
}

/* -------------------------------------------------------------------------- */
/* Client-safe payloads                                                        */
/* -------------------------------------------------------------------------- */

/**
 * An error shape that is safe to send to a browser.
 *
 * The SDK's `trace`, `type`, `url`, and `method` are deliberately dropped: they
 * carry a server traceback, a Python class name, and internal endpoints.
 */
export interface ClientError {
  name: string;
  code: FacadeErrorCode;
  status: number;
  message: string;
  retry_after_seconds?: number;
}

/** An artifact as the browser sees it. */
export interface ClientArtifact {
  name: string;
  media_type: string;
  exists: boolean;
  /** Server filesystem path. Only set when `exposePaths` is on. */
  path: string | null;
  /** A URL your own server serves. Only set when `artifactHref` returns one. */
  href: string | null;
}

/** The JEv outcome, reduced to the numbers a UI shows. */
export interface ClientQualitySummary {
  enabled: boolean;
  all_passed: boolean;
  categories_reviewed: number;
  categories_passed: number;
  categories_below_threshold: number;
  threshold: number;
}

/**
 * A finished report, reduced to what a browser needs.
 *
 * The full `Report` is not sent: it repeats document metadata, carries the
 * server's output folder, and lists the same artifacts twice.
 */
export interface ClientReportSummary {
  title: string;
  kind: string;
  section_count: number;
  total_words: number;
  /** Server filesystem path. Only set when `exposePaths` is on. */
  output_dir: string | null;
  report_path: string | null;
  quality: ClientQualitySummary | null;
  artifacts: ClientArtifact[];
}

/** A job snapshot with server-only fields removed. */
export interface ClientJob {
  id: string;
  kind: string;
  status: JobStatus;
  created_at: string;
  finished_at: string | null;
  /** Failure text the server itself wrote. Never a traceback. */
  error: string | null;
  message_count: number;
  messages?: string[];
  /** Success payload, reduced to a summary. Null unless the job succeeded. */
  report: ClientReportSummary | null;
}

/** How much of the server's detail survives the trip to a browser. */
export interface ClientPayloadOptions {
  /** Include progress messages. Defaults to `true`. */
  messages?: boolean;
  /**
   * Include server filesystem paths. Defaults to `false`.
   *
   * Turn it on only for a local, single-user tool where seeing the output
   * folder is the point. A path leaks the server's directory layout.
   */
  exposePaths?: boolean;
  /**
   * Build a browser URL for an artifact.
   *
   * The facade serves artifact metadata but no file bytes, so a link needs a
   * route of your own. Return `null` to send no link.
   */
  artifactHref?: (artifact: Artifact, report: Report | null) => string | null;
}

/** Options shared by every helper that produces a client payload. */
export interface BookroomServerIntegrationOptions extends ServerBookroomOptions, ClientPayloadOptions {}

/** Normalize anything thrown into a {@link BookroomError}. */
function normalizeError(value: unknown): BookroomError {
  if (isBookroomError(value)) return value;
  if (value instanceof Error) {
    return new BookroomError(value.message, { code: 'internal_error', status: 0, cause: value });
  }
  return new BookroomError(`The request failed: ${String(value)}`, {
    code: 'internal_error',
    status: 0,
    cause: value,
  });
}

/** Reduce an error to the fields a browser may see. */
export function toClientError(value: unknown): ClientError {
  const error = normalizeError(value);
  const client: ClientError = {
    name: error.name,
    code: error.code,
    status: error.status,
    message: error.message,
  };
  if (error.retryAfterSeconds !== undefined) {
    client.retry_after_seconds = error.retryAfterSeconds;
  }
  return client;
}

/** Narrow an untyped job result to a study-guide {@link Report}. */
function asReport(value: unknown): Report | null {
  if (typeof value !== 'object' || value === null) return null;
  const candidate = value as Partial<Report>;
  if (typeof candidate.output_dir !== 'string') return null;
  if (!Array.isArray(candidate.artifacts)) return null;
  return candidate as Report;
}

function toClientQuality(report: Report | null): ClientQualitySummary | null {
  const quality = report?.quality;
  if (quality === null || quality === undefined) return null;
  return {
    enabled: quality.enabled,
    all_passed: quality.all_passed,
    categories_reviewed: quality.categories_reviewed,
    categories_passed: quality.categories_passed,
    categories_below_threshold: quality.categories_below_threshold,
    threshold: quality.threshold,
  };
}

function toClientArtifact(
  artifact: Artifact,
  report: Report | null,
  options: ClientPayloadOptions,
): ClientArtifact {
  const exposePaths = options.exposePaths === true;
  const href = options.artifactHref?.(artifact, report) ?? null;
  return {
    name: artifact.name,
    media_type: artifact.media_type,
    exists: artifact.exists,
    path: exposePaths ? artifact.path : null,
    href,
  };
}

/** Reduce a full `Report` to a {@link ClientReportSummary}. */
export function toClientReport(
  report: Report,
  options: ClientPayloadOptions = {},
): ClientReportSummary {
  const exposePaths = options.exposePaths === true;
  return {
    title: report.document.title,
    kind: report.document.kind,
    section_count: report.document.section_count,
    total_words: report.document.total_words,
    output_dir: exposePaths ? report.output_dir : null,
    report_path: exposePaths ? report.report_path : null,
    quality: toClientQuality(report),
    artifacts: report.artifacts.map((artifact) => toClientArtifact(artifact, report, options)),
  };
}

/**
 * Reduce a raw snapshot to a {@link ClientJob}.
 *
 * The `result` field is replaced by `report`, a summary; `exposePaths` decides
 * whether any filesystem path rides along.
 */
export function toClientJob(
  snapshot: JobSnapshot,
  options: ClientPayloadOptions = {},
): ClientJob {
  const report = asReport(snapshot.result);
  const job: ClientJob = {
    id: snapshot.id,
    kind: snapshot.kind,
    status: snapshot.status,
    created_at: snapshot.created_at,
    finished_at: snapshot.finished_at,
    error: snapshot.error,
    message_count: snapshot.message_count,
    report: report === null ? null : toClientReport(report, options),
  };
  if (options.messages !== false && snapshot.messages !== undefined) {
    job.messages = snapshot.messages;
  }
  return job;
}

/** Options for {@link getJobForClient}. */
export type GetJobForClientOptions = BookroomServerIntegrationOptions;

/**
 * Fetch a job and return the browser-safe form.
 *
 * This is what a status route or action should return. It never leaks the raw
 * `result`, a server traceback, or (unless asked) a filesystem path.
 *
 * @throws {@link BookroomError} `not_found` when the job id is unknown, which
 * {@link handleBookroomRequest} turns into a 404 response.
 */
export async function getJobForClient(
  id: string,
  options: GetJobForClientOptions = {},
): Promise<ClientJob> {
  const client = getServerBookroom(options);
  const snapshot = await client.jobs.get(id, {
    ...(options.messages === false ? {} : { messages: true }),
  });
  return toClientJob(snapshot, options);
}

/* -------------------------------------------------------------------------- */
/* Server actions                                                              */
/* -------------------------------------------------------------------------- */

/**
 * The result of a server action: data, or a client-safe error.
 *
 * Actions return rather than throw, because an action's rejection is surfaced
 * to the browser as a framework error page with a digest, which tells the user
 * nothing useful.
 */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; error: ClientError };

/**
 * Run `fn` with a server client and capture the outcome.
 *
 * Every failure becomes `{ ok: false, error }` with the same fields a route
 * handler would have sent.
 */
export async function runBookroomAction<T>(
  fn: (client: Bookroom) => Promise<T>,
  options: BookroomServerIntegrationOptions = {},
): Promise<ActionResult<T>> {
  try {
    return { ok: true, data: await fn(getServerBookroom(options)) };
  } catch (raw) {
    return { ok: false, error: toClientError(raw) };
  }
}

function requireText(value: string | undefined, field: string): string {
  if (value === undefined || value.trim() === '') {
    throw new BookroomConfigError(`${field} is required and must not be empty.`);
  }
  return value;
}

/** Input for {@link createSummarizeAction}. */
export interface SummarizeActionInput {
  /** Source book, resolved on the server that runs the job. */
  path: string;
  outputSlug?: string;
  review?: boolean;
  options?: SummarizeOptions;
}

/** A server action that starts a study-guide job and returns immediately. */
export type SummarizeAction = (input: SummarizeActionInput) => Promise<ActionResult<ClientJob>>;

/**
 * Build a server action that starts a study guide as a background job.
 *
 * The action returns as soon as the job exists, so a client component can start
 * a run and poll separately without holding a request open for minutes.
 *
 * ```ts
 * 'use server';
 * export const startStudyGuide = createSummarizeAction();
 * ```
 */
export function createSummarizeAction(
  options: BookroomServerIntegrationOptions = {},
): SummarizeAction {
  return async (input: SummarizeActionInput): Promise<ActionResult<ClientJob>> =>
    runBookroomAction(async (client) => {
      const request: StartStudyGuideRequest = { path: requireText(input?.path, 'path') };
      if (input.outputSlug !== undefined) request.outputSlug = input.outputSlug;
      if (input.review !== undefined) request.review = input.review;
      if (input.options !== undefined) request.options = input.options;
      const snapshot = await client.jobs.studyGuide(request);
      return toClientJob(snapshot, options);
    }, options);
}

/** Input for {@link createJobStatusAction}. */
export interface JobStatusActionInput {
  id: string;
}

/** A server action that returns one job's browser-safe snapshot. */
export type JobStatusAction = (input: JobStatusActionInput) => Promise<ActionResult<ClientJob>>;

/**
 * Build a server action that returns a job snapshot.
 *
 * ```ts
 * 'use server';
 * export const jobStatus = createJobStatusAction();
 * const snapshot = await jobStatus({ id });
 * ```
 */
export function createJobStatusAction(
  options: BookroomServerIntegrationOptions = {},
): JobStatusAction {
  return async (input: JobStatusActionInput): Promise<ActionResult<ClientJob>> =>
    runBookroomAction(async (client) => {
      const id = requireText(input?.id, 'id');
      const snapshot = await client.jobs.get(id, {
        ...(options.messages === false ? {} : { messages: true }),
      });
      return toClientJob(snapshot, options);
    }, options);
}

/** Input for {@link createPreflightAction}. */
export interface PreflightActionInput {
  path: string;
  options?: SummarizeOptions;
}

/** A server action that estimates the cost of a run before it starts. */
export type PreflightAction = (input: PreflightActionInput) => Promise<ActionResult<Preflight>>;

/**
 * Build a server action that runs the server's own cost estimate.
 *
 * The facade enforces its budget caps here, so an over-budget book fails in the
 * preflight rather than partway through a paid run.
 */
export function createPreflightAction(
  options: BookroomServerIntegrationOptions = {},
): PreflightAction {
  return async (input: PreflightActionInput): Promise<ActionResult<Preflight>> =>
    runBookroomAction(async (client) => {
      const request: { path: string; options?: SummarizeOptions } = {
        path: requireText(input?.path, 'path'),
      };
      if (input.options !== undefined) request.options = input.options;
      return client.summarize.preflight(request);
    }, options);
}

/** The study-guide job request, as accepted by `jobs.studyGuide`. */
type StartStudyGuideRequest = Parameters<Bookroom['jobs']['studyGuide']>[0];

/* -------------------------------------------------------------------------- */
/* Route handlers                                                              */
/* -------------------------------------------------------------------------- */

/** The slice of a web `Request` this module uses. */
export interface RouteRequestLike {
  readonly method: string;
  readonly url: string;
  readonly headers: { get(name: string): string | null };
  json(): Promise<unknown>;
  /** Aborted when the client disconnects, so the facade call is cancelled too. */
  readonly signal?: AbortSignal;
}

/** Route params, as Next.js passes them. Values may be arrays for catch-alls. */
export type RouteParams = Record<string, string | string[] | undefined>;

/**
 * Route params as a handler argument.
 *
 * Next.js 15 hands them to the handler as a promise; earlier versions pass a
 * plain object. Both are accepted.
 */
export type RouteParamsInput = RouteParams | PromiseLike<RouteParams>;

/** The slice of the `Headers` interface this module uses. */
export interface ResponseHeadersLike {
  get(name: string): string | null;
  has(name: string): boolean;
  set(name: string, value: string): void;
}

/**
 * A structural stand-in for the global `Response`.
 *
 * Declaring it here keeps this file compilable without a DOM lib or `@types/node`,
 * while a real `Response` still satisfies it, so a Next.js route handler can
 * return the result directly.
 */
export interface RouteResponseLike {
  readonly status: number;
  readonly ok: boolean;
  readonly headers: ResponseHeadersLike;
  text(): Promise<string>;
  json(): Promise<unknown>;
}

type ResponseConstructorLike = new (
  body?: string | null,
  init?: { status?: number; headers?: Record<string, string> },
) => RouteResponseLike;

/** Resolve the global `Response`, with a clear message when there is none. */
function responseConstructor(): ResponseConstructorLike {
  const candidate = (globalThis as { Response?: ResponseConstructorLike }).Response;
  if (typeof candidate !== 'function') {
    throw new BookroomConfigError(
      'No global Response is available. Use Node 18 or newer, or an edge runtime.',
    );
  }
  return candidate;
}

/**
 * Build a JSON response.
 *
 * Returns a real `Response`, so a route handler can return it as-is.
 */
export function jsonResponse(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): RouteResponseLike {
  const ResponseCtor = responseConstructor();
  return new ResponseCtor(JSON.stringify(body ?? null), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', ...headers },
  });
}

/** What a route function receives. */
export interface BookroomRouteContext {
  /** Params from the route path, already awaited. */
  params: RouteParams;
  /** The incoming request. */
  request: RouteRequestLike;
  /** A token-bearing client built from the server environment. */
  client: Bookroom;
  /** The request's abort signal, or `undefined` when it has none. */
  signal: AbortSignal | undefined;
}

/** The route function `handleBookroomRequest` adapts. */
export type BookroomRoute = (context: BookroomRouteContext) => Promise<unknown> | unknown;

/** Status for each facade and client-side error code. */
const ERROR_STATUS: Record<string, number> = {
  invalid_request: 400,
  configuration_error: 503,
  unsupported_source: 415,
  extraction_failed: 422,
  budget_exceeded: 400,
  quota_exceeded: 429,
  provider_error: 502,
  cancelled: 409,
  application_load_failed: 503,
  sdk_error: 500,
  internal_error: 500,
  not_found: 404,
  unauthorized: 401,
  conflict: 409,
  timeout: 408,
  aborted: 499,
  network_error: 502,
  invalid_response: 502,
  job_failed: 500,
};

/**
 * Pick the HTTP status for an error.
 *
 * The SDK's own status wins when it is a real status, so `408` for a timeout and
 * `409` for a conflict survive unchanged. Otherwise the code decides, and a
 * transport failure that never saw a response becomes `502 Bad Gateway`, which is
 * what actually happened from the browser's point of view.
 */
export function errorStatus(error: BookroomError): number {
  const status = error.status;
  if (status >= 400 && status <= 599 && status !== 499) return status;
  const mapped = ERROR_STATUS[error.code];
  if (mapped !== undefined) return mapped;
  return status === 0 ? 502 : 500;
}

/** Options for {@link handleBookroomRequest}. */
export interface HandleBookroomRequestOptions extends BookroomServerIntegrationOptions {
  /** Methods this route accepts. Others get 405 with an `Allow` header. */
  methods?: readonly string[];
  /** Status for a successful response. Defaults to 200, or 201 for POST. */
  status?: number;
  /** Replace the response body or status before it is sent. */
  toResponse?: (
    value: unknown,
    context: BookroomRouteContext,
  ) => { status?: number; body?: unknown } | void;
  /** Override the status chosen for a failure. */
  statusForError?: (error: BookroomError) => number;
}

/**
 * Adapt a Next.js route handler to this SDK.
 *
 * It reads the request, gives your function a token-bearing client, and turns
 * whatever comes back into a JSON response. Failures become the right status for
 * their cause: `404` for an unknown job, `409` for a conflict, `429` plus a
 * `Retry-After` header for a provider quota, `502` when the facade is
 * unreachable. The error body is always `{ error: ClientError }`.
 *
 * Pass the third argument straight through from the handler, because Next.js 15
 * supplies `params` as a promise.
 */
export async function handleBookroomRequest(
  route: BookroomRoute,
  request: RouteRequestLike,
  params?: RouteParamsInput,
  options: HandleBookroomRequestOptions = {},
): Promise<RouteResponseLike> {
  const method = request.method.toUpperCase();
  const allowed = options.methods?.map((value) => value.toUpperCase());
  if (allowed !== undefined && !allowed.includes(method)) {
    return jsonResponse(
      {
        error: {
          name: 'BookroomError',
          code: 'invalid_request',
          status: 405,
          message: `${method} is not allowed on this route.`,
        },
      },
      405,
      { allow: allowed.join(', ') },
    );
  }

  try {
    const context: BookroomRouteContext = {
      params: params === undefined ? {} : await params,
      request,
      client: getServerBookroom(options),
      signal: request.signal,
    };
    const value = await route(context);
    const shaped = options.toResponse?.(value, context);
    const hasBody = typeof shaped === 'object' && shaped !== null && shaped.body !== undefined;
    const body = hasBody ? shaped.body : value;
    const status =
      (typeof shaped === 'object' && shaped !== null ? shaped.status : undefined) ??
      options.status ??
      (method === 'POST' ? 201 : 200);
    return jsonResponse(body ?? null, status);
  } catch (raw) {
    const error = normalizeError(raw);
    const headers: Record<string, string> = {};
    if (error.retryAfterSeconds !== undefined) {
      headers['retry-after'] = String(Math.max(0, Math.ceil(error.retryAfterSeconds)));
    }
    const status = options.statusForError?.(error) ?? errorStatus(error);
    return jsonResponse({ error: toClientError(error) }, status, headers);
  }
}