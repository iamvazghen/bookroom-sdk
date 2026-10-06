'use client';

/**
 * React bindings for the Bookroom SDK.
 *
 * Everything in this module runs in the browser, so it talks to a backend **you**
 * control that proxies to the facade. It never holds the facade token: the token
 * lives in your server process, and this module refuses to accept one in a
 * browser context.
 *
 * ```tsx
 * 'use client';
 * import { useBookroomJob, StudyGuidePanel } from 'bookroom-sdk/react';
 *
 * export function Panel() {
 *   const job = useBookroomJob({ path: '/books/attention.epub', pollIntervalMs: 1500 });
 *   return <StudyGuidePanel {...job} />;
 * }
 * ```
 *
 * A full study guide takes minutes, so this module is built around the
 * asynchronous job API: `useBookroomJob` starts a job, polls it, and exposes
 * progress without blocking a render.
 *
 * `src/next.ts` holds the server-side half of the same integration: it builds a
 * token-bearing client and forwards the calls this module makes.
 *
 * @packageDocumentation
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { CSSProperties, ReactNode } from 'react';

import { Bookroom } from './client.js';
import type { BookroomClientOptions } from './config.js';
import { BookroomConfigError, BookroomError } from './errors.js';
import { isBookroomError } from './errors.js';
import type { CallOptions } from './http.js';
import { isTerminalStatus } from './resources/jobs.js';
import type { CreateJobRequest } from './resources/jobs.js';
import type {
  Artifact,
  HealthReport,
  JobSnapshot,
  JobStatus,
  Report,
  ServerDescription,
  SummarizeOptions,
} from './types.js';

/* -------------------------------------------------------------------------- */
/* Errors                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Normalize anything thrown into a {@link BookroomError}.
 *
 * Hooks never hand a raw exception to a component: a non-SDK failure (a bad
 * `baseUrl`, a `TypeError` from the runtime) is wrapped so that every `error`
 * field in this module has the same `code`, `status`, and `message` shape.
 */
export function toBookroomError(value: unknown, fallbackMessage?: string): BookroomError {
  if (isBookroomError(value)) return value;
  if (value instanceof Error) {
    return new BookroomError(value.message, { code: 'internal_error', status: 0, cause: value });
  }
  const message = fallbackMessage ?? `The request failed: ${String(value)}`;
  return new BookroomError(message, { code: 'internal_error', status: 0, cause: value });
}

/* -------------------------------------------------------------------------- */
/* Client construction                                                         */
/* -------------------------------------------------------------------------- */

/** Options for {@link useBookroomClient}. */
export type UseBookroomClientOptions = BookroomClientOptions;

/**
 * Proxy path used when no `baseUrl` is given and the page runs in a browser.
 *
 * A Next.js or Vite app usually mounts its proxy at this path; override it with
 * an explicit `baseUrl` when yours lives elsewhere.
 */
export const DEFAULT_PROXY_PATH = '/api/bookroom';

/**
 * Resolve the base URL a browser client should use.
 *
 * An absolute `http(s)` URL is used as-is. A path starting with `/` is resolved
 * against `window.location.origin`, which is what makes the hook work unchanged
 * behind a same-origin proxy. With neither, and no browser to ask, the caller
 * gets a configuration error rather than a silent fallback to `127.0.0.1`.
 */
function resolveBrowserBaseUrl(options: UseBookroomClientOptions): string {
  const configured = options.baseUrl?.trim();
  if (configured !== undefined && configured !== '') {
    if (configured.startsWith('/')) {
      const origin = typeof window === 'undefined' ? undefined : window.location?.origin;
      if (origin === undefined || origin === '') {
        throw new BookroomConfigError(
          `useBookroomClient: baseUrl "${configured}" is relative and this component is ` +
            'rendering on the server, where there is no origin to resolve it against. ' +
            'Pass an absolute URL, or load the component client-only.',
        );
      }
      return `${origin.replace(/\/+$/, '')}${configured}`;
    }
    return configured;
  }
  if (typeof window !== 'undefined' && typeof window.location?.origin === 'string') {
    return `${window.location.origin.replace(/\/+$/, '')}${DEFAULT_PROXY_PATH}`;
  }
  throw new BookroomConfigError(
    'useBookroomClient: baseUrl is required. Pass the URL of your own proxy, which holds ' +
      `the facade token, or pass a path such as "${DEFAULT_PROXY_PATH}".`,
  );
}

