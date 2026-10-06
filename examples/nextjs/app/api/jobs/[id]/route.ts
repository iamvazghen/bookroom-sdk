/**
 * One job's status, trimmed for a browser.
 *
 * This is the route to copy when your UI should not see server-side detail.
 * `getJobForClient` replaces the raw `result` with a report summary, and by
 * default it does not include filesystem paths at all.
 *
 *   GET /api/jobs/9f2c...  ->  200 { id, status, message_count, report: {...} }
 *                          ->  404 { error: { code: "not_found", ... } }
 *
 * Add an `artifactHref` builder to give artifacts links: the facade serves
 * metadata but no file bytes, so the bytes have to come from a route of your
 * own.
 */

import { BookroomError } from 'bookroom-sdk';
import { getJobForClient, handleBookroomRequest } from 'bookroom-sdk/next';

interface RouteContext {
  params: Promise<{ id?: string }>;
}

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  const response = await handleBookroomRequest(
    async ({ params }) => {
      const raw = params['id'];
      const id = Array.isArray(raw) ? raw[0] : raw;
      if (id === undefined || id.trim() === '') {
        // A BookroomError carries its own status, so handleBookroomRequest
        // answers 400 instead of a generic 500.
        throw new BookroomError('A job id is required.', { code: 'invalid_request', status: 400 });
      }
      return getJobForClient(decodeURIComponent(id), {
        exposePaths: false,
        messages: true,
      });
    },
    request,
    context.params,
    { methods: ['GET'] },
  );

  return response as unknown as Response;
}