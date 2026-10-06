/**
 * Summarization: preflight estimates, section and text notes, digests, and the
 * complete study guide.
 */

import type { CallOptions, HttpTransport } from '../http.js';
import type {
  DigestResult,
  NotesResult,
  Preflight,
  Report,
  SummarizeOptions,
} from '../types.js';

/** Arguments for {@link SummarizeApi.preflight}. */
export interface PreflightRequest {
  path: string;
  options?: SummarizeOptions;
}

/** Arguments for {@link SummarizeApi.summarizeSection}. */
export interface SummarizeSectionRequest {
  title: string;
  /** The section's source text. */
  source: string;
  locator?: string;
  options?: SummarizeOptions;
}

/** Arguments for {@link SummarizeApi.summarizeText}. */
export interface SummarizeTextRequest {
  text: string;
  title?: string;
  options?: SummarizeOptions;
}

/** Arguments for {@link SummarizeApi.digest}. */
export interface DigestRequest {
  title: string;
  /** Existing chapter notes, or any body of notes, as one string. */
  chapterNotes: string;
  options?: SummarizeOptions;
}

/** Arguments for {@link SummarizeApi.studyGuide}. */
export interface StudyGuideRequest {
  path: string;
  options?: SummarizeOptions;
  /** Output folder name; the server picks one when omitted. */
  outputSlug?: string;
  /** JEv quality gate switch; the server decides when omitted. */
  review?: boolean;
}

/** Summarization calls. */
export class SummarizeApi {
  readonly #transport: HttpTransport;

  constructor(transport: HttpTransport) {
    this.#transport = transport;
  }

  /**
   * `POST /v1/preflight` — estimate spend before spending it.
   *
   * The server enforces its own budget caps here, so an over-budget book fails
   * in this call rather than partway through a paid run.
   */
  async preflight(request: PreflightRequest, options?: CallOptions): Promise<Preflight> {
    return this.#transport.request<Preflight>(
      {
        method: 'POST',
        path: '/v1/preflight',
        long: true,
        body: {
          path: request.path,
          ...(request.options ? { options: request.options } : {}),
        },
      },
      options,
    );
  }

  /** `POST /v1/summarize-section` — notes for one already-extracted section. */
  async summarizeSection(request: SummarizeSectionRequest, options?: CallOptions): Promise<string> {
    const body = await this.#transport.request<NotesResult>(
      {
        method: 'POST',
        path: '/v1/summarize-section',
        long: true,
        body: {
          title: request.title,
          source: request.source,
          ...(request.locator === undefined ? {} : { locator: request.locator }),
          ...(request.options ? { options: request.options } : {}),
        },
      },
      options,
    );
    return body.notes;
  }

  /** `POST /v1/summarize-text` — notes for raw text, with no source file. */
  async summarizeText(request: SummarizeTextRequest, options?: CallOptions): Promise<string> {
    const body = await this.#transport.request<NotesResult>(
      {
        method: 'POST',
        path: '/v1/summarize-text',
        long: true,
        body: {
          text: request.text,
          ...(request.title === undefined ? {} : { title: request.title }),
          ...(request.options ? { options: request.options } : {}),
        },
      },
      options,
    );
    return body.notes;
  }

  /**
   * `POST /v1/digest` — a digest body from notes that already exist.
   *
   * Nothing is re-summarized, so this is far cheaper than a full run.
   */
  async digest(request: DigestRequest, options?: CallOptions): Promise<string> {
    const body = await this.#transport.request<DigestResult>(
      {
        method: 'POST',
        path: '/v1/digest',
        long: true,
        body: {
          title: request.title,
          chapter_notes: request.chapterNotes,
          ...(request.options ? { options: request.options } : {}),
        },
      },
      options,
    );
    return body.digest;
  }

  /**
   * `POST /v1/study-guide` — the whole pipeline, synchronously.
   *
   * This is the expensive call: extraction, per-section notes, a digest, report
   * rendering, exports, and the optional 16-category JEv quality gate. Budget
   * minutes for it, which is why the default timeout is generous. Use
   * {@link JobsApi.create} instead when the caller cannot block for that long.
   */
  async studyGuide(request: StudyGuideRequest, options?: CallOptions): Promise<Report> {
    return this.#transport.request<Report>(
      {
        method: 'POST',
        path: '/v1/study-guide',
        long: true,
        body: {
          path: request.path,
          ...(request.options ? { options: request.options } : {}),
          ...(request.outputSlug === undefined ? {} : { output_slug: request.outputSlug }),
          ...(request.review === undefined ? {} : { review: request.review }),
        },
      },
      options,
    );
  }
}