/** Build a client, refusing to place a facade token in a browser. */
function createBrowserClient(options: UseBookroomClientOptions): Bookroom {
  if (options.token !== undefined && typeof window !== 'undefined') {
    throw new BookroomConfigError(
      'useBookroomClient: never pass a facade token in the browser. Anyone can read it from ' +
        'the page source or the network tab. Point baseUrl at your own proxy and let the ' +
        'server attach the token.',
    );
  }
  const baseUrl = resolveBrowserBaseUrl(options);
  try {
    return new Bookroom({ ...options, baseUrl });
  } catch (cause) {
    throw toBookroomError(cause, `Could not create a Bookroom client for ${baseUrl}.`);
  }
}

/** The part of the client options that changes the client identity. */
function clientCacheKey(options: UseBookroomClientOptions): string {
  const { baseUrl, token, timeoutMs, longRunningTimeoutMs, maxRetries, appRoot, userAgent } = options;
  return JSON.stringify([
    baseUrl ?? null,
    token ?? null,
    timeoutMs ?? null,
    longRunningTimeoutMs ?? null,
    maxRetries ?? null,
    appRoot ?? null,
    userAgent ?? null,
  ]);
}

/**
 * A memoized factory that builds a client only when one is actually needed.
 *
 * Construction is deferred so that a component with an explicit client, or one
 * under a {@link BookroomProvider}, is never affected by a bad proxy URL it does
 * not use.
 */
function useBookroomClientFactory(
  options: UseBookroomClientOptions | undefined,
): () => Bookroom {
  const resolved = options ?? {};
  const key = clientCacheKey(resolved);
  const ref = useRef<{ key: string; make: () => Bookroom } | null>(null);
  if (ref.current === null || ref.current.key !== key) {
    const captured = resolved;
    ref.current = { key, make: () => createBrowserClient(captured) };
  }
  return ref.current.make;
}

/**
 * Create and memoize a client for your proxy.
 *
 * The client is rebuilt only when a connection-affecting option changes, so it
 * is safe to call on every render. It never reads a facade token from the
 * environment, because a browser has no environment and should not have a token.
 *
 * ```tsx
 * const bookroom = useBookroomClient({ baseUrl: '/api/bookroom' });
 * ```
 *
 * When a {@link BookroomProvider} is present, {@link useBookroomJob} and the
 * one-shot hooks use its client instead, so calling this hook is optional there.
 */
export function useBookroomClient(options: UseBookroomClientOptions = {}): Bookroom {
  const make = useBookroomClientFactory(options);
  return make();
}

/* -------------------------------------------------------------------------- */
/* Context                                                                     */
/* -------------------------------------------------------------------------- */

/** The client shared by {@link BookroomProvider}. */
const BookroomContext = createContext<Bookroom | null>(null);

/** Props for {@link BookroomProvider}. */
export interface BookroomProviderProps {
  /** A client built by the caller, normally with {@link useBookroomClient}. */
  client: Bookroom;
  children?: ReactNode;
}

/**
 * Share one client across a React tree.
 *
 * ```tsx
 * <BookroomProvider client={useBookroomClient({ baseUrl: '/api/bookroom' })}>
 *   <App />
 * </BookroomProvider>
 * ```
 */
export function BookroomProvider({ client, children }: BookroomProviderProps): ReactNode {
  return <BookroomContext.Provider value={client}>{children}</BookroomContext.Provider>;
}

/** The shared client, or `null` when no provider is mounted. */
export function useOptionalBookroomClient(): Bookroom | null {
  return useContext(BookroomContext);
}

/**
 * The shared client.
 *
 * Throws a {@link BookroomConfigError} when there is no provider, which is the
 * one mistake that would otherwise show up as a confusing null client.
 */
export function useBookroomContext(): Bookroom {
  const client = useOptionalBookroomClient();
  if (client === null) {
    throw new BookroomConfigError(
      'useBookroomContext: no BookroomProvider is mounted above this component. ' +
        'Wrap the tree in <BookroomProvider client={...}>, or pass a client explicitly.',
    );
  }
  return client;
}

