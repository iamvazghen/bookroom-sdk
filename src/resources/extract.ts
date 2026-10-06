/**
 * Extraction: sections, locators, document metadata, and the table of contents.
 */

import type { CallOptions, HttpTransport } from '../http.js';
import type { SummarizeOptions } from '../types.js';
import type { Document, FileMetadata, OutlineEntry } from '../types.js';

/** Arguments for {@link ExtractApi.extract}. */
export interface ExtractRequest {
  /** Absolute path, on the *server's* filesystem, to a `.pdf` or `.epub`. */
  path: string;
  /** Reader-facing preferences; OCR for scanned PDFs is enabled here. */
  options?: SummarizeOptions;
  /** Return the full text of every section. Large; off by default. */
  includeText?: boolean;
}

/** Extraction calls. */
export class ExtractApi {
  readonly #transport: HttpTransport;

  constructor(transport: HttpTransport) {
    this.#transport = transport;
  }

  /**
   * `POST /v1/extract` — read a book into titled sections with locators.
   *
   * Without `includeText` the response carries counts only, which is what a
   * caller normally wants; the text is omitted because a whole book is large.
   */
  async extract(request: ExtractRequest, options?: CallOptions): Promise<Document> {
    return this.#transport.request<Document>(
      {
        method: 'POST',
        path: '/v1/extract',
        long: true,
        body: {
          path: request.path,
          ...(request.options ? { options: request.options } : {}),
          ...(request.includeText === undefined ? {} : { include_text: request.includeText }),
        },
      },
      options,
    );
  }

  /** `POST /v1/metadata` — file size, title, and author, without reading the book. */
  async metadata(path: string, options?: CallOptions): Promise<FileMetadata> {
    return this.#transport.request<FileMetadata>(
      { method: 'POST', path: '/v1/metadata', body: { path } },
      options,
    );
  }

  /** `POST /v1/outline` — the table of contents, when the source has one. */
  async outline(path: string, options?: CallOptions): Promise<OutlineEntry[]> {
    const body = await this.#transport.request<{ outline: OutlineEntry[] }>(
      { method: 'POST', path: '/v1/outline', body: { path } },
      options,
    );
    return body.outline;
  }
}
