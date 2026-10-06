/**
 * End-to-end tests for the client against a mock facade.
 *
 * These run over real HTTP against a `node:http` server, so request building,
 * auth headers, retries, error mapping, and job polling are all exercised the
 * way a real caller would hit them.
 */

import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';

import {
  Bookroom,
  BookroomError,
  DEFAULT_TIMEOUT_MS,
  isBookroomError,
  isBudgetExceededError,
  isCancelledError,
  isConflictError,
  isExtractionFailedError,
  isNotFoundError,
  isProviderError,
  isQuotaError,
  isRetryableError,
  isTimeoutError,
  isUnsupportedSourceError,
  isUnauthorizedError,
  resolveConfig,
} from '../dist/esm/index.js';
import { MOCK_TOKEN, startMockFacade } from './mock-facade.js';

describe('authentication', () => {
  let facade;
  let bookroom;

  before(async () => {
    facade = await startMockFacade();
    bookroom = new Bookroom({ baseUrl: facade.baseUrl, token: MOCK_TOKEN, maxRetries: 0 });
  });
  after(async () => {
    await facade.close();
  });

  it('sends the facade token as a bearer header', async () => {
    await bookroom.ping();
    const request = facade.state.requests.at(-1);
    assert.equal(request.headers.authorization, `Bearer ${MOCK_TOKEN}`);
  });

  it('never sends an Authorization header when no token is configured', async () => {
    const anonymous = new Bookroom({ baseUrl: facade.baseUrl });
    await assert.rejects(
      () => anonymous.ping(),
      (error) => {
        assert.ok(isUnauthorizedError(error));
        assert.equal(error.status, 401);
        return true;
      },
    );
    const request = facade.state.requests.at(-1);
    assert.equal(request.headers.authorization, undefined);
  });

  it('maps a missing token to a 401 BookroomError', async () => {
    const wrongToken = new Bookroom({ baseUrl: facade.baseUrl, token: 'nope' });
    await assert.rejects(
      () => wrongToken.describe(),
      (error) => {
        assert.ok(error instanceof BookroomError);
        assert.equal(error.code, 'unauthorized');
        assert.equal(error.status, 401);
        assert.equal(error.method, 'GET');
        assert.match(error.url, /\/v1\/describe$/);
        assert.equal(error.retryAfterSeconds, undefined);
        assert.equal(error.isRetryable, false);
        return true;
      },
    );
  });
});

describe('error mapping', () => {
  let facade;
  let bookroom;

  before(async () => {
    facade = await startMockFacade();
    bookroom = new Bookroom({ baseUrl: facade.baseUrl, token: MOCK_TOKEN, maxRetries: 3 });
  });
  after(async () => {
    await facade.close();
  });

  it('maps a 400 into the server code, message, and type', async () => {
    await assert.rejects(
      // An empty path fails the facade's own required-field check.
      () => bookroom.extract.extract({ path: '' }),
      (error) => {
        assert.ok(isBookroomError(error));
        assert.equal(error.code, 'invalid_request');
        assert.equal(error.status, 400);
        assert.equal(error.type, 'ValueError');
        assert.match(error.message, /Missing required field\(s\): path/);
        assert.deepEqual(error.toJSON().code, 'invalid_request');
        return true;
      },
    );
  });

  it('never retries a 4xx client error', async () => {
    const before = facade.countFor('POST', '/v1/extract');
    await assert.rejects(() => bookroom.extract.extract({ path: '' }));
    assert.equal(facade.countFor('POST', '/v1/extract') - before, 1);
  });

  it('recognizes an unsupported source', async () => {
    await assert.rejects(
      () => bookroom.extract.extract({ path: '/books/notes.docx' }),
      (error) => {
        assert.ok(isUnsupportedSourceError(error));
        assert.equal(error.status, 415);
        return true;
      },
    );
  });

  it('maps an unknown route to not_found', async () => {
    await assert.rejects(
      () => bookroom.transport.request({ method: 'GET', path: '/v1/nope' }),
      (error) => {
        assert.ok(isNotFoundError(error));
        assert.equal(error.code, 'not_found');
        assert.equal(error.status, 404);
        return true;
      },
    );
  });

  it('maps a delete conflict', async () => {
    const job = await bookroom.jobs.studyGuide({ path: '/books/attention.epub' });
    await bookroom.jobs.get(job.id);
    await assert.rejects(
      () => bookroom.jobs.delete(job.id),
      (error) => {
        assert.ok(isConflictError(error));
        assert.equal(error.code, 'conflict');
        assert.equal(error.status, 409);
        return true;
      },
    );
  });

  it('raises the documented helpers for other server codes', async () => {
    const codes = [
      ['unsupported_source', 415, isUnsupportedSourceError],
      ['extraction_failed', 422, isExtractionFailedError],
      ['quota_exceeded', 429, isQuotaError],
      ['provider_error', 502, isProviderError],
      ['budget_exceeded', 422, isBudgetExceededError],
      ['not_found', 404, isNotFoundError],
    ];
    for (const [code, status, helper] of codes) {
      const error = new BookroomError('mapped', { code, status });
      assert.equal(helper(error), true, `${code} should match its helper`);
    }
    assert.equal(isBookroomError(new Error('plain')), false);
    assert.equal(isCancelledError(new BookroomError('cancelled', { code: 'cancelled', status: 409 })), true);
  });
});

