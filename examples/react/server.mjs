/**
 * The proxy that keeps the facade token out of the browser.
 *
 * The Vite app calls `/api/bookroom/...` on this process. It forwards the request
 * to the facade, adds `Authorization: Bearer <token>`, and returns the response.
 * The token exists in this process and nowhere else: it is never sent to the page,
 * never written into the bundle, and never logged.
 *
 * Run it on its own:
 *   node server.mjs
 *
 * Or let Vite forward `/api/bookroom` here while developing:
 *   node server.mjs        # port 8788
 *   npm run dev            # Vite on 5173
 *
 * For a production preview, build first and this server also serves `dist/`:
 *   npm run build && NODE_ENV=production node server.mjs
 */

import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import express from 'express';

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** Where the facade is listening. */
const FACADE_URL = (process.env.BOOKROOM_URL ?? 'http://127.0.0.1:8787').replace(/\/+$/, '');

/**
 * The facade token. It is read here and nowhere else in the example.
 *
 * Leave it unset when the facade was started without `--token`.
 */
const FACADE_TOKEN = process.env.BOOKROOM_FACADE_TOKEN ?? process.env.BOOKROOM_TOKEN ?? '';

const PORT = Number(process.env.PORT ?? 8788);
const IS_PRODUCTION = process.env.NODE_ENV === 'production';

const app = express();

// The SDK sends JSON, so a small JSON parser is enough. The raw body is not
// needed: request bodies are forwarded verbatim below.
app.use(express.json({ limit: '2mb' }));

/** Collect a request body as text, so it can be forwarded unchanged. */
function readRawBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

/**
 * Strip the fields that must not reach a browser.
 *
 * The facade's error envelope may carry `trace` (a Python traceback), `type`
 * (an exception class), and internal URLs. The SDK's `bookroom-sdk/next`
 * helpers do the same trimming, plus path trimming on job results.
 */
function sanitizeErrorBody(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return text;
  }
  if (typeof parsed !== 'object' || parsed === null || parsed.error === undefined) return text;
  const { trace, type, url, method, ...safe } = parsed.error;
  void trace;
  void type;
  void url;
  void method;
  return JSON.stringify({ ...parsed, error: safe });
}

app.all('/api/bookroom*', async (req, res) => {
  const suffix = req.url === '/' ? '' : req.url; // keeps the query string
  const target = `${FACADE_URL}${suffix}`;

  /** @type {Record<string, string>} */
  const headers = { accept: 'application/json' };
  if (FACADE_TOKEN !== '') headers.authorization = `Bearer ${FACADE_TOKEN}`;

  let body;
  if (req.method !== 'GET' && req.method !== 'HEAD' && req.method !== 'DELETE') {
    body = await readRawBody(req);
    if (body !== '') headers['content-type'] = 'application/json';
  }

  try {
    const upstream = await fetch(target, {
      method: req.method,
      headers,
      ...(body === undefined ? {} : { body }),
    });
    const text = await upstream.text();

    // Forward the retry hint so a rate-limited client can back off properly.
    const retryAfter = upstream.headers.get('retry-after');
    if (retryAfter !== null) res.set('retry-after', retryAfter);

    res.status(upstream.status);
    res.set('content-type', upstream.headers.get('content-type') ?? 'application/json');
    res.send(upstream.ok ? text : sanitizeErrorBody(text));
  } catch (error) {
    // The facade is down. Say so as a gateway error rather than a 500, and do
    // not echo the token, the URL, or the underlying error to the browser.
    console.error(`[proxy] could not reach the facade at ${FACADE_URL}:`, error);
    res.status(502).json({
      error: {
        name: 'BookroomNetworkError',
        code: 'network_error',
        status: 502,
        message: 'The Bookroom facade is unreachable from this proxy.',
      },
    });
  }
});

app.get('/api/healthz', (_req, res) => {
  res.json({
    proxy: 'ok',
    facade_url: FACADE_URL,
    token_configured: FACADE_TOKEN !== '',
  });
});

// Serve the built app when it exists, so `npm run build && node server.mjs`
// gives a single-origin deployment with no CORS setup.
const dist = path.join(HERE, 'dist');
if (IS_PRODUCTION || existsSync(dist)) {
  app.use(express.static(dist));
  app.get(/^(?!\/api\/).*/, (_req, res) => {
    res.sendFile(path.join(dist, 'index.html'));
  });
}

app.listen(PORT, () => {
  console.log(`[proxy] listening on http://127.0.0.1:${PORT}`);
  console.log(`[proxy] forwarding /api/bookroom -> ${FACADE_URL}`);
  console.log(`[proxy] facade token ${FACADE_TOKEN === '' ? 'NOT set' : 'loaded (never sent to the browser)'}`);
  if (!existsSync(dist)) {
    console.log('[proxy] no dist/ yet, run "npm run build" to serve the app from here');
  }
});