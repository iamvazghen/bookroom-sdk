/**
 * `bookroom-sdk` — a typed client for the Bookroom book-summarizer facade.
 *
 * The client needs only the facade's own token, when the server has one. The
 * LLM and JEv API keys stay in the server process; this package never asks for
 * them and never sends them.
 *
 * ```ts
 * import { Bookroom, isQuotaError } from 'bookroom-sdk';
 *
 * const bookroom = new Bookroom({ baseUrl: 'http://127.0.0.1:8787' });
 *
 * try {
 *   const report = await bookroom.summarize.studyGuide({ path: '/books/attention.epub' });
 *   console.log(report.markdown.path);
 * } catch (error) {
 *   if (isQuotaError(error)) console.error('Retry later:', error.retryAfterSeconds);
 *   else throw error;
 * }
 * ```
 *
 * @packageDocumentation
 */

export { Bookroom, VERSION } from './client.js';

export {
  DEFAULT_BASE_URL,
  DEFAULT_LONG_TIMEOUT_MS,
  DEFAULT_MAX_RETRIES,
  DEFAULT_RETRY_BASE_DELAY_MS,
  DEFAULT_RETRY_MAX_DELAY_MS,
  DEFAULT_TIMEOUT_MS,
  globalFetch,
  joinAppRoot,
  readProcessEnv,
  resolveConfig,
} from './config.js';
export type {
  BookroomClientOptions,
  EnvironmentLike,
  FetchLike,
  HttpResponseLike,
  RequestInitLike,
  ResolvedConfig,
} from './config.js';

export {
  BookroomAbortError,
  BookroomConfigError,
  BookroomError,
  BookroomJobError,
  BookroomNetworkError,
  BookroomProtocolError,
  BookroomTimeoutError,
  hasErrorCode,
  isBookroomError,
  isBudgetExceededError,
  isCancelledError,
  isConfigurationError,
  isConflictError,
  isExtractionFailedError,
  isJobFailedError,
  isNotFoundError,
  isProviderError,
  isQuotaError,
  isRetryableError,
  isTimeoutError,
  isUnauthorizedError,
  isUnsupportedSourceError,
  retryDelaySeconds,
} from './errors.js';
export type { BookroomErrorInit } from './errors.js';

export { HttpTransport } from './http.js';
export type { CallOptions, QueryValue, RequestSpec } from './http.js';

export { ExportApi } from './resources/export.js';
export type {
  ClaimAuditRequest,
  ManifestRequest,
  MergeRequest,
  PdfRequest,
  RenderRequest,
} from './resources/export.js';

export { ExtractApi } from './resources/extract.js';
export type { ExtractRequest } from './resources/extract.js';

export { HealthApi } from './resources/health.js';

export { isTerminalStatus, JobsApi } from './resources/jobs.js';
export type { CreateJobRequest, ReviewReportJobRequest, WaitForJobOptions } from './resources/jobs.js';

export { ReviewApi } from './resources/review.js';
export type { EvaluateRequest, EvaluateSectionRequest } from './resources/review.js';

export { SummarizeApi } from './resources/summarize.js';
export type {
  DigestRequest,
  PreflightRequest,
  StudyGuideRequest,
  SummarizeSectionRequest,
  SummarizeTextRequest,
} from './resources/summarize.js';

export { TranslateApi } from './resources/translate.js';
export type { TranslateBatchRequest, TranslateRequest } from './resources/translate.js';

/* -------------------------------------------------------------------------- */
/* Next.js server integration                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Server-side helpers for Next.js: a cached token-bearing client, server action
 * factories, route-handler adaptation, and the client-safe payload types.
 *
 * This module has no runtime dependency of its own, so it is safe to export from
 * the package entry point.
 */
export {
  clearServerBookroomCache,
  createJobStatusAction,
  createPreflightAction,
  createSummarizeAction,
  errorStatus,
  getJobForClient,
  getServerBookroom,
  handleBookroomRequest,
  jsonResponse,
  runBookroomAction,
  SERVER_ENV_VARS,
  toClientError,
  toClientJob,
  toClientReport,
} from './next.js';
export type {
  ActionResult,
  BookroomRoute,
  BookroomRouteContext,
  BookroomServerIntegrationOptions,
  ClientArtifact,
  ClientError,
  ClientJob,
  ClientPayloadOptions,
  ClientQualitySummary,
  ClientReportSummary,
  GetJobForClientOptions,
  HandleBookroomRequestOptions,
  JobStatusAction,
  JobStatusActionInput,
  PreflightAction,
  PreflightActionInput,
  ResponseHeadersLike,
  RouteParams,
  RouteParamsInput,
  RouteRequestLike,
  RouteResponseLike,
  ServerBookroomOptions,
  SummarizeAction,
  SummarizeActionInput,
} from './next.js';

/* -------------------------------------------------------------------------- */
/* React bindings                                                              */
/* -------------------------------------------------------------------------- */

/*
 * The React bindings in `src/react.tsx` are deliberately NOT re-exported here.
 *
 * `react` is an optional peer dependency, so importing `src/react.tsx` pulls in
 * the `react` package and its JSX types. A bare value or type re-export from
 * this entry point would therefore make `import 'bookroom-sdk'` fail to
 * typecheck in a plain Node or server project that has no React installed,
 * which is the common case for this SDK.
 *
 * Import the runtime surface from the subpath instead, once the package
 * `exports` map declares it:
 *
 *   "exports": {
 *     ".":       { "types": "./dist/index.d.ts",  "default": "./dist/index.js" },
 *     "./react": { "types": "./dist/react.d.ts",  "default": "./dist/react.js" }
 *   }
 *
 *   import { StudyGuidePanel, useBookroomJob } from 'bookroom-sdk/react';
 *
 * `package.json` is owned by the SDK maintainer, so the map above is a request,
 * not something this entry point can do for itself. The React public API is
 * listed in `src/react.tsx` and documented in `examples/react/README.md`.
 */

export type * from './types.js';