describe('retries', () => {
  let facade;
  let bookroom;

  before(async () => {
    facade = await startMockFacade();
    bookroom = new Bookroom({
      baseUrl: facade.baseUrl,
      token: MOCK_TOKEN,
      maxRetries: 2,
      retryBaseDelayMs: 5,
      retryMaxDelayMs: 20,
    });
  });
  after(async () => {
    await facade.close();
  });

  it('retries a 429 and then succeeds', async () => {
    facade.failOnce({ status: 429, code: 'quota_exceeded', message: 'quota window', extra: { retry_after_seconds: 0 } });
    const notes = await bookroom.summarize.summarizeText({ text: 'Attention is scarce.', title: 'T' });
    assert.equal(notes, 'Notes for the supplied text.');
    assert.equal(facade.countFor('POST', '/v1/summarize-text'), 2);
  });

  it('retries a 502 and then succeeds', async () => {
    facade.failOnce({ status: 502, code: 'provider_error', message: 'upstream is down' });
    const health = await bookroom.check();
    assert.equal(health.ok, true);
    assert.equal(facade.countFor('GET', '/v1/check'), 2);
  });

  it('gives up after the configured number of attempts and keeps retry_after', async () => {
    const stubborn = new Bookroom({
      baseUrl: facade.baseUrl,
      token: MOCK_TOKEN,
      maxRetries: 1,
      retryBaseDelayMs: 1,
    });
    for (let attempt = 0; attempt < 2; attempt += 1) {
      facade.failOnce({
        status: 429,
        code: 'quota_exceeded',
        message: 'still limited',
        extra: { retry_after_seconds: 7 },
      });
    }
    const before = facade.countFor('GET', '/v1/sections');
    await assert.rejects(
      () => stubborn.sections(),
      (error) => {
        assert.ok(isQuotaError(error));
        assert.equal(error.retryAfterSeconds, 7);
        assert.equal(error.isRetryable, true);
        assert.equal(isRetryableError(error), true);
        return true;
      },
    );
    assert.equal(facade.countFor('GET', '/v1/sections') - before, 2);
  });

  it('does not retry when maxRetries is zero', async () => {
    const once = new Bookroom({ baseUrl: facade.baseUrl, token: MOCK_TOKEN, maxRetries: 0 });
    facade.failOnce({ status: 500, code: 'internal_error', message: 'boom' });
    const before = facade.countFor('GET', '/healthz');
    await assert.rejects(
      () => once.ping(),
      (error) => {
        assert.equal(error.status, 500);
        assert.equal(error.code, 'internal_error');
        return true;
      },
    );
    assert.equal(facade.countFor('GET', '/healthz') - before, 1);
  });
});

