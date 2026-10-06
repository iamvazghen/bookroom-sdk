/**
 * Typed result shapes for every Bookroom facade response.
 *
 * These mirror the JSON the facade returns one-for-one; the SDK performs no
 * hidden transformation, so a value you read here is exactly what the server
 * produced.
 */

/* -------------------------------------------------------------------------- */
/* Errors                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Error codes the facade itself emits.
 *
 * The wire type also admits unknown strings, so a newer server can add a code
 * without breaking a compiled client.
 */
export type KnownErrorCode =
  | 'invalid_request'
  | 'configuration_error'
  | 'unsupported_source'
  | 'extraction_failed'
  | 'budget_exceeded'
  | 'quota_exceeded'
  | 'provider_error'
  | 'cancelled'
  | 'application_load_failed'
  | 'sdk_error'
  | 'internal_error'
  | 'not_found'
  | 'unauthorized'
  | 'conflict';

/** A facade error code, including any code a future server may add. */
export type FacadeErrorCode = KnownErrorCode | (string & {});

/**
 * The `error` object inside a non-2xx facade response.
 *
 * `type` and `trace` are only present on some codes, and `retry_after_seconds`
 * only when the server knows when to try again.
 */
export interface FacadeErrorBody {
  code?: FacadeErrorCode;
  message?: string;
  type?: string;
  trace?: string;
  retry_after_seconds?: number;
}

/** Envelope used by every failing facade response. */
export interface FacadeErrorEnvelope {
  error?: FacadeErrorBody;
}

/* -------------------------------------------------------------------------- */
/* Health and discovery                                                        */
/* -------------------------------------------------------------------------- */

/** `GET /healthz` */
export interface ServerHealth {
  status: string;
  sdk_version: string;
}

/**
 * The server's own configuration report, as returned by `GET /v1/describe`.
 *
 * It contains no secrets: the API keys are reduced to `*_api_key_set` flags.
 * Extra keys are allowed so a newer server stays assignable.
 */
export interface FacadeConfig {
  llm_endpoint?: string;
  llm_model?: string;
  llm_api_key_set?: boolean;
  jev_endpoint?: string;
  jev_model?: string;
  jev_api_key_set?: boolean;
  jev_enabled?: boolean;
  jev_score_threshold?: number;
  jev_confidence_threshold?: number;
  jev_max_revisions?: number;
  thinking_level?: string;
  legacy_llm_endpoint?: string;
  legacy_llm_model?: string | null;
  legacy_concurrency?: number;
  max_actual_llm_tokens?: number;
  max_estimated_llm_input_tokens?: number;
  max_estimated_jev_credits?: number;
  min_word_count?: number;
  ocr_enabled?: boolean;
  ocr_language?: string;
  output_dir?: string;
  app_root?: string;
  exports?: Record<string, boolean>;
  [key: string]: unknown;
}

/** `GET /v1/describe` */
export interface ServerDescription {
  sdk_version: string;
  config: FacadeConfig;
  capabilities: string[];
}

/** `GET /v1/capabilities` */
export interface CapabilitiesResponse {
  capabilities: string[];
}

/** One provider's leg of `GET /v1/check`. */
export interface ProviderStatus {
  status?: string;
  model?: string;
  message?: string;
  [key: string]: unknown;
}

/**
 * `GET /v1/check`.
 *
 * Probes both providers with a minimal synthetic request; no book content is
 * sent, so this is cheap and safe to call before a paid run.
 */
export interface HealthReport {
  ok: boolean;
  llm: ProviderStatus;
  review: ProviderStatus;
  llm_provider?: string;
  review_provider?: string;
}

/** `GET /v1/sections` */
export interface ReportSection {
  key: string;
  heading: string;
}

/** `GET /v1/sections` */
export interface SectionsResponse {
  sections: ReportSection[];
}

/** `GET /v1/ocr-languages` */
export interface OcrLanguagesResponse {
  languages: string[];
}

/** `GET /v1/usage` */
export interface ProviderUsage {
  schema_version?: string;
  provider: string;
  model: string;
  calls: number;
  prompt_tokens: number;
  candidate_tokens: number;
  total_tokens: number;
}

/* -------------------------------------------------------------------------- */
/* Extraction                                                                  */
/* -------------------------------------------------------------------------- */

/** Source formats the engine can read. */
export type DocumentKind = 'pdf' | 'epub';

