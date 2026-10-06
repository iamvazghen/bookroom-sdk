/**
 * End-to-end study-guide run against a live Bookroom facade.
 *
 * The flow mirrors what a real integration does:
 *
 * 1. `describe()`   — confirm which server you are talking to.
 * 2. `check()`      — confirm both providers answer before spending anything.
 * 3. `preflight()`  — ask the server what the run will cost.
 * 4. `jobs.studyGuide()` — start the run in the background.
 * 5. `jobs.waitFor()` — poll to completion, printing progress as it arrives.
 * 6. Print the report summary and its artifacts.
 *
 * The token is read from `BOOKROOM_FACADE_TOKEN` and stays in this process. This
 * is a server-side script; never move it into a browser bundle.
 *
 * Usage:
 *   node dist/study-guide.js --path /books/attention.epub
 */

import {
  Bookroom,
  VERSION,
  hasErrorCode,
  isBookroomError,
  isJobFailedError,
} from 'bookroom-sdk';
import type { Artifact, Preflight, Report } from 'bookroom-sdk';

/** Everything this script reads from arguments and the environment. */
interface ExampleConfig {
  baseUrl: string;
  token: string | undefined;
  path: string;
  outputSlug: string | undefined;
  review: boolean;
  pollIntervalMs: number;
  skipCheck: boolean;
  skipPreflight: boolean;
}

/** Read a flag in the form `--name value` or `--name=value`. */
function readFlag(argv: readonly string[], name: string): string | undefined {
  const prefix = `--${name}`;
  for (let index = 0; index < argv.length; index += 1) {
    const candidate = argv[index];
    if (candidate === prefix) return argv[index + 1];
    if (candidate !== undefined && candidate.startsWith(`${prefix}=`)) {
      return candidate.slice(prefix.length + 1);
    }
  }
  return undefined;
}

/** True when a bare flag such as `--no-review` was passed. */
function hasFlag(argv: readonly string[], name: string): boolean {
  return argv.includes(`--${name}`);
}

/** Merge arguments and `BOOKROOM_*` variables into one configuration. */
export function readConfig(argv: readonly string[] = process.argv.slice(2)): ExampleConfig {
  const env = process.env;
  const path = readFlag(argv, 'path') ?? env['BOOKROOM_PATH'];
  if (path === undefined || path.trim() === '') {
    throw new Error(
      'No book to summarize. Pass --path /books/title.epub or set BOOKROOM_PATH.\n' +
        'The path is resolved on the machine running the facade, not on yours.',
    );
  }
  const pollRaw = readFlag(argv, 'poll-ms');
  const pollIntervalMs = pollRaw === undefined ? 1500 : Number(pollRaw);
  if (!Number.isFinite(pollIntervalMs) || pollIntervalMs <= 0) {
    throw new Error(`--poll-ms must be a positive number, received "${pollRaw}"`);
  }
  const token = env['BOOKROOM_FACADE_TOKEN'] ?? env['BOOKROOM_TOKEN'];
  return {
    baseUrl: readFlag(argv, 'base-url') ?? env['BOOKROOM_URL'] ?? env['BOOKROOM_BASE_URL'] ?? 'http://127.0.0.1:8787',
    token: token === undefined || token.trim() === '' ? undefined : token.trim(),
    path: path.trim(),
    outputSlug: readFlag(argv, 'slug'),
    review: !hasFlag(argv, 'no-review'),
    pollIntervalMs,
    skipCheck: hasFlag(argv, 'skip-check'),
    skipPreflight: hasFlag(argv, 'skip-preflight'),
  };
}

/** Narrow an untyped job result to a report, with a readable failure. */
function asReport(value: unknown): Report {
  if (typeof value !== 'object' || value === null) {
    throw new Error('The job finished without a result object.');
  }
  const candidate = value as Partial<Report>;
  if (typeof candidate.output_dir !== 'string' || !Array.isArray(candidate.artifacts)) {
    throw new Error('The job finished with a result that is not a study-guide report.');
  }
  return candidate as Report;
}

function printArtifacts(artifacts: readonly Artifact[]): void {
  if (artifacts.length === 0) {
    console.log('  (no artifacts)');
    return;
  }
  for (const artifact of artifacts) {
    const location = artifact.path ?? '(no path)';
    const state = artifact.exists ? 'ok' : 'missing';
    console.log(`  [${state}] ${artifact.name} — ${artifact.media_type} — ${location}`);
  }
}

function printPreflight(estimate: Preflight): void {
  console.log('\nPreflight');
  console.log(`  sections            ${estimate.section_count}`);
  console.log(`  batches             ${estimate.batch_count}`);
  console.log(`  input tokens (est.) ${estimate.gemini_input_tokens_estimate}`);
  console.log(`  JEv credits (worst) ${estimate.jev_credits_estimate_worst_case}`);
}

