/**
 * The `Bookroom` client: one object exposing every wrapped capability.
 *
 * Start the facade server once, then point any client at it:
 *
 * ```ts
 * import { Bookroom } from 'bookroom-sdk';
 *
 * const bookroom = new Bookroom({ baseUrl: 'http://127.0.0.1:8787' });
 * const report = await bookroom.summarize.studyGuide({ path: '/books/attention.epub' });
 * console.log(report.markdown.path);
 * ```
 *
 * The caller supplies only the facade's own token, when the server was started
 * with one. The LLM and JEv API keys live in the server process and are never
 * required, requested, or transmitted by this client.
 */

import { joinAppRoot, resolveConfig } from './config.js';
import type { BookroomClientOptions, ResolvedConfig } from './config.js';
import { HttpTransport } from './http.js';
import type { CallOptions } from './http.js';
import { ExportApi } from './resources/export.js';
import { ExtractApi } from './resources/extract.js';
import { HealthApi } from './resources/health.js';
import { JobsApi } from './resources/jobs.js';
import type { WaitForJobOptions } from './resources/jobs.js';
import { ReviewApi } from './resources/review.js';
import { SummarizeApi } from './resources/summarize.js';
import { TranslateApi } from './resources/translate.js';
import type {
  HealthReport,
  JobSnapshot,
  ProviderUsage,
  ReportSection,
  ServerDescription,
  ServerHealth,
} from './types.js';

/** SDK version, matching the facade server it talks to. */
export const VERSION = '1.0.0';

/** The whole client surface. */
export class Bookroom {
  /** The resolved configuration, after options, environment, and defaults. */
  readonly config: ResolvedConfig;

  /** The HTTP transport, for callers who need a route this SDK does not wrap. */
  readonly transport: HttpTransport;

  /** Reachability, provider checks, capabilities, and the category list. */
  readonly health: HealthApi;

  /** EPUB and PDF extraction: sections, locators, outline, metadata. */
  readonly extract: ExtractApi;

  /** Chapter notes, digests, and complete study guides. */
  readonly summarize: SummarizeApi;

  /** JEv scoring and the 16-category quality gate. */
  readonly review: ReviewApi;

  /** Markdown, PDF, concept map, claims, manifest, usage, merging. */
  readonly export: ExportApi;

  /** Translation and chapter classification on the alternate transport. */
  readonly translate: TranslateApi;

  /** Background jobs for runs that take minutes. */
  readonly jobs: JobsApi;

  constructor(options: BookroomClientOptions = {}) {
    this.config = resolveConfig(options);
    this.transport = new HttpTransport(this.config);
    this.health = new HealthApi(this.transport);
    this.extract = new ExtractApi(this.transport);
    this.summarize = new SummarizeApi(this.transport);
    this.review = new ReviewApi(this.transport);
    this.export = new ExportApi(this.transport);
    this.translate = new TranslateApi(this.transport);
    this.jobs = new JobsApi(this.transport);
  }

  /**
   * Build a client from `BOOKROOM_*` environment variables.
   *
   * Convenience for the common case; explicit options still win.
   */
  static fromEnv(options: BookroomClientOptions = {}): Bookroom {
    return new Bookroom(options);
  }

  /**
   * A reconfigured copy that shares nothing with this one.
   *
   * Useful for a per-request timeout or a different token without mutating a
   * long-lived client.
   */
  withOptions(overrides: BookroomClientOptions): Bookroom {
    const token = overrides.token ?? this.config.token;
    const appRoot = overrides.appRoot ?? this.config.appRoot;
    const userAgent = overrides.userAgent ?? this.config.userAgent;
    return new Bookroom({
      baseUrl: overrides.baseUrl ?? this.config.baseUrl,
      timeoutMs: overrides.timeoutMs ?? this.config.timeoutMs,
      longRunningTimeoutMs: overrides.longRunningTimeoutMs ?? this.config.longRunningTimeoutMs,
      maxRetries: overrides.maxRetries ?? this.config.maxRetries,
      retryBaseDelayMs: overrides.retryBaseDelayMs ?? this.config.retryBaseDelayMs,
      retryMaxDelayMs: overrides.retryMaxDelayMs ?? this.config.retryMaxDelayMs,
      retryOnNetworkError: overrides.retryOnNetworkError ?? this.config.retryOnNetworkError,
      fetch: overrides.fetch ?? this.config.fetch,
      defaultHeaders: { ...this.config.defaultHeaders, ...overrides.defaultHeaders },
      ...(token !== undefined ? { token } : {}),
      ...(appRoot !== undefined ? { appRoot } : {}),
      ...(userAgent !== undefined ? { userAgent } : {}),
      ...overrides.env,
      ...(overrides.readEnv !== undefined ? { readEnv: overrides.readEnv } : {}),
    });
  }

  /** `GET /healthz` */
  ping(options?: CallOptions): Promise<ServerHealth> {
    return this.health.ping(options);
  }

  /** `GET /v1/check` — verify both providers before spending anything. */
  check(options?: CallOptions): Promise<HealthReport> {
    return this.health.check(options);
  }

  /** `GET /v1/describe` — the server's secret-free configuration and capabilities. */
  describe(options?: CallOptions): Promise<ServerDescription> {
    return this.health.describe(options);
  }

  /** `GET /v1/capabilities` */
  capabilities(options?: CallOptions): Promise<string[]> {
    return this.health.capabilities(options);
  }

  /** `GET /v1/sections` */
  sections(options?: CallOptions): Promise<ReportSection[]> {
    return this.health.sections(options);
  }

  /** `GET /v1/ocr-languages` */
  ocrLanguages(options?: CallOptions): Promise<string[]> {
    return this.health.ocrLanguages(options);
  }

  /** `GET /v1/usage` */
  usage(options?: CallOptions): Promise<ProviderUsage> {
    return this.export.usage(options);
  }

  /**
   * Poll a job until it finishes.
   *
   * Delegates to {@link JobsApi.waitFor}; provided here because job polling is
   * the operation most callers reach for first.
   */
  waitForJob(id: string, options?: WaitForJobOptions): Promise<JobSnapshot> {
    return this.jobs.waitFor(id, options ?? {});
  }

  /**
   * The configured app root, when one was set.
   *
   * Local only, and never sent to the server.
   */
  get appRoot(): string | undefined {
    return this.config.appRoot;
  }

  /**
   * Expand a possibly relative path against the app root, for readable logs.
   *
   * The server resolves paths on its own filesystem, so this value is only for
   * messages you print yourself.
   */
  resolvePath(path: string): string {
    const root = this.config.appRoot;
    return root === undefined ? path : joinAppRoot(root, path);
  }

  /** A short description with no secrets in it. */
  toString(): string {
    return (
      `Bookroom(sdk=${VERSION}, url=${this.config.baseUrl}, ` +
      `auth=${this.config.token === undefined ? 'none' : 'bearer'}, ` +
      `timeout=${this.config.timeoutMs}ms)`
    );
  }
}