/** Reader-facing preferences forwarded to the server's prompt builder. */
export interface SummarizeOptions {
  language?: string;
  reading_level?: string;
  /** `brief` | `standard` | `deep` */
  digest_length?: string;
  /** `auto` or a specific book genre */
  book_type?: string;
  ocr_enabled?: boolean;
  /** Tesseract language code, for example `eng`. */
  ocr_language?: string;
}

/** One extracted unit of a book. */
export interface DocumentSection {
  title: string;
  /** Where the section came from: a page label or an EPUB spine position. */
  locator: string;
  word_count: number;
  characters: number;
  ocr_used: boolean;
  ocr_confidence: number | null;
  /** Present only when the request asked for `include_text`. */
  text?: string;
}

/** `POST /v1/extract` */
export interface Document {
  path: string;
  kind: DocumentKind | string;
  title: string;
  section_count: number;
  total_words: number;
  sections: DocumentSection[];
}

/** `POST /v1/metadata` */
export interface FileMetadata {
  path: string;
  kind: string;
  name: string;
  size_bytes: number;
  author: string | null;
  title: string;
  /** PDF page count; absent for EPUB. */
  pages?: number;
}

/** One table-of-contents entry from `POST /v1/outline`. */
export interface OutlineEntry {
  level: number;
  title: string;
  page: number | null;
}

/** `POST /v1/outline` */
export interface OutlineResponse {
  outline: OutlineEntry[];
}

/* -------------------------------------------------------------------------- */
/* Summarization                                                               */
/* -------------------------------------------------------------------------- */

/**
 * `POST /v1/preflight`.
 *
 * The server's own cost estimate and work-batch plan. Known keys are typed;
 * the server may add more.
 */
export interface Preflight {
  section_count: number;
  batch_count: number;
  gemini_input_tokens_estimate: number;
  jev_credits_estimate_worst_case: number;
  work_units?: unknown[];
  batches?: unknown[];
  [key: string]: unknown;
}

/** `POST /v1/summarize-section` and `POST /v1/summarize-text` */
export interface NotesResult {
  notes: string;
}

/** `POST /v1/digest` */
export interface DigestResult {
  digest: string;
}

/* -------------------------------------------------------------------------- */
/* Reports and artifacts                                                       */
/* -------------------------------------------------------------------------- */

/** A file produced by a run. `path` is null when the artifact is absent. */
export interface Artifact {
  name: string;
  path: string | null;
  media_type: string;
  exists: boolean;
}

/** `GET /v1/artifacts` */
export interface ArtifactsResponse {
  artifacts: Artifact[];
}

/** Aggregate JEv outcome for a run; null when review was not enabled. */
export interface QualitySummary {
  enabled: boolean;
  threshold: number;
  max_revisions: number;
  categories_reviewed: number;
  categories_passed: number;
  categories_below_threshold: number;
  revision_truncation_fallbacks: number;
  all_passed: boolean;
  /** Category key to per-dimension score, for example `faithfulness`. */
  scores: Record<string, Record<string, number>>;
  /** Category key to the reviewer's focus note for a failing category. */
  focus: Record<string, string>;
}

/** The full `POST /v1/study-guide` result. */
export interface Report {
  document: Document;
  output_dir: string;
  report_path: string | null;
  markdown: Artifact;
  pdf: Artifact | null;
  chapter_notes: Artifact | null;
  concept_map: Artifact | null;
  claim_audit: Artifact | null;
  manifest: Artifact | null;
  usage: Artifact | null;
  preflight: Preflight | null;
  evaluations: Record<string, unknown>;
  quality: QualitySummary | null;
  artifacts: Artifact[];
}

/* -------------------------------------------------------------------------- */
/* Review                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * `POST /v1/review/evaluate`.
 *
 * The raw JEv decision payload. Its scores are advisory signals about
 * faithfulness, coverage, and clarity, not proof that a summary is correct.
 */
export interface EvaluateResponse {
  answers: Record<string, unknown>;
  model?: string;
  usage?: Record<string, unknown>;
  [key: string]: unknown;
}

/** One attempt recorded by the quality gate. */
export interface ReviewAttempt {
  attempt?: number;
  enabled: boolean;
  passed: boolean | null;
  scores?: Record<string, number>;
  confidence?: Record<string, number>;
  focus?: string | null;
  jev_focus?: string | null;
  usage?: Record<string, unknown>;
  evaluation_scope?: string;
  source_parts_reviewed?: number;
  /** Set when a section was too large to revise in one pass. */
  revision_skipped?: string | null;
  [key: string]: unknown;
}

/** One reviewed report category from `POST /v1/review/report`. */
export interface ReviewRecord {
  section_key: string;
  section: string;
  evidence_sha256: string;
  attempts: ReviewAttempt[];
}

