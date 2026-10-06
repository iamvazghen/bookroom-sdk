/**
 * A tiny stand-in for the Bookroom facade, built on `node:http`.
 *
 * It speaks the same routes, status codes, and error envelope as the real
 * Python facade, so the client can be exercised end to end over real HTTP
 * without any provider credentials or book files.
 */

import http from 'node:http';

/** Token the mock demands, mirroring a token-protected facade. */
export const MOCK_TOKEN = 'facade-test-token';

const REPORT_PATH = '/output/attention/study-guide.md';

const CAPABILITIES = [
  'extract.extract',
  'extract.metadata',
  'extract.outline',
  'extract.ocr_languages',
  'summarize.preflight',
  'summarize.summarize_section',
  'summarize.summarize_text',
  'summarize.digest',
  'summarize.study_guide',
  'review.evaluate',
  'review.evaluate_section',
  'review.report_sections',
  'review.review_report',
  'review.evaluations',
  'export.pdf',
  'export.markdown',
  'export.validate',
  'export.render_report',
  'export.concept_map',
  'export.claim_audit',
  'export.manifest',
  'export.usage',
  'export.artifacts',
  'export.merge_markdown',
  'health.check',
  'translate.translate',
  'translate.translate_batch',
  'translate.classify_chapters',
  'translate.extract_notes',
];

const REPORT_SECTIONS = [
  ['one_sentence_summary', 'One-Sentence Summary'],
  ['chapter_summaries', 'Chapter Summaries'],
  ['argument_map', 'Argument Map'],
  ['key_concepts', 'Key Concepts'],
  ['concept_map', 'Concept Map'],
  ['worked_examples', 'Worked Examples'],
  ['common_misconceptions', 'Common Misconceptions'],
  ['evidence_and_citations', 'Evidence and Citations'],
  ['vocabulary', 'Vocabulary'],
  ['discussion_questions', 'Discussion Questions'],
  ['practice_problems', 'Practice Problems'],
  ['applications', 'Applications'],
  ['counterarguments', 'Counterarguments'],
  ['deep_dive', 'Deep Dive'],
  ['action_items', 'Action Items'],
  ['further_reading', 'Further Reading'],
];

/** The finished `POST /v1/study-guide` payload. */
export function reportFixture() {
  return {
    document: {
      path: '/books/attention.epub',
      kind: 'epub',
      title: 'Attention',
      section_count: 4,
      total_words: 1240,
      sections: [
        {
          title: 'Chapter 1',
          locator: 'p.1-12',
          word_count: 310,
          characters: 1980,
          ocr_used: false,
          ocr_confidence: null,
        },
      ],
    },
    output_dir: '/output/attention',
    report_path: REPORT_PATH,
    markdown: {
      name: 'study-guide.md',
      path: REPORT_PATH,
      media_type: 'text/markdown',
      exists: true,
    },
    pdf: {
      name: 'study-guide.pdf',
      path: '/output/attention/study-guide.pdf',
      media_type: 'application/pdf',
      exists: true,
    },
    chapter_notes: {
      name: 'chapter-notes.md',
      path: '/output/attention/chapter-notes.md',
      media_type: 'text/markdown',
      exists: true,
    },
    concept_map: {
      name: 'study-maps.json',
      path: '/output/attention/study-maps.json',
      media_type: 'application/json',
      exists: true,
    },
    claim_audit: null,
    manifest: {
      name: 'manifest.json',
      path: '/output/attention/manifest.json',
      media_type: 'application/json',
      exists: true,
    },
    usage: null,
    preflight: {
      section_count: 4,
      batch_count: 1,
      gemini_input_tokens_estimate: 4820,
      jev_credits_estimate_worst_case: 640,
      work_units: [{ section: 'Chapter 1' }],
      batches: [{ index: 1, sections: ['Chapter 1'] }],
    },
    evaluations: { report_section_count: 16, threshold: 3.5 },
    quality: {
      enabled: true,
      threshold: 3.5,
      max_revisions: 2,
      categories_reviewed: 16,
      categories_passed: 15,
      categories_below_threshold: 1,
      revision_truncation_fallbacks: 0,
      all_passed: false,
      scores: {
        one_sentence_summary: { faithfulness: 4.4, coverage: 4.1, clarity: 4.6 },
      },
      focus: {
        common_misconceptions: 'Add the second misconception explicitly.',
      },
    },
    artifacts: [
      { name: 'study-guide.md', path: REPORT_PATH, media_type: 'text/markdown', exists: true },
      {
        name: 'study-guide.pdf',
        path: '/output/attention/study-guide.pdf',
        media_type: 'application/pdf',
        exists: true,
      },
    ],
  };
}

