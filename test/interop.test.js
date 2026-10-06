/**
 * Dual-package checks.
 *
 * The package ships ESM and CommonJS builds, so `import` and `require` must
 * both work, from the same exports map, against a live mock facade.
 */

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { after, before, describe, it } from 'node:test';

import { Bookroom as EsmBookroom, isBookroomError } from '../dist/esm/index.js';
import { MOCK_TOKEN, startMockFacade } from './mock-facade.js';

const require = createRequire(import.meta.url);

describe('dual package', () => {
  it('exposes the same API through require() and import', () => {
    const cjs = require('../dist/cjs/index.js');
    assert.equal(typeof cjs.Bookroom, 'function');
    assert.equal(typeof cjs.BookroomError, 'function');
    assert.equal(typeof cjs.isQuotaError, 'function');
    assert.equal(typeof cjs.VERSION, 'string');
    assert.equal(typeof EsmBookroom, 'function');

    const fromCjs = new cjs.Bookroom({ baseUrl: 'http://127.0.0.1:8787' });
    const fromEsm = new EsmBookroom({ baseUrl: 'http://127.0.0.1:8787' });
    for (const namespace of ['health', 'extract', 'summarize', 'review', 'export', 'translate', 'jobs']) {
      assert.ok(namespace in fromCjs, `cjs is missing ${namespace}`);
      assert.ok(namespace in fromEsm, `esm is missing ${namespace}`);
    }
  });

  it('recognizes an error thrown by the other build', () => {
    const cjs = require('../dist/cjs/index.js');
    const error = new cjs.BookroomError('from cjs', { code: 'quota_exceeded', status: 429, retryAfterSeconds: 3 });
    assert.equal(isBookroomError(error), true);
    assert.equal(cjs.isQuotaError(error), true);
  });

  it('declares import, require, and types conditions', async () => {
    const manifest = JSON.parse(
      await readFile(new URL('../package.json', import.meta.url), 'utf8'),
    );
    assert.equal(manifest.type, 'module');
    const entry = manifest.exports['.'];
    assert.equal(entry.import, './dist/esm/index.js');
    assert.equal(entry.require, './dist/cjs/index.js');
    assert.equal(entry.types.import, './dist/esm/index.d.ts');
    assert.equal(entry.types.require, './dist/cjs/index.d.ts');
    assert.equal(manifest.engines.node, '>=18');
  });

  it('drives a real request from the CommonJS build', async () => {
    const cjs = require('../dist/cjs/index.js');
    const facade = await startMockFacade();
    try {
      const bookroom = new cjs.Bookroom({ baseUrl: facade.baseUrl, token: MOCK_TOKEN });
      const health = await bookroom.ping();
      assert.equal(health.status, 'ok');
      assert.equal(facade.state.requests.at(-1).headers.authorization, `Bearer ${MOCK_TOKEN}`);
    } finally {
      await facade.close();
    }
  });
});

describe('transport edge cases', () => {
  let facade;

  before(async () => {
    facade = await startMockFacade();
  });
  after(async () => {
    await facade.close();
  });

  it('reports an unreachable facade as a network error', async () => {
    const bookroom = new EsmBookroom({ baseUrl: 'http://127.0.0.1:1', maxRetries: 0, timeoutMs: 2000 });
    await assert.rejects(
      () => bookroom.ping(),
      (error) => {
        assert.equal(error.code, 'network_error');
        assert.equal(error.status, 0);
        assert.equal(isBookroomError(error), true);
        return true;
      },
    );
  });

  it('reports a non-JSON body as a protocol error', async () => {
    const bookroom = new EsmBookroom({
      baseUrl: facade.baseUrl,
      maxRetries: 0,
      fetch: async () => ({
        ok: true,
        status: 200,
        headers: { get: () => null },
        text: async () => '<html>not json</html>',
      }),
    });
    await assert.rejects(
      () => bookroom.ping(),
      (error) => {
        assert.equal(error.code, 'invalid_response');
        return true;
      },
    );
  });

  it('honors a Retry-After header when the body has no retry_after_seconds', async () => {
    const bookroom = new EsmBookroom({
      baseUrl: facade.baseUrl,
      maxRetries: 0,
      fetch: async () => ({
        ok: false,
        status: 429,
        headers: { get: (name) => (name.toLowerCase() === 'retry-after' ? '12' : null) },
        text: async () => JSON.stringify({ error: { code: 'quota_exceeded', message: 'limited' } }),
      }),
    });
    await assert.rejects(
      () => bookroom.ping(),
      (error) => {
        assert.equal(error.retryAfterSeconds, 12);
        return true;
      },
    );
  });
});