/** How a hook picks the client it talks to. */
export interface UseBookroomHookOptions {
  /** Use this client instead of the shared or derived one. */
  client?: Bookroom;
  /** How to build a client when there is no provider. */
  proxy?: UseBookroomClientOptions;
}

/** Resolve a client for a hook that needs one immediately, or fail clearly. */
function useResolvedClient(options: UseBookroomHookOptions | undefined): Bookroom {
  const contextClient = useOptionalBookroomClient();
  const make = useBookroomClientFactory(options?.proxy);
  if (options?.client !== undefined) return options.client;
  if (contextClient !== null) return contextClient;
  try {
    return make();
  } catch (cause) {
    throw toBookroomError(cause);
  }
}

/**
 * A lazy client resolver.
 *
 * `useBookroomJob` only needs a client when a run actually starts, so building it
 * at render time would fail a component that has not been asked to do anything
 * yet. The factory defers that decision to `start()`, where a configuration
 * problem becomes a normal `error` value instead of a render crash.
 */
function useClientFactory(options: UseBookroomHookOptions | undefined): () => Bookroom {
  const contextClient = useOptionalBookroomClient();
  const make = useBookroomClientFactory(options?.proxy);
  const explicit = options?.client;
  return useCallback(() => {
    if (explicit !== undefined) return explicit;
    if (contextClient !== null) return contextClient;
    try {
      return make();
    } catch (cause) {
      throw toBookroomError(cause);
    }
  }, [contextClient, explicit, make]);
}

/* -------------------------------------------------------------------------- */
/* useBookroomJob                                                              */
/* -------------------------------------------------------------------------- */

/** The request body of a study-guide job, minus the fixed `kind`. */
export type StartStudyGuideInput = Omit<CreateJobRequest, 'kind'>;

/** Options for {@link useBookroomJob}. */
export interface UseBookroomJobOptions {
  /** Source book, resolved by the server that runs the job. */
  path: string;
  /** Output folder name; the server picks one when omitted. */
  outputSlug?: string;
  /** JEv quality gate switch; the server decides when omitted. */
  review?: boolean;
  /** Reader-facing preferences forwarded to the server's prompt builder. */
  summarizeOptions?: SummarizeOptions;
  /** Delay between polls in milliseconds. Defaults to the SDK default (500). */
  pollIntervalMs?: number;
  /** Give up polling after this many milliseconds. Defaults to the long timeout. */
  timeoutMs?: number;
  /** Start as soon as the hook mounts. Defaults to `false`. */
  autoStart?: boolean;
  /** Use this client instead of the shared or derived one. */
  client?: Bookroom;
  /** How to build a client when there is no provider. */
  proxy?: UseBookroomClientOptions;
}

/** What {@link useBookroomJob} returns. */
export interface UseBookroomJobResult {
  /** `idle` before the first start, then the server's own job status. */
  status: JobStatus | 'idle';
  /** The job id, once one has been created. */
  jobId: string | null;
  /** The most recent raw snapshot from the server. */
  snapshot: JobSnapshot | null;
  /**
   * Completion as a fraction between 0 and 1.
   *
   * `null` while the job is in flight: the facade reports progress messages and
   * a message count, but never a percentage. Use `messages.length` to show
   * activity, and treat a null progress as indeterminate rather than inventing a
   * number.
   */
  progress: number | null;
  /** Progress messages, newest last. */
  messages: string[];
  /** The finished report, when the job succeeded. */
  result: Report | null;
  /** The failure, as a {@link BookroomError}. */
  error: BookroomError | null;
  /** True between a start and a stop watching. */
  isRunning: boolean;
  startedAt: number | null;
  finishedAt: number | null;
  /** Start a job. Merges `overrides` over the hook's own input. */
  start: (overrides?: StartStudyGuideInput) => Promise<void>;
  /**
   * Stop polling.
   *
   * This ends this browser tab's interest in the job; the facade keeps running
   * it, because the facade exposes no cancel route. The last snapshot stays
   * visible so the UI can say so honestly.
   */
  cancel: () => void;
  /** Return to the initial state, forgetting the job and its messages. */
  reset: () => void;
}

interface JobState {
  status: JobStatus | 'idle';
  jobId: string | null;
  snapshot: JobSnapshot | null;
  messages: string[];
  result: Report | null;
  error: BookroomError | null;
  isRunning: boolean;
  startedAt: number | null;
  finishedAt: number | null;
}

