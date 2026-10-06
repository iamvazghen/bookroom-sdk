/**
 * Translation and chapter triage, on the server's alternate LLM transport.
 *
 * These calls run on the legacy OpenAI-compatible path (Ollama or a similar
 * endpoint) rather than the main generation path, which is why they are
 * separate from the summarization namespace.
 */

import type { CallOptions, HttpTransport } from '../http.js';
import type {
  BatchTranslationResponse,
  ClassifyResponse,
  NotesBatchResponse,
  TranslationResponse,
} from '../types.js';

/** Arguments for {@link TranslateApi.translate}. */
export interface TranslateRequest {
  text: string;
  /** Target language tag or name, for example `Spanish`. */
  targetLang: string;
}

/** Arguments for {@link TranslateApi.translateBatch}. */
export interface TranslateBatchRequest {
  texts: string[];
  targetLang: string;
}

/** Translation and triage calls. */
export class TranslateApi {
  readonly #transport: HttpTransport;

  constructor(transport: HttpTransport) {
    this.#transport = transport;
  }

  /** `POST /v1/translate` — translate one text. */
  async translate(request: TranslateRequest, options?: CallOptions): Promise<string> {
    const body = await this.#transport.request<TranslationResponse>(
      {
        method: 'POST',
        path: '/v1/translate',
        long: true,
        body: { text: request.text, target_lang: request.targetLang },
      },
      options,
    );
    return body.translation;
  }

  /** `POST /v1/translate/batch` — translate many texts. */
  async translateBatch(request: TranslateBatchRequest, options?: CallOptions): Promise<string[]> {
    const body = await this.#transport.request<BatchTranslationResponse>(
      {
        method: 'POST',
        path: '/v1/translate/batch',
        long: true,
        body: { texts: request.texts, target_lang: request.targetLang },
      },
      options,
    );
    return body.translations;
  }

  /** `POST /v1/translate/classify` — keep only the chapters worth summarizing. */
  async classify(texts: string[], options?: CallOptions): Promise<string[]> {
    const body = await this.#transport.request<ClassifyResponse>(
      { method: 'POST', path: '/v1/translate/classify', long: true, body: { texts } },
      options,
    );
    return body.relevant;
  }

  /** `POST /v1/translate/notes` — multi-node notes: summary, lessons, quotes, and more. */
  async notes(texts: string[], options?: CallOptions): Promise<string[]> {
    const body = await this.#transport.request<NotesBatchResponse>(
      { method: 'POST', path: '/v1/translate/notes', long: true, body: { texts } },
      options,
    );
    return body.notes;
  }
}
