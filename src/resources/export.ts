/**
 * Exports and packaging: Markdown, PDF, the concept graph, the claim audit, the
 * reproducible manifest, provider usage, and folder merging.
 */

import type { CallOptions, HttpTransport } from '../http.js';
import type {
  Artifact,
  ClaimAudit,
  ConceptMap,
  ProviderUsage,
  ReportManifest,
} from '../types.js';

/** Arguments for {@link ExportApi.pdf}. */
export interface PdfRequest {
  reportPath: string;
  /** Destination file; the server defaults to the report path with a `.pdf` suffix. */
  pdfPath?: string;
}

/** Arguments for {@link ExportApi.render}. */
export interface RenderRequest {
  title: string;
  /** Category key to section body, for the sections already generated. */
  sections: Record<string, string>;
  author?: string;
  sourceName?: string;
}

/** Arguments for {@link ExportApi.claimAudit}. */
export interface ClaimAuditRequest {
  reportPath: string;
  /** Chapter notes to audit against; the report's sibling file by default. */
  chapterNotes?: string;
  /** Lexical-overlap floor below which a claim is flagged. Defaults to 0.18. */
  minOverlap?: number;
}

/** Arguments for {@link ExportApi.manifest}. */
export interface ManifestRequest {
  reportPath: string;
  /** The original book, for its hash and provenance. */
  sourcePath: string;
}

/** Arguments for {@link ExportApi.merge}. */
export interface MergeRequest {
  folder: string;
  /** Output file; defaults to `book.md` on the server. */
  destination?: string;
}

/** Export calls. */
export class ExportApi {
  readonly #transport: HttpTransport;

  constructor(transport: HttpTransport) {
    this.#transport = transport;
  }

  /** `POST /v1/export/pdf` — render the study guide to a Unicode PDF. */
  async pdf(request: PdfRequest, options?: CallOptions): Promise<Artifact> {
    return this.#transport.request<Artifact>(
      {
        method: 'POST',
        path: '/v1/export/pdf',
        long: true,
        body: {
          report_path: request.reportPath,
          ...(request.pdfPath === undefined ? {} : { pdf_path: request.pdfPath }),
        },
      },
      options,
    );
  }

  /** `POST /v1/export/markdown` — read the canonical Markdown report as text. */
  async markdown(reportPath: string, options?: CallOptions): Promise<string> {
    const body = await this.#transport.request<{ markdown: string }>(
      { method: 'POST', path: '/v1/export/markdown', body: { report_path: reportPath } },
      options,
    );
    return body.markdown;
  }

  /**
   * `POST /v1/export/validate` — run the deterministic layout checks.
   *
   * An empty array means the Markdown is well formed.
   */
  async validate(markdown: string, options?: CallOptions): Promise<string[]> {
    const body = await this.#transport.request<{ problems: string[] }>(
      { method: 'POST', path: '/v1/export/validate', body: { markdown } },
      options,
    );
    return body.problems;
  }

  /** `POST /v1/export/render` — assemble a full report from finished sections. */
  async render(request: RenderRequest, options?: CallOptions): Promise<string> {
    const body = await this.#transport.request<{ markdown: string }>(
      {
        method: 'POST',
        path: '/v1/export/render',
        long: true,
        body: {
          title: request.title,
          sections: request.sections,
          ...(request.author === undefined ? {} : { author: request.author }),
          ...(request.sourceName === undefined ? {} : { source_name: request.sourceName }),
        },
      },
      options,
    );
    return body.markdown;
  }

  /** `POST /v1/export/concept-map` — the report's concept map as a portable graph. */
  async conceptMap(reportPath: string, options?: CallOptions): Promise<ConceptMap> {
    return this.#transport.request<ConceptMap>(
      { method: 'POST', path: '/v1/export/concept-map', body: { report_path: reportPath } },
      options,
    );
  }

  /**
   * `POST /v1/export/claim-audit` — lexical triage of the report's claims.
   *
   * This is a review aid, not semantic fact verification: a low-overlap claim is
   * flagged for a human and never auto-rejected.
   */
  async claimAudit(request: ClaimAuditRequest, options?: CallOptions): Promise<ClaimAudit> {
    return this.#transport.request<ClaimAudit>(
      {
        method: 'POST',
        path: '/v1/export/claim-audit',
        long: true,
        body: {
          report_path: request.reportPath,
          ...(request.chapterNotes === undefined ? {} : { chapter_notes: request.chapterNotes }),
          ...(request.minOverlap === undefined ? {} : { min_overlap: request.minOverlap }),
        },
      },
      options,
    );
  }

  /**
   * `POST /v1/export/manifest` — the reproducible, secret-free run manifest.
   *
   * Contains the source hash, the generation model, and the quality-gate
   * outcome, so a report can be traced back to the exact input and settings.
   */
  async manifest(request: ManifestRequest, options?: CallOptions): Promise<ReportManifest> {
    return this.#transport.request<ReportManifest>(
      {
        method: 'POST',
        path: '/v1/export/manifest',
        long: true,
        body: { report_path: request.reportPath, source_path: request.sourcePath },
      },
      options,
    );
  }

  /** `POST /v1/export/merge` — concatenate every `.md` file in a folder. */
  async merge(request: MergeRequest, options?: CallOptions): Promise<string> {
    const body = await this.#transport.request<{ path: string }>(
      {
        method: 'POST',
        path: '/v1/export/merge',
        body: {
          folder: request.folder,
          ...(request.destination === undefined ? {} : { destination: request.destination }),
        },
      },
      options,
    );
    return body.path;
  }

  /**
   * `GET /v1/usage` — token accounting.
   *
   * Pass `reportPath` to get the usage recorded for a specific run. Without it
   * the server returns its live in-process counter, which is **thread-local**:
   * a run executed on a background job thread will read as zero here, because
   * the request arrives on a different thread. For a number that belongs to a
   * particular run, always pass its report path.
   */
  async usage(reportPath?: string, options?: CallOptions): Promise<ProviderUsage> {
    return this.#transport.request<ProviderUsage>(
      {
        method: 'GET',
        path: '/v1/usage',
        // `exactOptionalPropertyTypes` forbids present-and-undefined, so the
        // key is only added when there is a report path to send.
        ...(reportPath === undefined ? {} : { query: { report_path: reportPath } }),
      },
      options,
    );
  }

  /** `GET /v1/artifacts` — every artifact that exists beside a study guide. */
  async artifacts(reportPath: string, options?: CallOptions): Promise<Artifact[]> {
    const body = await this.#transport.request<{ artifacts: Artifact[] }>(
      { method: 'GET', path: '/v1/artifacts', query: { report_path: reportPath } },
      options,
    );
    return body.artifacts;
  }
}
