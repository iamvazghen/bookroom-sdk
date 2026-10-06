/**
 * Server actions.
 *
 * `'use server'` makes every export in this file a server action: the function
 * body runs only on the server, and only its arguments and return value cross
 * the boundary. That is what keeps `BOOKROOM_FACADE_TOKEN` out of the browser.
 *
 * The factories come from `bookroom-sdk/next`. Each one builds a token-bearing
 * client from the environment, runs the call, and returns a plain object; none
 * of them throws, because a rejected action reaches the browser as a framework
 * error page instead of a usable message.
 *
 * ```tsx
 * 'use client';
 * import { startStudyGuide, jobStatus } from './actions';
 *
 * const result = await startStudyGuide({ path: '/books/attention.epub' });
 * if (result.ok) console.log(result.data.id);
 * else console.error(result.error.code, result.error.message);
 * ```
 */

'use server';

import {
  createJobStatusAction,
  createPreflightAction,
  createSummarizeAction,
} from 'bookroom-sdk/next';

/**
 * Start a study-guide job.
 *
 * Returns as soon as the job exists. The path is resolved on the machine running
 * the facade, so validate it against your own allow-list before passing it on.
 */
export const startStudyGuide = createSummarizeAction();

/** One job's browser-safe snapshot. */
export const jobStatus = createJobStatusAction();

/** The server's own cost estimate, so an over-budget book fails early. */
export const preflight = createPreflightAction();