function errorEnvelope(code, message, extra = {}) {
  return { error: { code, message, type: 'ValueError', ...extra } };
}

function jsonResponse(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (raw.trim() === '') {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (cause) {
        reject(cause);
      }
    });
    req.on('error', reject);
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Start the mock facade on an ephemeral port.
 *
 * Returns the base URL, the recorded requests, knobs for injecting transient
 * failures and delays, and a `close()` that releases the socket.
 */
export async function startMockFacade(options = {}) {
  const token = options.token === undefined ? MOCK_TOKEN : options.token;
  const pollsBeforeDone = options.pollsBeforeDone ?? 2;

  const state = {
    /** Every request the mock received, in order. */
    requests: [],
    /** Queue of one-shot failures; each entry may target a single path. */
    failures: [],
    /** `METHOD /path` to a response delay in milliseconds. */
    delays: new Map(),
    jobs: new Map(),
    polls: new Map(),
    pollsBeforeDone,
  };

  const server = http.createServer((req, res) => {
    handle(req, res).catch(() => {
      if (!res.headersSent) jsonResponse(res, 500, errorEnvelope('internal_error', 'mock failure'));
    });
  });

  async function handle(req, res) {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1');
    const path = url.pathname;
    const query = Object.fromEntries(url.searchParams.entries());
    let body = {};
    if (req.method === 'POST') {
      try {
        body = await readBody(req);
      } catch {
        jsonResponse(res, 400, errorEnvelope('invalid_request', 'Request body is not valid JSON'));
        return;
      }
    }

    state.requests.push({
      method: req.method,
      path,
      query,
      body,
      headers: { ...req.headers },
    });

    const headerToken = req.headers.authorization ?? '';
    const authorized =
      token === null || (headerToken.startsWith('Bearer ') && headerToken.slice(7).trim() === token);
    if (!authorized) {
      jsonResponse(res, 401, { error: { code: 'unauthorized', message: 'Invalid or missing facade token' } });
      return;
    }

    const key = `${req.method} ${path}`;
    const delayMs = state.delays.get(key);
    if (delayMs !== undefined) await sleep(delayMs);

    const injected = state.failures.findIndex(
      (failure) => failure.path === undefined || failure.path === path,
    );
    if (injected !== -1) {
      const [failure] = state.failures.splice(injected, 1);
      jsonResponse(res, failure.status, errorEnvelope(failure.code, failure.message, failure.extra ?? {}));
      return;
    }

    const result = route(req.method, path, query, body, state, pollsBeforeDone);
    jsonResponse(res, result.status, result.payload);
  }

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;

  return {
    baseUrl,
    server,
    state,
    /** Queue a one-shot failure, optionally limited to a single path. */
    failOnce(failure) {
      state.failures.push(failure);
    },
    /** Make a route respond slowly, to exercise timeouts and aborts. */
    delay(method, path, ms) {
      state.delays.set(`${method} ${path}`, ms);
    },
    /** How many times a path was requested. */
    countFor(method, path) {
      return state.requests.filter((request) => request.method === method && request.path === path).length;
    },
    async close() {
      server.closeAllConnections?.();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

function route(method, path, query, body, state, pollsBeforeDone) {
  const notFound = () => ({ status: 404, payload: { error: { code: 'not_found', message: `No route for ${method} ${path}` } } });

  /* --------------------------------------------------------------- GET routes */
  if (method === 'GET' && (path === '/' || path === '/healthz' || path === '/v1/healthz')) {
    return { status: 200, payload: { status: 'ok', sdk_version: '1.0.0' } };
  }
  if (method === 'GET' && path === '/v1/describe') {
    return {
      status: 200,
      payload: {
        sdk_version: '1.0.0',
        config: {
          llm_endpoint: 'https://mock-llm.invalid/v1beta',
          llm_model: 'gemini-3.8-flash',
          llm_api_key_set: true,
          jev_endpoint: 'https://mock-jev.invalid/v1',
          jev_model: 'jev-latest',
          jev_api_key_set: true,
          jev_enabled: true,
          output_dir: 'output',
          exports: { markdown: true, pdf: true },
        },
        capabilities: CAPABILITIES,
      },
    };
  }
  if (method === 'GET' && path === '/v1/capabilities') {
    return { status: 200, payload: { capabilities: CAPABILITIES } };
  }
  if (method === 'GET' && path === '/v1/check') {
    return {
      status: 200,
      payload: {
        ok: true,
        llm: { status: 'ok', model: 'gemini-3.8-flash', message: 'reachable' },
        review: { status: 'ok', model: 'jev-latest', message: 'reachable' },
        llm_provider: 'llm',
        review_provider: 'jev',
      },
    };
  }
  if (method === 'GET' && path === '/v1/sections') {
    return {
      status: 200,
      payload: {
        sections: REPORT_SECTIONS.map(([key, heading]) => ({ key, heading })),
      },
    };
  }
  if (method === 'GET' && path === '/v1/ocr-languages') {
    return { status: 200, payload: { languages: ['eng', 'fra', 'deu', 'spa'] } };
  }
  if (method === 'GET' && path === '/v1/usage') {
    return {
      status: 200,
      payload: {
        schema_version: '1.0',
        provider: 'Google Gemini API',
        model: 'gemini-3.8-flash',
        calls: 18,
        prompt_tokens: 4820,
        candidate_tokens: 6120,
        total_tokens: 10940,
      },
    };
  }
  if (method === 'GET' && path === '/v1/artifacts') {
    if (!query['report_path']) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'report_path is required') };
    }
    return {
      status: 200,
      payload: {
        artifacts: [
          { name: 'study-guide.md', path: REPORT_PATH, media_type: 'text/markdown', exists: true },
          { name: 'study-guide.pdf', path: '/output/attention/study-guide.pdf', media_type: 'application/pdf', exists: true },
        ],
      },
    };
  }
  if (method === 'GET' && path === '/v1/jobs') {
    return { status: 200, payload: { jobs: [...state.jobs.values()].map((job) => snapshot(job)) } };
  }
  if (method === 'GET' && path.startsWith('/v1/jobs/')) {
    const job = state.jobs.get(decodeURIComponent(path.slice('/v1/jobs/'.length)));
    if (job === undefined) {
      return { status: 404, payload: { error: { code: 'not_found', message: 'Unknown job id' } } };
    }
    const seen = (state.polls.get(job.id) ?? 0) + 1;
    state.polls.set(job.id, seen);
    job.status = seen > pollsBeforeDone ? 'succeeded' : 'running';
    job.messages.push(`progress ${seen}`);
    if (job.status === 'succeeded') {
      job.finished_at = '2026-01-01T00:00:10.000000+00:00';
      job.result = { report_path: REPORT_PATH, markdown: reportFixture().markdown };
    }
    return { status: 200, payload: snapshot(job, query['messages'] === '1') };
  }

  /* -------------------------------------------------------------- POST routes */
  if (method === 'POST' && path === '/v1/jobs') {
    const kind = body.kind ?? 'study-guide';
    if (kind !== 'study-guide' && kind !== 'review-report') {
      return { status: 400, payload: errorEnvelope('invalid_request', `Unknown job kind '${kind}'`) };
    }
    if (!body.path) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'Missing required field(s): path') };
    }
    const id = `job-${state.jobs.size + 1}`;
    state.jobs.set(id, {
      id,
      kind,
      status: 'queued',
      created_at: '2026-01-01T00:00:00.000000+00:00',
      finished_at: null,
      error: null,
      messages: [],
      result: null,
    });
    return { status: 200, payload: snapshot(state.jobs.get(id)) };
  }
  if (method === 'POST' && path === '/v1/extract') {
    if (missingFieldJson(body, 'path')) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'Missing required field(s): path') };
    }
    if (String(body.path).endsWith('.docx')) {
      return { status: 415, payload: errorEnvelope('unsupported_source', 'Only EPUB and PDF files are supported') };
    }
    const document = reportFixture().document;
    document.path = body.path;
    if (body.include_text === true) {
      document.sections = document.sections.map((section) => ({ ...section, text: 'Attention is scarce.' }));
    }
    return { status: 200, payload: document };
  }
  if (method === 'POST' && path === '/v1/metadata') {
    if (missingFieldJson(body, 'path')) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'Missing required field(s): path') };
    }
    return {
      status: 200,
      payload: {
        path: body.path,
        kind: 'pdf',
        name: 'attention.pdf',
        size_bytes: 20480,
        author: 'A. Reader',
        title: 'Attention',
        pages: 42,
      },
    };
  }
  if (method === 'POST' && path === '/v1/outline') {
    if (missingFieldJson(body, 'path')) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'Missing required field(s): path') };
    }
    return {
      status: 200,
      payload: { outline: [{ level: 1, title: 'Chapter 1', page: 1 }, { level: 2, title: 'Section 1.1', page: 3 }] },
    };
  }
  if (method === 'POST' && path === '/v1/preflight') {
    if (missingFieldJson(body, 'path')) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'Missing required field(s): path') };
    }
    return {
      status: 200,
      payload: {
        section_count: 4,
        batch_count: 1,
        gemini_input_tokens_estimate: 4820,
        jev_credits_estimate_worst_case: 640,
        work_units: [{ section: 'Chapter 1' }],
        batches: [{ index: 1 }],
      },
    };
  }
  if (method === 'POST' && path === '/v1/summarize-section') {
    if (missingFieldJson(body, 'title', 'source')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): title, source'),
      };
    }
    return { status: 200, payload: { notes: `Notes for ${body.title}` } };
  }
  if (method === 'POST' && path === '/v1/summarize-text') {
    if (missingFieldJson(body, 'text')) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'Missing required field(s): text') };
    }
    return { status: 200, payload: { notes: 'Notes for the supplied text.' } };
  }
  if (method === 'POST' && path === '/v1/digest') {
    if (missingFieldJson(body, 'title', 'chapter_notes')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): title, chapter_notes'),
      };
    }
    return { status: 200, payload: { digest: `Digest of ${body.title}` } };
  }
  if (method === 'POST' && path === '/v1/study-guide') {
    if (missingFieldJson(body, 'path')) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'Missing required field(s): path') };
    }
    const report = reportFixture();
    report.document.path = body.path;
    return { status: 200, payload: report };
  }
  if (method === 'POST' && path === '/v1/review/evaluate') {
    if (missingFieldJson(body, 'source_excerpt', 'summary')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): source_excerpt, summary'),
      };
    }
    return {
      status: 200,
      payload: {
        answers: { faithfulness: 4, coverage: 3, clarity: 5 },
        model: 'jev-latest',
        usage: { credits: 3 },
      },
    };
  }
  if (method === 'POST' && path === '/v1/review/section') {
    if (missingFieldJson(body, 'title', 'source', 'draft')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): title, source, draft'),
      };
    }
    return {
      status: 200,
      payload: {
        enabled: true,
        passed: true,
        scores: { faithfulness: 4.2, coverage: 4.0, clarity: 4.4 },
        confidence: { faithfulness: 0.8, coverage: 0.7, clarity: 0.9 },
        focus: null,
        model: 'jev-latest',
        usage: { credits: 5 },
      },
    };
  }
  if (method === 'POST' && path === '/v1/review/report') {
    if (missingFieldJson(body, 'report_path')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): report_path'),
      };
    }
    return {
      status: 200,
      payload: {
        records: REPORT_SECTIONS.map(([key, heading]) => ({
          section_key: key,
          section: heading,
          evidence_sha256: 'abc123',
          attempts: [{ attempt: 1, enabled: true, passed: true, scores: { faithfulness: 4 } }],
        })),
      },
    };
  }
  if (method === 'POST' && path === '/v1/review/evaluations') {
    if (missingFieldJson(body, 'report_path')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): report_path'),
      };
    }
    return { status: 200, payload: { evaluations: { report_section_count: 16, threshold: 3.5 } } };
  }
  if (method === 'POST' && path === '/v1/export/pdf') {
    if (missingFieldJson(body, 'report_path')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): report_path'),
      };
    }
    return {
      status: 200,
      payload: {
        name: 'study-guide.pdf',
        path: body.pdf_path ?? '/output/attention/study-guide.pdf',
        media_type: 'application/pdf',
        exists: true,
      },
    };
  }
  if (method === 'POST' && path === '/v1/export/markdown') {
    if (missingFieldJson(body, 'report_path')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): report_path'),
      };
    }
    return { status: 200, payload: { markdown: '# Attention\n\nBody text.\n' } };
  }
  if (method === 'POST' && path === '/v1/export/validate') {
    if (missingFieldJson(body, 'markdown')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): markdown'),
      };
    }
    return { status: 200, payload: { problems: [] } };
  }
  if (method === 'POST' && path === '/v1/export/render') {
    if (missingFieldJson(body, 'title', 'sections')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): title, sections'),
      };
    }
    return { status: 200, payload: { markdown: `# ${body.title}\n\nRendered.\n` } };
  }
  if (method === 'POST' && path === '/v1/export/concept-map') {
    if (missingFieldJson(body, 'report_path')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): report_path'),
      };
    }
    return {
      status: 200,
      payload: {
        schema_version: '1.0',
        nodes: [{ id: 'attention', label: 'Attention', depth: 0 }],
        edges: [{ source: 'attention', target: 'scarcity', relation: 'subconcept_of' }],
      },
    };
  }
  if (method === 'POST' && path === '/v1/export/claim-audit') {
    if (missingFieldJson(body, 'report_path')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): report_path'),
      };
    }
    return {
      status: 200,
      payload: {
        schema_version: '1.0',
        method: 'sentence-level lexical overlap against chapter notes; not semantic verification',
        claim_count: 1,
        source_section_count: 4,
        claims: [
          {
            section: 'One-Sentence Summary',
            claim: 'Attention is scarce.',
            status: 'source_overlap_found',
            lexical_overlap: 0.42,
            evidence_locator: 'p.1-12',
            evidence_section: 'Chapter 1',
            review_note: 'Lexical match is not proof of support; inspect source and claim.',
          },
        ],
      },
    };
  }
  if (method === 'POST' && path === '/v1/export/manifest') {
    if (missingFieldJson(body, 'report_path', 'source_path')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): report_path, source_path'),
      };
    }
    return {
      status: 200,
      payload: {
        schema_version: '1.0',
        source_file: 'attention.epub',
        source_sha256: 'deadbeef',
        generated_at_utc: '2026-01-01T00:00:00+00:00',
        generation_provider: 'Google Gemini API',
        generation_model: 'gemini-3.8-flash',
        jev_evaluation_enabled: true,
        report_section_categories_evaluated: 16,
        report_section_categories_passed: 15,
        report_section_categories_below_threshold: 1,
        quality_score_threshold: 3.5,
        quality_revision_limit: 2,
        evaluation_records: 16,
        ocr_sections: 0,
        mean_ocr_confidence: null,
        study_guide: 'study-guide.md',
        chapter_notes: 'chapter-notes.md',
        evaluations: 'evaluations.json',
      },
    };
  }
  if (method === 'POST' && path === '/v1/export/merge') {
    if (missingFieldJson(body, 'folder')) {
      return { status: 400, payload: errorEnvelope('invalid_request', 'Missing required field(s): folder') };
    }
    return { status: 200, payload: { path: body.destination ?? 'book.md' } };
  }
  if (method === 'POST' && path === '/v1/translate') {
    if (missingFieldJson(body, 'text', 'target_lang')) {
      return {
        status: 400,
        payload: errorEnvelope('invalid_request', 'Missing required field(s): text, target_lang'),
      };
    }
    return { status: 200, payload: { translation: `[${body.target_lang}] ${body.text}` } };
  }
  if (method === 'POST' && path === '/v1/translate/batch') {
    return { status: 200, payload: { translations: (body.texts ?? []).map((text) => `[es] ${text}`) } };
  }
  if (method === 'POST' && path === '/v1/translate/classify') {
    return { status: 200, payload: { relevant: (body.texts ?? []).slice(0, 1) } };
  }
  if (method === 'POST' && path === '/v1/translate/notes') {
    return { status: 200, payload: { notes: (body.texts ?? []).map((text) => `notes: ${text}`) } };
  }

  /* ------------------------------------------------------------- DELETE route */
  if (method === 'DELETE' && path.startsWith('/v1/jobs/')) {
    const id = decodeURIComponent(path.slice('/v1/jobs/'.length));
    const job = state.jobs.get(id);
    if (job === undefined) {
      return { status: 404, payload: { error: { code: 'not_found', message: 'Unknown job id' } } };
    }
    if (job.status === 'queued' || job.status === 'running') {
      return { status: 409, payload: { error: { code: 'conflict', message: 'A running job cannot be removed' } } };
    }
    state.jobs.delete(id);
    return { status: 200, payload: { deleted: id } };
  }

  return notFound();
}

/** True when the request body lacks a required field. */
function missingFieldJson(body, ...fields) {
  return fields.some((field) => !body[field]);
}

function snapshot(job, includeMessages = false) {
  const data = {
    id: job.id,
    kind: job.kind,
    status: job.status,
    created_at: job.created_at,
    finished_at: job.finished_at,
    error: job.error,
    message_count: job.messages.length,
  };
  if (includeMessages) data.messages = [...job.messages];
  if (job.status === 'succeeded') data.result = job.result;
  return data;
}
