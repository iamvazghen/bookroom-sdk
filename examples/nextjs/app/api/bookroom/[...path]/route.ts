/**
 * The proxy route the browser talks to.
 *
 * The React bindings in `bookroom-sdk/react` build a client pointed at
 * `/api/bookroom`, so every call they make lands here:
 *
 *   GET  /api/bookroom/v1/describe      -> client.describe()
 *   GET  /api/bookroom/v1/check         -> client.check()
 *   GET  /api/bookroom/v1/jobs          -> client.jobs.list()
 *   GET  /api/bookroom/v1/jobs/{id}     -> client.jobs.get(id, { messages: true })
 *   POST /api/bookroom/v1/jobs          -> client.jobs.studyGuide(...)
 *
 * `handleBookroomRequest` supplies the client (built from `BOOKROOM_URL` and
 * `BOOKROOM_FACADE_TOKEN`), turns a thrown `BookroomError` into the right status
 * with a trimmed body, and never sees a token from the browser.
 *
 * Job snapshots are forwarded in the facade's own shape rather than the trimmed
 * `ClientJob`, because the browser SDK reads `job.result` to render the report.
 * The `result` therefore still contains server-side file paths. That is fine for
 * a local tool; for anything public, serve the trimmed payload instead by
 * calling `getJobForClient(id, { exposePaths: false })` and teaching your client
 * to read `report` instead of `result`.
 */

import { BookroomError } from 'bookroom-sdk';
import { handleBookroomRequest } from 'bookroom-sdk/next';

/** Next.js 15 hands `params` to the handler as a promise. */
interface RouteContext {
  params: Promise<{ path?: string[] }>;
}

/** The catch-all segments, minus the leading `v1`. */
function tailSegments(params: Record<string, string | string[] | undefined>): string[] {
  const raw = params['path'];
  const segments = Array.isArray(raw) ? raw : typeof raw === 'string' ? raw.split('/') : [];
  return segments[0] === 'v1' ? segments.slice(1) : segments;
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  const response = await handleBookroomRequest(
    async ({ client, params, signal }) => {
      const tail = tailSegments(params);
      const [head, id] = tail;

      if (head === undefined) {
        throw new BookroomError('No facade route was requested.', {
          code: 'not_found',
          status: 404,
        });
      }
      if (head === 'describe') return client.describe();
      if (head === 'check') return client.check();
      if (head === 'capabilities') return client.capabilities();
      if (head === 'jobs' && id === undefined) return { jobs: await client.jobs.list() };

      if (head === 'jobs' && id !== undefined) {
        const snapshot = await client.jobs.get(decodeURIComponent(id), {
          messages: true,
          ...(signal === undefined ? {} : { signal }),
        });
        return snapshot;
      }

      throw new BookroomError(`This app does not proxy GET /v1/${tail.join('/')}.`, {
        code: 'not_found',
        status: 404,
      });
    },
    request,
    context.params,
    { methods: ['GET'] },
  );

  // `handleBookroomRequest` returns a real Response; its declared type is the
  // narrower structural one so this package compiles without the DOM lib.
  return response as unknown as Response;
}

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  const response = await handleBookroomRequest(
    async ({ client, params, signal }) => {
      const tail = tailSegments(params);
      if (tail[0] !== 'jobs') {
        throw new BookroomError(`This app does not proxy POST /v1/${tail.join('/')}.`, {
          code: 'not_found',
          status: 404,
        });
      }

      const body = (await request.json().catch(() => ({}))) as {
        path?: unknown;
        output_slug?: unknown;
        review?: unknown;
      };
      if (typeof body.path !== 'string' || body.path.trim() === '') {
        throw new BookroomError('A book path is required.', { code: 'invalid_request', status: 400 });
      }

      const started = await client.jobs.studyGuide({
        path: body.path,
        ...(typeof body.output_slug === 'string' ? { outputSlug: body.output_slug } : {}),
        ...(typeof body.review === 'boolean' ? { review: body.review } : {}),
        ...(signal === undefined ? {} : { signal }),
      });
      return started;
    },
    request,
    context.params,
    { methods: ['POST'], status: 202 },
  );

  return response as unknown as Response;
}