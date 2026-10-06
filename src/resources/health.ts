/**
 * Health and discovery: reachability, provider checks, capabilities, the report
 * category list, and the available OCR languages.
 */

import type { CallOptions, HttpTransport } from '../http.js';
import type {
  CapabilitiesResponse,
  HealthReport,
  OcrLanguagesResponse,
  ReportSection,
  SectionsResponse,
  ServerDescription,
  ServerHealth,
} from '../types.js';

/** Health and discovery calls. */
export class HealthApi {
  readonly #transport: HttpTransport;

  constructor(transport: HttpTransport) {
    this.#transport = transport;
  }

  /** `GET /healthz` — is the process up, and which SDK is behind it. */
  async ping(options?: CallOptions): Promise<ServerHealth> {
    return this.#transport.request<ServerHealth>({ method: 'GET', path: '/healthz' }, options);
  }

  /**
   * `GET /v1/check` — probe both providers before spending anything.
   *
   * Sends a minimal synthetic request, never book content, so it is cheap and
   * safe to call at start-up. It catches an invalid key or an unreachable model
   * before a paid run begins.
   */
  async check(options?: CallOptions): Promise<HealthReport> {
    return this.#transport.request<HealthReport>({ method: 'GET', path: '/v1/check' }, options);
  }

  /**
   * `GET /v1/describe` — the server's active configuration and capabilities.
   *
   * The config report contains no secrets: keys are reduced to `*_api_key_set`
   * booleans, so this is safe to log.
   */
  async describe(options?: CallOptions): Promise<ServerDescription> {
    return this.#transport.request<ServerDescription>(
      { method: 'GET', path: '/v1/describe' },
      options,
    );
  }

  /** `GET /v1/capabilities` — the capability names the server advertises. */
  async capabilities(options?: CallOptions): Promise<string[]> {
    const body = await this.#transport.request<CapabilitiesResponse>(
      { method: 'GET', path: '/v1/capabilities' },
      options,
    );
    return body.capabilities;
  }

  /** `GET /v1/sections` — the canonical report categories, in order. */
  async sections(options?: CallOptions): Promise<ReportSection[]> {
    const body = await this.#transport.request<SectionsResponse>(
      { method: 'GET', path: '/v1/sections' },
      options,
    );
    return body.sections;
  }

  /** `GET /v1/ocr-languages` — language codes available for scanned PDFs. */
  async ocrLanguages(options?: CallOptions): Promise<string[]> {
    const body = await this.#transport.request<OcrLanguagesResponse>(
      { method: 'GET', path: '/v1/ocr-languages' },
      options,
    );
    return body.languages;
  }
}