describe('timeouts and aborts', () => {
  let facade;

  before(async () => {
    facade = await startMockFacade();
  });
  after(async () => {
    await facade.close();
  });

  it('raises a timeout error when the server is too slow', async () => {
    const bookroom = new Bookroom({
      baseUrl: facade.baseUrl,
      token: MOCK_TOKEN,
      timeoutMs: 30,
      maxRetries: 0,
    });
    facade.delay('GET', '/v1/capabilities', 250);
    await assert.rejects(
      () => bookroom.capabilities(),
      (error) => {
        assert.ok(isTimeoutError(error));
        assert.equal(error.code, 'timeout');
        assert.equal(error.status, 408);
        assert.match(error.message, /timed out after 30 ms/);
        return true;
      },
    );
    facade.state.delays.clear();
  });

  it('honors a caller abort signal', async () => {
    const bookroom = new Bookroom({ baseUrl: facade.baseUrl, token: MOCK_TOKEN, maxRetries: 0 });
    facade.delay('GET', '/v1/ocr-languages', 250);
    const controller = new AbortController();
    const pending = bookroom.ocrLanguages({ signal: controller.signal });
    setTimeout(() => controller.abort(), 20);
    await assert.rejects(
      () => pending,
      (error) => {
        assert.ok(isCancelledError(error));
        return true;
      },
    );
    facade.state.delays.clear();
  });
});

describe('study guide', () => {
  let facade;
  let bookroom;

  before(async () => {
    facade = await startMockFacade();
    bookroom = new Bookroom({ baseUrl: facade.baseUrl, token: MOCK_TOKEN });
  });
  after(async () => {
    await facade.close();
  });

  it('maps the full report payload', async () => {
    const report = await bookroom.summarize.studyGuide({
      path: '/books/attention.epub',
      outputSlug: 'attention',
      review: true,
      options: { language: 'English', digest_length: 'deep' },
    });

    const request = facade.state.requests.at(-1);
    assert.equal(request.path, '/v1/study-guide');
    assert.deepEqual(request.body, {
      path: '/books/attention.epub',
      options: { language: 'English', digest_length: 'deep' },
      output_slug: 'attention',
      review: true,
    });

    assert.equal(report.report_path, '/output/attention/study-guide.md');
    assert.equal(report.markdown.exists, true);
    assert.equal(report.pdf.media_type, 'application/pdf');
    assert.equal(report.claim_audit, null);
    assert.equal(report.preflight.batch_count, 1);
    assert.equal(report.quality.categories_reviewed, 16);
    assert.equal(report.quality.all_passed, false);
    assert.equal(report.quality.scores.one_sentence_summary.faithfulness, 4.4);
    assert.equal(report.artifacts.length, 2);
    assert.equal(report.document.section_count, 4);
  });

  it('maps a preflight estimate', async () => {
    const preflight = await bookroom.summarize.preflight({ path: '/books/attention.epub' });
    assert.equal(preflight.section_count, 4);
    assert.equal(preflight.gemini_input_tokens_estimate, 4820);
    assert.equal(preflight.jev_credits_estimate_worst_case, 640);
  });

  it('maps section, text, and digest notes', async () => {
    const section = await bookroom.summarize.summarizeSection({
      title: 'Chapter 1',
      source: 'text',
      locator: 'p.1-12',
    });
    assert.equal(section, 'Notes for Chapter 1');

    const text = await bookroom.summarize.summarizeText({ text: 'raw text' });
    assert.equal(text, 'Notes for the supplied text.');

    const digest = await bookroom.summarize.digest({ title: 'Attention', chapterNotes: 'notes' });
    assert.equal(digest, 'Digest of Attention');
  });
});