/** `POST /v1/review/report` */
export interface ReviewReportResponse {
  records: ReviewRecord[];
}

/** `POST /v1/review/evaluations` */
export interface EvaluationsResponse {
  evaluations: Record<string, unknown>;
}

/** `POST /v1/review/section` */
export interface SectionReview {
  enabled: boolean;
  passed: boolean | null;
  scores: Record<string, number>;
  confidence: Record<string, number>;
  focus: string | null;
  model: string | null;
  usage: Record<string, unknown>;
}

/* -------------------------------------------------------------------------- */
/* Exports                                                                     */
/* -------------------------------------------------------------------------- */

/** `POST /v1/export/render` and `POST /v1/export/markdown` */
export interface MarkdownResponse {
  markdown: string;
}

/** `POST /v1/export/validate` */
export interface ValidationResponse {
  problems: string[];
}

/** One node of the concept graph. */
export interface ConceptNode {
  id: string;
  label: string;
  depth: number;
}

/** One edge of the concept graph. */
export interface ConceptEdge {
  source: string;
  target: string;
  /** `organizes`, `subconcept_of`, or a column relation. */
  relation: string;
}

/** `POST /v1/export/concept-map` */
export interface ConceptMap {
  schema_version: string;
  nodes: ConceptNode[];
  edges: ConceptEdge[];
}

/** How one sentence of the report fared against the chapter notes. */
export interface ClaimAuditEntry {
  section: string;
  claim: string;
  /** `source_overlap_found` | `explicit_inference` | `low_overlap_review` */
  status: string;
  lexical_overlap: number;
  evidence_locator: string | null;
  evidence_section: string | null;
  review_note: string;
}

/**
 * `POST /v1/export/claim-audit`.
 *
 * Lexical triage, not semantic verification: a low-overlap claim is flagged
 * for a human, never auto-rejected.
 */
export interface ClaimAudit {
  schema_version: string;
  method: string;
  claim_count: number;
  source_section_count: number;
  claims: ClaimAuditEntry[];
}

/** `POST /v1/export/manifest` */
export interface ReportManifest {
  schema_version: string;
  source_file: string;
  source_sha256: string;
  generated_at_utc: string;
  generation_provider: string;
  generation_model: string;
  jev_evaluation_enabled: boolean;
  report_section_categories_evaluated: number;
  report_section_categories_passed: number;
  report_section_categories_below_threshold: number;
  quality_score_threshold: number | null;
  quality_revision_limit: number | null;
  evaluation_records: number;
  ocr_sections: number;
  mean_ocr_confidence: number | null;
  study_guide: string;
  chapter_notes: string;
  evaluations: string;
  [key: string]: unknown;
}

/** `POST /v1/export/merge` */
export interface MergeResult {
  path: string;
}

/* -------------------------------------------------------------------------- */
/* Translation                                                                 */
/* -------------------------------------------------------------------------- */

/** `POST /v1/translate` */
export interface TranslationResponse {
  translation: string;
}

/** `POST /v1/translate/batch` */
export interface BatchTranslationResponse {
  translations: string[];
}

/** `POST /v1/translate/classify` */
export interface ClassifyResponse {
  relevant: string[];
}

/** `POST /v1/translate/notes` */
export interface NotesBatchResponse {
  notes: string[];
}

/* -------------------------------------------------------------------------- */
/* Jobs                                                                        */
/* -------------------------------------------------------------------------- */

/** The two long-running job kinds the facade can start. */
export type JobKind = 'study-guide' | 'review-report';

/** Lifecycle of a background job. */
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

/** A job is finished once it reaches any of these states. */
export type TerminalJobStatus = Extract<JobStatus, 'succeeded' | 'failed' | 'cancelled'>;

/** `GET /v1/jobs`, `GET /v1/jobs/{id}`, and `POST /v1/jobs`. */
export interface JobSnapshot {
  id: string;
  kind: JobKind | string;
  status: JobStatus;
  created_at: string;
  finished_at: string | null;
  /** Failure text when `status` is `failed`. */
  error: string | null;
  message_count: number;
  /** Progress messages, only present when polling with `messages: true`. */
  messages?: string[];
  /** The finished `Report` (or `{records}`) when `status` is `succeeded`. */
  result?: unknown;
}

/** `GET /v1/jobs` */
export interface JobsResponse {
  jobs: JobSnapshot[];
}

/** `DELETE /v1/jobs/{id}` */
export interface DeleteJobResponse {
  deleted: string;
}