const INITIAL_JOB_STATE: JobState = {
  status: 'idle',
  jobId: null,
  snapshot: null,
  messages: [],
  result: null,
  error: null,
  isRunning: false,
  startedAt: null,
  finishedAt: null,
};

/** Narrow an untyped job result to a {@link Report}. */
function asReport(value: unknown): Report | null {
  if (typeof value !== 'object' || value === null) return null;
  const candidate = value as Partial<Report>;
  if (typeof candidate.output_dir !== 'string') return null;
  if (!Array.isArray(candidate.artifacts)) return null;
  return candidate as Report;
}

/**
 * Start a study-guide job and follow it to completion.
 *
 * The hook creates the job through `jobs.studyGuide(...)`, then polls with
 * `jobs.waitFor(...)`, pushing every snapshot into state. Polling stops on
 * unmount, on {@link UseBookroomJobResult.cancel}, and on terminal status.
 *
 * ```tsx
 * const job = useBookroomJob({ path: '/books/attention.epub', pollIntervalMs: 1500 });
 * return <button onClick={() => void job.start()}>Generate</button>;
 * ```
 */
export function useBookroomJob(options: UseBookroomJobOptions): UseBookroomJobResult {
  // `exactOptionalPropertyTypes` means an optional key may be absent but must
  // not be present-and-undefined, so forward only what the caller actually set.
  const getClient = useClientFactory({
    ...(options.client === undefined ? {} : { client: options.client }),
    ...(options.proxy === undefined ? {} : { proxy: options.proxy }),
  });
  const [state, setState] = useState<JobState>(INITIAL_JOB_STATE);

  const controllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const autoStartKeyRef = useRef<string | null>(null);

  const { path, outputSlug, review, summarizeOptions, pollIntervalMs, timeoutMs } = options;

  const input = useMemo<StartStudyGuideInput>(() => {
    const merged: StartStudyGuideInput = { path };
    if (outputSlug !== undefined) merged.outputSlug = outputSlug;
    if (review !== undefined) merged.review = review;
    if (summarizeOptions !== undefined) merged.options = summarizeOptions;
    return merged;
  }, [path, outputSlug, review, summarizeOptions]);

  const inputKey = useMemo(() => JSON.stringify(input), [input]);

  /** Copy a snapshot into state, ignoring updates after unmount. */
  const applySnapshot = useCallback((snapshot: JobSnapshot) => {
    if (!mountedRef.current) return;
    setState((previous) => ({
      ...previous,
      jobId: snapshot.id,
      status: snapshot.status,
      snapshot,
      messages: snapshot.messages ?? previous.messages,
    }));
  }, []);

  const run = useCallback(
    async (overrides: StartStudyGuideInput | undefined): Promise<void> => {
      const request: StartStudyGuideInput = { ...input, ...overrides };
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;

      setState({ ...INITIAL_JOB_STATE, isRunning: true, startedAt: Date.now() });

      // Built here rather than at render time, so a missing proxy URL surfaces
      // as an error in the panel instead of crashing the component.
      let client: Bookroom;
      try {
        client = getClient();
      } catch (cause) {
        setState((previous) => ({
          ...previous,
          error: toBookroomError(cause),
          isRunning: false,
          finishedAt: Date.now(),
        }));
        return;
      }

      const callOptions: CallOptions = { signal: controller.signal };
      try {
        const started = await client.jobs.studyGuide(request, callOptions);
        if (!mountedRef.current || controller.signal.aborted) return;
        applySnapshot(started);

        const finished = await client.jobs.waitFor(started.id, {
          ...(pollIntervalMs !== undefined ? { pollIntervalMs } : {}),
          ...(timeoutMs !== undefined ? { timeoutMs } : {}),
          messages: true,
          signal: controller.signal,
          onUpdate: applySnapshot,
        });
        if (!mountedRef.current) return;
        setState((previous) => ({
          ...previous,
          status: 'succeeded',
          snapshot: finished,
          messages: finished.messages ?? previous.messages,
          result: asReport(finished.result),
          progress: 1,
          isRunning: false,
          finishedAt: Date.now(),
          error: null,
        }));
      } catch (raw) {
        const error = toBookroomError(raw);
        if (!mountedRef.current) return;
        if (error.code === 'aborted') {
          // cancel(), unmount, or a superseded start: stop the spinner and keep
          // whatever the server last told us.
          setState((previous) => ({ ...previous, isRunning: false }));
          return;
        }
        setState((previous) => ({
          ...previous,
          error,
          isRunning: false,
          finishedAt: Date.now(),
          status:
            previous.snapshot !== null && isTerminalStatus(previous.snapshot.status)
              ? previous.snapshot.status
              : previous.status,
        }));
      } finally {
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    },
    [applySnapshot, getClient, input, pollIntervalMs, timeoutMs],
  );

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    if (mountedRef.current) setState((previous) => ({ ...previous, isRunning: false }));
  }, []);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    autoStartKeyRef.current = null;
    if (mountedRef.current) setState(INITIAL_JOB_STATE);
  }, []);

  // Track mount state and abort in-flight polls on unmount. Re-entering the
  // effect body keeps this correct under React's StrictMode double invoke.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
    };
  }, []);

  const autoStart = options.autoStart === true;
  useEffect(() => {
    if (!autoStart) return;
    if (autoStartKeyRef.current === inputKey) return;
    autoStartKeyRef.current = inputKey;
    void run(undefined);
  }, [autoStart, inputKey, run]);

  return {
    status: state.status,
    jobId: state.jobId,
    snapshot: state.snapshot,
    progress: state.isRunning ? null : state.status === 'succeeded' ? 1 : null,
    messages: state.messages,
    result: state.result,
    error: state.error,
    isRunning: state.isRunning,
    startedAt: state.startedAt,
    finishedAt: state.finishedAt,
    start: run,
    cancel,
    reset,
  };
}