describe('extraction, review, and exports', () => {
  let facade;
  let bookroom;

  before(async () => {
    facade = await startMockFacade();
    bookroom = new Bookroom({ baseUrl: facade.baseUrl, token: MOCK_TOKEN });
  });
  after(async () => {
    await facade.close();
  });

  it('extracts sections and includes text only when asked', async () => {
    const bare = await bookroom.extract.extract({ path: '/books/attention.epub' });
    assert.equal(bare.sections[0].text, undefined);
    assert.equal(bare.sections[0].ocr_confidence, null);

    const withText = await bookroom.extract.extract({ path: '/books/attention.epub', includeText: true });
    assert.equal(withText.sections[0].text, 'Attention is scarce.');
  });

  it('reads metadata and the outline', async () => {
    const metadata = await bookroom.extract.metadata('/books/attention.pdf');
    assert.equal(metadata.pages, 42);
    assert.equal(metadata.author, 'A. Reader');

    const outline = await bookroom.extract.outline('/books/attention.pdf');
    assert.equal(outline.length, 2);
    assert.equal(outline[0].level, 1);
  });

  it('runs standalone and per-section review', async () => {
    const evaluation = await bookroom.review.evaluate({
      sourceExcerpt: 'Water freezes at 0C.',
      summary: 'Water freezes at 0C.',
    });
    assert.equal(evaluation.answers.faithfulness, 4);
    assert.equal(evaluation.model, 'jev-latest');

    const section = await bookroom.review.evaluateSection({
      title: 'Chapter 1',
      source: 'source',
      draft: 'draft',
    });
    assert.equal(section.passed, true);
    assert.equal(section.scores.faithfulness, 4.2);
  });

  it('runs the 16-category gate and reads the stored evaluations', async () => {
    const records = await bookroom.review.report('/output/attention/study-guide.md');
    assert.equal(records.length, 16);
    assert.equal(records[0].section_key, 'one_sentence_summary');
    assert.equal(records[0].attempts[0].passed, true);

    const evaluations = await bookroom.review.evaluations('/output/attention/study-guide.md');
    assert.equal(evaluations.report_section_count, 16);
  });

  it('exports every artifact type', async () => {
    const pdf = await bookroom.export.pdf({ reportPath: '/output/attention/study-guide.md' });
    assert.equal(pdf.media_type, 'application/pdf');

    const custom = await bookroom.export.pdf({
      reportPath: '/output/attention/study-guide.md',
      pdfPath: '/output/attention/custom.pdf',
    });
    assert.equal(custom.path, '/output/attention/custom.pdf');

    const markdown = await bookroom.export.markdown('/output/attention/study-guide.md');
    assert.match(markdown, /# Attention/);

    const problems = await bookroom.export.validate(markdown);
    assert.deepEqual(problems, []);

    const rendered = await bookroom.export.render({
      title: 'Attention',
      sections: { one_sentence_summary: 'Body.' },
      author: 'A. Reader',
      sourceName: 'attention.epub',
    });
    assert.match(rendered, /# Attention/);
    const renderRequest = facade.state.requests.at(-1);
    assert.equal(renderRequest.body.source_name, 'attention.epub');

    const conceptMap = await bookroom.export.conceptMap('/output/attention/study-guide.md');
    assert.equal(conceptMap.nodes[0].id, 'attention');
    assert.equal(conceptMap.edges[0].relation, 'subconcept_of');

    const audit = await bookroom.export.claimAudit({
      reportPath: '/output/attention/study-guide.md',
      chapterNotes: '/output/attention/chapter-notes.md',
      minOverlap: 0.2,
    });
    assert.equal(audit.claim_count, 1);
    assert.equal(audit.claims[0].status, 'source_overlap_found');

    const manifest = await bookroom.export.manifest({
      reportPath: '/output/attention/study-guide.md',
      sourcePath: '/books/attention.epub',
    });
    assert.equal(manifest.generation_model, 'gemini-3.8-flash');
    assert.equal(manifest.source_sha256, 'deadbeef');

    const merged = await bookroom.export.merge({ folder: '/output/attention', destination: '/out/book.md' });
    assert.equal(merged, '/out/book.md');

    const artifacts = await bookroom.export.artifacts('/output/attention/study-guide.md');
    assert.equal(artifacts.length, 2);
    const artifactsRequest = facade.state.requests.at(-1);
    assert.equal(artifactsRequest.query.report_path, '/output/attention/study-guide.md');

    const usage = await bookroom.export.usage();
    assert.equal(usage.total_tokens, 10940);
  });

  it('translates and triages chapters', async () => {
    const translated = await bookroom.translate.translate({ text: 'Hola', targetLang: 'English' });
    assert.equal(translated, '[English] Hola');

    const batch = await bookroom.translate.translateBatch({ texts: ['a', 'b'], targetLang: 'es' });
    assert.deepEqual(batch, ['[es] a', '[es] b']);

    const relevant = await bookroom.translate.classify(['keep', 'drop']);
    assert.deepEqual(relevant, ['keep']);

    const notes = await bookroom.translate.notes(['one', 'two']);
    assert.deepEqual(notes, ['notes: one', 'notes: two']);
  });

  it('exposes discovery routes', async () => {
    const health = await bookroom.health.ping();
    assert.equal(health.status, 'ok');

    const check = await bookroom.check();
    assert.equal(check.llm.model, 'gemini-3.8-flash');

    const description = await bookroom.describe();
    assert.equal(description.config.llm_api_key_set, true);
    assert.ok(description.capabilities.includes('summarize.study_guide'));

    const capabilities = await bookroom.capabilities();
    assert.ok(capabilities.includes('export.pdf'));

    const sections = await bookroom.sections();
    assert.equal(sections.length, 16);

    const languages = await bookroom.ocrLanguages();
    assert.deepEqual(languages, ['eng', 'fra', 'deu', 'spa']);

    const usage = await bookroom.usage();
    assert.equal(usage.calls, 18);
  });
});

describe('jobs', () => {
  let facade;
  let bookroom;

  before(async () => {
    facade = await startMockFacade({ pollsBeforeDone: 2 });
    bookroom = new Bookroom({ baseUrl: facade.baseUrl, token: MOCK_TOKEN });
  });
  after(async () => {
    await facade.close();
  });

  it('polls a job to success and returns the report', async () => {
    const job = await bookroom.jobs.studyGuide({ path: '/books/attention.epub', outputSlug: 'jobbed' });
    assert.equal(job.status, 'queued');
    assert.equal(job.kind, 'study-guide');

    const createRequest = facade.state.requests.at(-1);
    assert.equal(createRequest.path, '/v1/jobs');
    assert.equal(createRequest.body.output_slug, 'jobbed');

    const seen = [];
    const finished = await bookroom.waitForJob(job.id, {
      pollIntervalMs: 5,
      timeoutMs: 5000,
      onUpdate: (update) => seen.push(update.status),
    });

    assert.equal(finished.status, 'succeeded');
    assert.ok(seen.includes('running'));
    assert.equal(seen.at(-1), 'succeeded');
    assert.ok(finished.messages.length >= 3);

    const pollRequest = facade.state.requests.at(-1);
    assert.equal(pollRequest.query.messages, '1');

    const report = await bookroom.jobs.waitForReport(job.id, { pollIntervalMs: 5, timeoutMs: 5000 });
    assert.equal(report.report_path, '/output/attention/study-guide.md');

    const deleted = await bookroom.jobs.delete(job.id);
    assert.equal(deleted, job.id);
  });

  it('lists jobs and starts a review-report job with both fields', async () => {
    const job = await bookroom.jobs.reviewReport({ reportPath: '/output/attention/study-guide.md' });
    const createRequest = facade.state.requests.at(-1);
    assert.equal(createRequest.body.kind, 'review-report');
    assert.equal(createRequest.body.report_path, '/output/attention/study-guide.md');
    assert.equal(createRequest.body.path, '/output/attention/study-guide.md');

    const jobs = await bookroom.jobs.list();
    assert.ok(jobs.some((entry) => entry.id === job.id));

    const single = await bookroom.jobs.get(job.id, { messages: true });
    assert.equal(single.id, job.id);
  });

  it('raises a job error when polling an unknown id', async () => {
    await assert.rejects(
      () => bookroom.jobs.waitFor('does-not-exist', { pollIntervalMs: 5, timeoutMs: 500 }),
      (error) => {
        assert.ok(isNotFoundError(error));
        return true;
      },
    );
  });
});

describe('configuration', () => {
  it('reads BOOKROOM_* variables', () => {
    const config = resolveConfig({
      env: {
        BOOKROOM_URL: 'http://example.test:9999/',
        BOOKROOM_FACADE_TOKEN: 'from-env',
        BOOKROOM_TIMEOUT_MS: '1234',
        BOOKROOM_APP_ROOT: 'D:/books',
      },
    });
    assert.equal(config.baseUrl, 'http://example.test:9999');
    assert.equal(config.token, 'from-env');
    assert.equal(config.timeoutMs, 1234);
    assert.equal(config.appRoot, 'D:/books');
    assert.equal(config.longRunningTimeoutMs, 1_800_000);
  });

  it('defaults sensibly and lets options win over the environment', () => {
    const fromEnv = resolveConfig({ env: {} });
    assert.equal(fromEnv.baseUrl, 'http://127.0.0.1:8787');
    assert.equal(fromEnv.timeoutMs, DEFAULT_TIMEOUT_MS);
    assert.equal(fromEnv.token, undefined);

    const overridden = resolveConfig({
      baseUrl: 'http://other.test:1',
      token: 'option-token',
      env: { BOOKROOM_URL: 'http://ignored.test', BOOKROOM_FACADE_TOKEN: 'env-token' },
    });
    assert.equal(overridden.baseUrl, 'http://other.test:1');
    assert.equal(overridden.token, 'option-token');
  });

  it('rejects a bad base URL', () => {
    assert.throws(() => resolveConfig({ baseUrl: 'not-a-url', env: {} }), /absolute http\(s\) URL/);
    assert.throws(() => resolveConfig({ baseUrl: 'ftp://host', env: {} }), /must use http or https/);
  });

  it('resolves relative paths against the app root for readable logs', () => {
    const bookroom = new Bookroom({ baseUrl: 'http://127.0.0.1:8787', appRoot: 'D:/books' });
    assert.equal(bookroom.resolvePath('attention.epub'), 'D:/books/attention.epub');
    assert.equal(bookroom.resolvePath('C:/elsewhere/a.epub'), 'C:/elsewhere/a.epub');
    assert.equal(bookroom.resolvePath('/srv/a.epub'), '/srv/a.epub');
    assert.equal(bookroom.appRoot, 'D:/books');

    const rootless = new Bookroom({ baseUrl: 'http://127.0.0.1:8787' });
    assert.equal(rootless.resolvePath('attention.epub'), 'attention.epub');
    assert.equal(rootless.appRoot, undefined);
  });

  it('copies configuration with withOptions and keeps the original intact', () => {
    const original = new Bookroom({ baseUrl: 'http://127.0.0.1:8787', token: 'first' });
    const copy = original.withOptions({ token: 'second', timeoutMs: 999 });
    assert.equal(copy.config.token, 'second');
    assert.equal(copy.config.timeoutMs, 999);
    assert.equal(original.config.token, 'first');
    assert.equal(original.config.timeoutMs, DEFAULT_TIMEOUT_MS);
    assert.match(String(original), /auth=bearer/);
  });

  it('uses an injected fetch implementation', async () => {
    const calls = [];
    const fake = async (url, init) => {
      calls.push({ url, init });
      return {
        ok: true,
        status: 200,
        headers: { get: () => null },
        text: async () => JSON.stringify({ status: 'ok', sdk_version: '9.9.9' }),
      };
    };
    const bookroom = new Bookroom({ baseUrl: 'http://injected.test', fetch: fake });
    const health = await bookroom.ping();
    assert.equal(health.sdk_version, '9.9.9');
    assert.equal(calls[0].url, 'http://injected.test/healthz');
    assert.equal(calls[0].init.method, 'GET');
    assert.equal(calls[0].init.headers.accept, 'application/json');
  });
});