function printReport(report: Report): void {
  console.log('\nReport');
  console.log(`  title       ${report.document.title}`);
  console.log(`  format      ${report.document.kind}`);
  console.log(`  sections    ${report.document.section_count}`);
  console.log(`  words       ${report.document.total_words}`);
  console.log(`  output dir  ${report.output_dir}`);
  console.log(`  markdown    ${report.markdown.path ?? '(not written)'}`);
  if (report.quality !== null) {
    const quality = report.quality;
    console.log(
      `  quality     ${quality.categories_passed}/${quality.categories_reviewed} categories passed` +
        (quality.all_passed ? ' (all passed)' : ` (threshold ${quality.threshold})`),
    );
  } else {
    console.log('  quality     not reviewed');
  }
  console.log('\nArtifacts');
  printArtifacts(report.artifacts);
}

/**
 * Run the whole flow and return a process exit code.
 *
 * Exported so a test, or another script, can call it with its own configuration
 * instead of driving it through the command line.
 */
export async function runStudyGuide(config: ExampleConfig): Promise<number> {
  const client = new Bookroom({
    baseUrl: config.baseUrl,
    ...(config.token !== undefined ? { token: config.token } : {}),
  });
  console.log(`bookroom-sdk ${VERSION} -> ${config.baseUrl}`);
  console.log(client.toString());

  const description = await client.describe();
  console.log(`\nServer ${description.sdk_version}`);
  console.log(`  model       ${String(description.config.llm_model ?? 'unknown')}`);
  console.log(`  LLM key     ${description.config.llm_api_key_set === true ? 'set' : 'missing'}`);
  console.log(`  JEv enabled ${String(description.config.jev_enabled ?? false)}`);
  console.log(`  capabilities ${description.capabilities.length}`);

  if (config.skipCheck) {
    console.log('\nProvider check skipped (--skip-check).');
  } else {
    const health = await client.check();
    console.log(`\nProviders ok=${String(health.ok)}`);
    console.log(`  llm    ${health.llm.status ?? 'unknown'} ${health.llm.model ?? ''}`.trimEnd());
    console.log(`  review ${health.review.status ?? 'unknown'} ${health.review.model ?? ''}`.trimEnd());
    if (!health.ok) {
      console.error('\nA provider is not healthy. Fix that before spending anything.');
      return 1;
    }
  }

  if (config.skipPreflight) {
    console.log('\nPreflight skipped (--skip-preflight).');
  } else {
    printPreflight(await client.summarize.preflight({ path: config.path }));
  }

  console.log(`\nStarting a study guide for ${config.path}. This takes minutes.`);
  const started = await client.jobs.studyGuide({
    path: config.path,
    ...(config.outputSlug !== undefined ? { outputSlug: config.outputSlug } : {}),
    review: config.review,
  });
  console.log(`  job ${started.id} (${started.status})`);

  let lastMessageCount = 0;
  const finished = await client.jobs.waitFor(started.id, {
    pollIntervalMs: config.pollIntervalMs,
    messages: true,
    onUpdate: (job) => {
      const messages = job.messages ?? [];
      for (let index = lastMessageCount; index < messages.length; index += 1) {
        console.log(`  [${job.status}] ${messages[index]}`);
      }
      lastMessageCount = messages.length;
      console.log(`  [${job.status}] ${job.message_count} progress messages`);
    },
  });

  printReport(asReport(finished.result));
  console.log('\nDone.');
  return 0;
}

/** Print a failure the way an operator needs to see it, then set the exit code. */
function reportFailure(error: unknown): void {
  if (!isBookroomError(error)) {
    console.error(error);
    process.exitCode = 1;
    return;
  }
  const failedJob = isJobFailedError(error) ? error.job : undefined;
  if (failedJob !== undefined) {
    console.error(`\nThe job failed: ${failedJob.error ?? 'no reason given'}`);
  } else if (hasErrorCode(error, 'quota_exceeded')) {
    console.error(
      `\nA provider quota was hit. Retry after ${error.retryAfterSeconds ?? 'an unknown number of'} seconds.`,
    );
  } else if (hasErrorCode(error, 'timeout')) {
    console.error('\nTimed out while waiting. The job may still be running on the server.');
  } else {
    console.error(`\n${error.name} [${error.code}] HTTP ${error.status}: ${error.message}`);
  }
  if (error.retryAfterSeconds !== undefined) {
    console.error(`Retry after ${error.retryAfterSeconds} seconds.`);
  }
  process.exitCode = 1;
}

/** Read the configuration, then run. Kept async so a bad config rejects. */
async function main(): Promise<number> {
  return runStudyGuide(readConfig());
}

const isEntrypoint = process.argv[1] !== undefined && process.argv[1].includes('study-guide');
if (isEntrypoint) {
  main()
    .then((code) => {
      if (code !== 0) process.exitCode = code;
    })
    .catch(reportFailure);
}