/* -------------------------------------------------------------------------- */
/* One-shot hooks                                                              */
/* -------------------------------------------------------------------------- */

/** What {@link useBookroomDescribe} returns. */
export interface UseBookroomDescribeResult {
  description: ServerDescription | null;
  loading: boolean;
  error: BookroomError | null;
  /** Run the call again. */
  reload: () => void;
}

/**
 * One `describe()` call on mount, with loading and error state.
 *
 * The description contains no secrets, which makes it safe to render directly.
 */
export function useBookroomDescribe(
  options: UseBookroomHookOptions = {},
): UseBookroomDescribeResult {
  const client = useResolvedClient(options);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    description: ServerDescription | null;
    loading: boolean;
    error: BookroomError | null;
  }>({ description: null, loading: true, error: null });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    client
      .describe({ signal: controller.signal })
      .then((description) => {
        if (active) setState({ description, loading: false, error: null });
      })
      .catch((raw: unknown) => {
        if (active) setState({ description: null, loading: false, error: toBookroomError(raw) });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [client, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  return { ...state, reload };
}

/** What {@link useBookroomHealth} returns. */
export interface UseBookroomHealthResult {
  report: HealthReport | null;
  loading: boolean;
  error: BookroomError | null;
  /** True when the server answered and reported both providers healthy. */
  ok: boolean;
  /** Run the check again. */
  reload: () => void;
}

/**
 * One `check()` call on mount, with loading and error state.
 *
 * `check()` probes both providers with a tiny synthetic request, so it is cheap,
 * but it is not free and the server serializes it behind its run lock. Call it
 * when a user asks about provider health, not on every render.
 */
export function useBookroomHealth(options: UseBookroomHookOptions = {}): UseBookroomHealthResult {
  const client = useResolvedClient(options);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    report: HealthReport | null;
    loading: boolean;
    error: BookroomError | null;
  }>({ report: null, loading: true, error: null });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    client
      .check({ signal: controller.signal })
      .then((report) => {
        if (active) setState({ report, loading: false, error: null });
      })
      .catch((raw: unknown) => {
        if (active) setState({ report: null, loading: false, error: toBookroomError(raw) });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [client, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  return { ...state, ok: state.report?.ok === true, reload };
}

/* -------------------------------------------------------------------------- */
/* StudyGuidePanel                                                             */
/* -------------------------------------------------------------------------- */

/** Props for {@link StudyGuidePanel}. */
export interface StudyGuidePanelProps extends Omit<UseBookroomJobOptions, 'path'> {
  /**
   * Book path, shown in the header and used when the panel starts its own job.
   *
   * Optional in controlled mode, where the caller already owns the job.
   */
  path?: string;
  /**
   * Render this hook result instead of creating one.
   *
   * Pass the result of your own `useBookroomJob` when you want the panel's markup
   * beside controls of your own. Without it, the panel manages its own job.
   *
   * ```tsx
   * const job = useBookroomJob({ path: 'book.epub' });
   * return <StudyGuidePanel job={job} path="book.epub" onStart={job.start} />;
   * ```
   */
  job?: UseBookroomJobResult;
  /**
   * Override what the start button does.
   *
   * Defaults to starting the panel's own job, or to the controlled `job`'s own
   * `start`.
   */
  onStart?: () => void;
  /** Heading text. */
  title?: string;
  /** Label for the start button. */
  startLabel?: string;
  /** Class name for the wrapper element, for your own stylesheet. */
  className?: string;
  /** Inline style for the wrapper element. */
  style?: CSSProperties;
  /**
   * Turn an artifact into a URL your browser can open.
   *
   * The facade serves JSON metadata but no file bytes, so a link is only
   * possible when your own server exposes the file. Returning `null` renders the
   * artifact's path as text instead.
   */
  artifactHref?: (artifact: Artifact, report: Report) => string | null;
  /** Called once when a run succeeds. */
  onSucceeded?: (report: Report) => void;
  /** Called once when a run fails. */
  onFailed?: (error: BookroomError) => void;
}

const PANEL_STYLE_ID = 'bookroom-study-guide-panel-styles';

const PANEL_CSS = `
@keyframes bookroomPanelSlide {
  0% { margin-left: -40%; }
  100% { margin-left: 100%; }
}
.bookroom-panel__bar--indeterminate > span {
  animation: bookroomPanelSlide 1.4s ease-in-out infinite;
}
.bookroom-panel__messages {
  scrollbar-width: thin;
}
`;

const panelStyles = {
  root: {
    fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    fontSize: 14,
    lineHeight: 1.5,
    color: '#0f172a',
    backgroundColor: '#ffffff',
    border: '1px solid #e2e8f0',
    borderRadius: 10,
    padding: 20,
    maxWidth: 760,
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  } satisfies CSSProperties,
  heading: { margin: 0, fontSize: 17, fontWeight: 650, letterSpacing: '-0.01em' } satisfies CSSProperties,
  meta: { margin: 0, color: '#475569', fontSize: 13 } satisfies CSSProperties,
  row: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } satisfies CSSProperties,
  button: {
    appearance: 'none',
    border: '1px solid #0f172a',
    backgroundColor: '#0f172a',
    color: '#ffffff',
    borderRadius: 7,
    padding: '7px 14px',
    fontSize: 13,
    fontWeight: 550,
    cursor: 'pointer',
  } satisfies CSSProperties,
  buttonSecondary: {
    appearance: 'none',
    border: '1px solid #cbd5e1',
    backgroundColor: '#ffffff',
    color: '#0f172a',
    borderRadius: 7,
    padding: '7px 14px',
    fontSize: 13,
    fontWeight: 550,
    cursor: 'pointer',
  } satisfies CSSProperties,
  buttonDisabled: { opacity: 0.55, cursor: 'default' } satisfies CSSProperties,
  status: { fontSize: 13, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 8 } satisfies CSSProperties,
  dot: (color: string) => ({ width: 8, height: 8, borderRadius: 4, backgroundColor: color, display: 'inline-block' }) satisfies CSSProperties,
  bar: {
    position: 'relative',
    height: 6,
    borderRadius: 3,
    backgroundColor: '#e2e8f0',
    overflow: 'hidden',
  } satisfies CSSProperties,
  barFill: (color: string) => ({
    height: '100%',
    borderRadius: 3,
    backgroundColor: color,
    transition: 'width 240ms ease-out',
  }) satisfies CSSProperties,
  messages: {
    margin: 0,
    padding: '10px 12px',
    listStyle: 'none',
    backgroundColor: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: 8,
    maxHeight: 168,
    overflowY: 'auto',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 12,
    color: '#334155',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  } satisfies CSSProperties,
  message: { whiteSpace: 'pre-wrap' } satisfies CSSProperties,
  error: {
    margin: 0,
    padding: '10px 12px',
    borderRadius: 8,
    border: '1px solid #fecaca',
    backgroundColor: '#fef2f2',
    color: '#991b1b',
    fontSize: 13,
  } satisfies CSSProperties,
  summary: {
    margin: 0,
    display: 'grid',
    gridTemplateColumns: 'minmax(120px, auto) 1fr',
    gap: '6px 16px',
    fontSize: 13,
  } satisfies CSSProperties,
  summaryLabel: { color: '#64748b' } satisfies CSSProperties,
  summaryValue: { margin: 0, fontWeight: 550, overflowWrap: 'anywhere' } satisfies CSSProperties,
  sectionTitle: { margin: '4px 0 0', fontSize: 13, fontWeight: 650, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b' } satisfies CSSProperties,
  artifacts: { margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 } satisfies CSSProperties,
  link: { color: '#1d4ed8', textDecoration: 'underline', overflowWrap: 'anywhere' } satisfies CSSProperties,
  code: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12, color: '#334155', overflowWrap: 'anywhere' } satisfies CSSProperties,
};

const STATUS_LABELS: Record<JobStatus | 'idle', string> = {
  idle: 'Not started',
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Complete',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

const STATUS_COLORS: Record<JobStatus | 'idle', string> = {
  idle: '#94a3b8',
  queued: '#b45309',
  running: '#1d4ed8',
  succeeded: '#15803d',
  failed: '#b91c1c',
  cancelled: '#64748b',
};

/** Format a duration in milliseconds as a compact human string. */
function formatDuration(ms: number | null): string | null {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return null;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
}

function formatCount(value: number | undefined): string | undefined {
  if (value === undefined) return undefined;
  return new Intl.NumberFormat('en-US').format(value);
}

/**
 * A minimal study-guide panel: start a job, watch it, read the report.
 *
 * It is written with inline styles and one injected stylesheet, so it needs no
 * CSS framework and no build-time plugin. Everything it shows comes from
 * {@link useBookroomJob}; pass that hook's options straight through.
 *
 * ```tsx
 * <StudyGuidePanel
 *   path="/books/attention.epub"
 *   pollIntervalMs={1500}
 *   artifactHref={(artifact) => `/api/artifacts/${encodeURIComponent(artifact.name)}`}
 * />
 * ```
 */
export function StudyGuidePanel(props: StudyGuidePanelProps): ReactNode {
  const {
    title = 'Study guide',
    startLabel = 'Generate study guide',
    className,
    style,
    artifactHref,
    onSucceeded,
    onFailed,
    job: controlledJob,
    onStart,
    path,
    ...hookOptions
  } = props;

  // The hook always runs, so hook order is stable; in controlled mode its result
  // is ignored. Its client is built lazily, so an unused hook never resolves one.
  const ownJob = useBookroomJob({ ...hookOptions, path: path ?? '' });
  const job = controlledJob ?? ownJob;
  const handleStart = onStart ?? (() => void job.start());
  const { result, error, status, messages, isRunning } = job;

  // The one injected rule this component needs: an indeterminate progress bar.
  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (document.getElementById(PANEL_STYLE_ID) !== null) return;
    const element = document.createElement('style');
    element.id = PANEL_STYLE_ID;
    element.textContent = PANEL_CSS;
    document.head.appendChild(element);
  }, []);

  useEffect(() => {
    if (result !== null) onSucceeded?.(result);
  }, [onSucceeded, result]);

  useEffect(() => {
    if (error !== null) onFailed?.(error);
  }, [error, onFailed]);

  const statusColor = STATUS_COLORS[status];
  const elapsed =
    job.startedAt !== null
      ? formatDuration((job.finishedAt ?? Date.now()) - job.startedAt)
      : null;
  const indeterminate = isRunning && job.progress === null;

  return (
    <section className={className} style={{ ...panelStyles.root, ...style }}>
      <header style={panelStyles.heading}>{title}</header>

      <p style={panelStyles.meta}>
        <code style={panelStyles.code}>{path ?? ''}</code>
      </p>

      <div style={panelStyles.row}>
        <button
          type="button"
          style={{ ...panelStyles.button, ...(isRunning ? panelStyles.buttonDisabled : {}) }}
          onClick={handleStart}
          disabled={isRunning || (controlledJob === undefined && path === undefined)}
        >
          {isRunning ? 'Generating…' : startLabel}
        </button>
        {isRunning ? (
          <button type="button" style={panelStyles.buttonSecondary} onClick={job.cancel}>
            Stop watching
          </button>
        ) : null}
        {status !== 'idle' ? (
          <button type="button" style={panelStyles.buttonSecondary} onClick={job.reset}>
            Reset
          </button>
        ) : null}

        <span style={panelStyles.status}>
          <span style={panelStyles.dot(statusColor)} />
          {STATUS_LABELS[status]}
          {job.jobId !== null ? <code style={panelStyles.code}>{job.jobId}</code> : null}
          {elapsed !== null ? <span style={{ color: '#64748b' }}>{elapsed}</span> : null}
        </span>
      </div>

      {isRunning ? (
        <div
          className={indeterminate ? 'bookroom-panel__bar--indeterminate' : undefined}
          style={panelStyles.bar}
        >
          <span
            style={
              indeterminate
                ? { ...panelStyles.barFill(statusColor), width: '40%' }
                : { ...panelStyles.barFill(statusColor), width: `${Math.round((job.progress ?? 0) * 100)}%` }
            }
          />
        </div>
      ) : null}

      {isRunning && job.progress === null ? (
        <p style={{ ...panelStyles.meta, margin: 0 }}>
          The server reports progress as messages, not a percentage.
        </p>
      ) : null}

      {messages.length > 0 ? (
        <ul className="bookroom-panel__messages" style={panelStyles.messages}>
          {messages.map((message, index) => (
            <li key={`${index}-${message.slice(0, 24)}`} style={panelStyles.message}>
              {message}
            </li>
          ))}
        </ul>
      ) : null}

      {error !== null ? (
        <p style={panelStyles.error}>
          <strong>{error.code}</strong> (HTTP {error.status}): {error.message}
          {error.retryAfterSeconds !== undefined ? ` Retry after ${error.retryAfterSeconds}s.` : ''}
        </p>
      ) : null}

      {result !== null ? (
        <>
          <h3 style={panelStyles.sectionTitle}>Report</h3>
          <dl style={panelStyles.summary}>
            <dt style={panelStyles.summaryLabel}>Title</dt>
            <dd style={panelStyles.summaryValue}>{result.document.title}</dd>

            <dt style={panelStyles.summaryLabel}>Format</dt>
            <dd style={panelStyles.summaryValue}>{result.document.kind}</dd>

            <dt style={panelStyles.summaryLabel}>Sections</dt>
            <dd style={panelStyles.summaryValue}>{formatCount(result.document.section_count)}</dd>

            <dt style={panelStyles.summaryLabel}>Words</dt>
            <dd style={panelStyles.summaryValue}>{formatCount(result.document.total_words)}</dd>

            <dt style={panelStyles.summaryLabel}>Output folder</dt>
            <dd style={panelStyles.summaryValue}>
              <code style={panelStyles.code}>{result.output_dir}</code>
            </dd>

            <dt style={panelStyles.summaryLabel}>Quality gate</dt>
            <dd style={panelStyles.summaryValue}>
              {result.quality === null
                ? 'Not run'
                : `${result.quality.categories_passed}/${result.quality.categories_reviewed} categories passed` +
                  (result.quality.all_passed ? '' : `, threshold ${result.quality.threshold}`)}
            </dd>
          </dl>

          <h3 style={panelStyles.sectionTitle}>Artifacts</h3>
          {result.artifacts.length === 0 ? (
            <p style={panelStyles.meta}>The run produced no artifacts.</p>
          ) : (
            <ul style={panelStyles.artifacts}>
              {result.artifacts.map((artifact) => {
                const href = artifactHref?.(artifact, result) ?? null;
                return (
                  <li key={artifact.name}>
                    {artifact.exists ? null : <span style={{ color: '#94a3b8' }}>missing · </span>}
                    {href !== null ? (
                      <a style={panelStyles.link} href={href} rel="noreferrer">
                        {artifact.name}
                      </a>
                    ) : (
                      <span>{artifact.name}</span>
                    )}{' '}
                    <span style={{ color: '#64748b' }}>
                      {artifact.media_type}
                      {artifact.path !== null ? ` · ${artifact.path}` : ''}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      ) : null}
    </section>
  );
}