/**
 * The same flow as `examples/typescript`, in plain ESM JavaScript.
 *
 * Nothing here is TypeScript: the shapes are described with JSDoc, which means
 * an editor and `tsc --checkJs` still catch a wrong argument or a renamed
 * option, while the file runs on plain Node with no build step.
 *
 * The facade token is read from `BOOKROOM_FACADE_TOKEN` and stays in this
 * process. This script belongs on a server, never in a browser bundle.
 *
 * Usage:
 *   node src/study-guide.mjs --path /books/attention.epub
 */

import { Bookroom, VERSION, hasErrorCode, isBookroomError, isJobFailedError } from 'bookroom-sdk';

/**
 * @typedef {object} ExampleConfig
 * @property {string} baseUrl Facade base URL, without a trailing slash.
 * @property {string | undefined} token Facade token, when the server requires one.
 * @property {string} path Book to summarize, resolved on the machine running the facade.
 * @property {string | undefined} outputSlug Output folder name, when you want to force one.
 * @property {boolean} review Run the JEv quality gate.
 * @property {number} pollIntervalMs Milliseconds between polls.
 * @property {boolean} skipCheck Skip the provider check.
 * @property {boolean} skipPreflight Skip the cost estimate.
 */

/**
 * @typedef {object} Artifact
 * @property {string} name
 * @property {string | null} path
 * @property {string} media_type
 * @property {boolean} exists
 */

/**
 * Read a flag in the form `--name value` or `--name=value`.
 *
 * @param {readonly string[]} argv
 * @param {string} name
 * @returns {string | undefined}
 */
function readFlag(argv, name) {
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

/**
 * True when a bare flag such as `--no-review` was passed.
 *
 * @param {readonly string[]} argv
 * @param {string} name
 * @returns {boolean}
 */
function hasFlag(argv, name) {
  return argv.includes(`--${name}`);
}

/**
 * Merge arguments and `BOOKROOM_*` variables into one configuration.
 *
 * @param {readonly string[]} [argv]
 * @returns {ExampleConfig}
 */
export function readConfig(argv = process.argv.slice(2)) {
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
    baseUrl:
      readFlag(argv, 'base-url') ??
      env['BOOKROOM_URL'] ??
      env['BOOKROOM_BASE_URL'] ??
      'http://127.0.0.1:8787',
    token: token === undefined || token.trim() === '' ? undefined : token.trim(),
    path: path.trim(),
    outputSlug: readFlag(argv, 'slug'),
    review: !hasFlag(argv, 'no-review'),
    pollIntervalMs,
    skipCheck: hasFlag(argv, 'skip-check'),
    skipPreflight: hasFlag(argv, 'skip-preflight'),
  };
}

/**
 * Narrow an untyped job result to something report-shaped.
 *
 * `jobs.waitFor` returns `result?: unknown`, so the shape has to be checked
 * before any property is read.
 *
 * @param {unknown} value
 * @returns {{ output_dir: string, document: { title: string, kind: string, section_count: number, total_words: number }, markdown: Artifact, report_path: string | null, quality: ({ enabled: boolean, all_passed: boolean, categories_passed: number, categories_reviewed: number, threshold: number } | null), artifacts: Artifact[] }}
 */
function asReport(value) {
  if (typeof value !== 'object' || value === null) {
    throw new Error('The job finished without a result object.');
  }
  const candidate = /** @type {Record<string, unknown>} */ (value);
  if (typeof candidate['output_dir'] !== 'string' || !Array.isArray(candidate['artifacts'])) {
    throw new Error('The job finished with a result that is not a study-guide report.');
  }
  return /** @type {ReturnType<typeof asReport>} */ (value);
}

/**
 * Print each artifact with its type and where it landed.
 *
 * @param {readonly Artifact[]} artifacts
 * @returns {void}
 */
function printArtifacts(artifacts) {
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

/**
 * Run describe, check, preflight, then a job to completion.
 *
 * @param {ExampleConfig} config
 * @returns {Promise<number>} Process exit code.
 */
export async function runStudyGuide(config) {
  const client = new Bookroom({
    baseUrl: config.baseUrl,
    ...(config.token !== undefined ? { token: config.token } : {}),
  });
  console.log(`bookroom-sdk ${VERSION} -> ${config.baseUrl}`);
  console.log(client.toString());

  const description = await client.describe();
  console.log(`\nServer ${description.sdk_version}`);
  console.log(`  model        ${String(description.config.llm_model ?? 'unknown')}`);
  console.log(`  LLM key      ${description.config.llm_api_key_set === true ? 'set' : 'missing'}`);
  console.log(`  JEv enabled  ${String(description.config.jev_enabled ?? false)}`);
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
    const estimate = await client.summarize.preflight({ path: config.path });
    console.log('\nPreflight');
    console.log(`  sections            ${estimate.section_count}`);
    console.log(`  batches             ${estimate.batch_count}`);
    console.log(`  input tokens (est.) ${estimate.gemini_input_tokens_estimate}`);
    console.log(`  JEv credits (worst) ${estimate.jev_credits_estimate_worst_case}`);
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

  const report = asReport(finished.result);
  console.log('\nReport');
  console.log(`  title       ${report.document.title}`);
  console.log(`  format      ${report.document.kind}`);
  console.log(`  sections    ${report.document.section_count}`);
  console.log(`  words       ${report.document.total_words}`);
  console.log(`  output dir  ${report.output_dir}`);
  console.log(`  markdown    ${report.markdown.path ?? '(not written)'}`);
  if (report.quality !== null && report.quality !== undefined) {
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
  console.log('\nDone.');
  return 0;
}

/**
 * Print a failure the way an operator needs to see it, then set the exit code.
 *
 * @param {unknown} error
 * @returns {void}
 */
function reportFailure(error) {
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

const isEntrypoint = process.argv[1] !== undefined && process.argv[1].includes('study-guide');
if (isEntrypoint) {
  runStudyGuide(readConfig())
    .then((code) => {
      if (code !== 0) process.exitCode = code;
    })
    .catch(reportFailure);
}