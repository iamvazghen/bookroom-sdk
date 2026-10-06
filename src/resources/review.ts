/**
 * JEv review: independent scoring, the 16-category quality gate, and the stored
 * evaluation history.
 *
 * JEv is a decision model, not a generator. Its scores are advisory signals
 * about faithfulness, coverage, clarity, and structure — not proof that a
 * summary is correct.
 */

import type { CallOptions, HttpTransport } from '../http.js';
import type { EvaluateResponse, ReviewRecord, SectionReview } from '../types.js';

/** Arguments for {@link ReviewApi.evaluate}. */
export interface EvaluateRequest {
  /** A bounded excerpt of the source. Keep it small; do not send a whole book. */
  sourceExcerpt: string;
  summary: string;
}

/** Arguments for {@link ReviewApi.evaluateSection}. */
export interface EvaluateSectionRequest {
  title: string;
  /** The evidence the draft is judged against. */
  source: string;
  draft: string;
}

/** Review calls. */
export class ReviewApi {
  readonly #transport: HttpTransport;

  constructor(transport: HttpTransport) {
    this.#transport = transport;
  }

  /**
   * `POST /v1/review/evaluate` — score one summary against one excerpt.
   *
   * Returns JEv's raw typed response.
   */
  async evaluate(request: EvaluateRequest, options?: CallOptions): Promise<EvaluateResponse> {
    return this.#transport.request<EvaluateResponse>(
      {
        method: 'POST',
        path: '/v1/review/evaluate',
        long: true,
        body: { source_excerpt: request.sourceExcerpt, summary: request.summary },
      },
      options,
    );
  }

  /**
   * `POST /v1/review/section` — score one candidate section on the
   * four-dimension production rubric.
   */
  async evaluateSection(
    request: EvaluateSectionRequest,
    options?: CallOptions,
  ): Promise<SectionReview> {
    return this.#transport.request<SectionReview>(
      {
        method: 'POST',
        path: '/v1/review/section',
        long: true,
        body: { title: request.title, source: request.source, draft: request.draft },
      },
      options,
    );
  }

  /**
   * `POST /v1/review/report` — evaluate and revise all 16 report categories.
   *
   * Runs in place on the server: it rewrites `study-guide.md` beside
   * `chapter-notes.md` and `evaluations.json`. A category that stays below
   * threshold after its revision budget is kept with its history rather than
   * hidden, so a low score is visible rather than lost.
   */
  async report(reportPath: string, options?: CallOptions): Promise<ReviewRecord[]> {
    const body = await this.#transport.request<{ records: ReviewRecord[] }>(
      { method: 'POST', path: '/v1/review/report', long: true, body: { report_path: reportPath } },
      options,
    );
    return body.records;
  }

  /** `POST /v1/review/evaluations` — the stored history for a report. */
  async evaluations(
    reportPath: string,
    options?: CallOptions,
  ): Promise<Record<string, unknown>> {
    const body = await this.#transport.request<{ evaluations: Record<string, unknown> }>(
      { method: 'POST', path: '/v1/review/evaluations', body: { report_path: reportPath } },
      options,
    );
    return body.evaluations;
  }
}
