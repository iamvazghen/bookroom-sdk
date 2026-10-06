// Drive the REAL Python facade with the built TypeScript SDK.
//
// This is the cross-language proof: the Python engine (with a mock LLM/JEv
// provider behind it) serving genuine EPUB fixtures, exercised entirely through
// the TypeScript client over HTTP.
//
//   node cross_language_client.mjs <dist-entry> <baseUrl> <token> <epub>

import process from "node:process";

const [distEntry, baseUrl, token, epub] = process.argv.slice(2);
if (!distEntry || !baseUrl || !epub) {
  console.error("usage: node cross_language_client.mjs <dist-entry> <baseUrl> <token> <epub>");
  process.exit(2);
}

const mod = await import(distEntry);
const { Bookroom, BookroomError } = mod;

let passed = 0;
const failures = [];
const check = (label, ok, detail = "") => {
  if (ok) {
    passed += 1;
    console.log(`  PASS  ${label}${detail ? `  [${detail}]` : ""}`);
  } else {
    failures.push(label);
    console.log(`  FAIL  ${label}${detail ? `  [${detail}]` : ""}`);
  }
};

const room = new Bookroom({ baseUrl, token, timeoutMs: 900000 });

console.log("=== construction ===");
check("client constructed", room instanceof Bookroom);
const namespaces = ["extract", "summarize", "review", "export", "health", "jobs"];
check("all namespaces present", namespaces.every((n) => Boolean(room[n])),
  namespaces.filter((n) => room[n]).join(","));

console.log("\n=== metadata ===");
const described = await room.describe();
check("describe returns capabilities",
  Array.isArray(described.capabilities) && described.capabilities.length >= 35,
  `${described.capabilities?.length} capabilities`);
check("describe leaks no secret values", !JSON.stringify(described).includes("mock-llm-key"));
check("describe exports the LLM endpoint",
  String(described.config?.llm_endpoint ?? "").startsWith("http://127.0.0.1"),
  described.config?.llm_endpoint);
check("describe exports the review endpoint",
  Boolean(described.config?.jev_endpoint),
  described.config?.jev_endpoint);
check("describe exports the models",
  Boolean(described.config?.llm_model) && Boolean(described.config?.jev_model),
  `${described.config?.llm_model} / ${described.config?.jev_model}`);

const health = await room.check();
check("provider check via HTTP", health.ok === true, `llm=${health.llm?.status}`);

const sections = await room.sections();
check("16 report categories", sections.length === 16, `${sections.length}`);

const caps = await room.capabilities();
check("capabilities listed", Array.isArray(caps) && caps.length >= 35, `${caps.length}`);

console.log("\n=== extraction ===");
const doc = await room.extract.extract({ path: epub });
check("document extracted", doc.section_count >= 1, `${doc.section_count} sections`);
check("kind detected", doc.kind === "epub" || doc.kind === "pdf", doc.kind);
check("locators present", doc.sections.every((s) => Boolean(s.locator)));
check("words counted", doc.total_words > 500, `${doc.total_words} words`);
check("section words counted", doc.sections.every((s) => s.word_count > 0),
  doc.sections.map((s) => s.word_count).join(","));

const meta = await room.extract.metadata(epub);
check("metadata returned", meta.kind === doc.kind, `${meta.kind}, ${meta.size_bytes} bytes`);

console.log("\n=== preflight ===");
const plan = await room.summarize.preflight({ path: epub });
check("preflight counts sections", plan.section_count === doc.section_count,
  `${plan.section_count} vs ${doc.section_count}`);
check("preflight plans batches", plan.batch_count >= 1, `${plan.batch_count} batches`);
check("preflight estimates tokens", plan.gemini_input_tokens_estimate > 0,
  `${plan.gemini_input_tokens_estimate}`);
check("preflight estimates review credits", plan.jev_credits_estimate_worst_case > 0,
  `${plan.jev_credits_estimate_worst_case}`);

console.log("\n=== summarization ===");
const notes = await room.summarize.summarizeText({
  text: "Attention is the scarce resource. ".repeat(60),
  title: "Sample",
});
check("summarize-text returned notes", typeof notes === "string" && notes.length > 40,
  `${notes?.length} chars`);

console.log("\n=== study guide ===");
const report = await room.summarize.studyGuide({ path: epub, outputSlug: "ts-attention" });
check("study guide returned a report", Boolean(report.report_path), report.report_path);
const names = (report.artifacts ?? []).map((a) => a.name);
for (const expected of ["study-guide.md", "study-guide.pdf", "chapter-notes.md",
                        "study-maps.json", "claim-audit.json", "manifest.json"]) {
  check(`${expected} produced`, names.includes(expected));
}
check("16 categories reviewed", report.quality?.categories_reviewed === 16,
  `${report.quality?.categories_reviewed}`);
check("all categories passed", report.quality?.all_passed === true);
check("quality reports a threshold", typeof report.quality?.threshold === "number",
  String(report.quality?.threshold));

console.log("\n=== exports ===");
const md = await room.export.markdown(report.report_path);
check("markdown export", md.length > 2000, `${md.length} chars`);
const problems = await room.export.validate(md);
check("validation reports no problems", problems.length === 0, JSON.stringify(problems));
const pdf = await room.export.pdf({ reportPath: report.report_path });
check("pdf export exists", pdf.exists === true, pdf.path);
const graph = await room.export.conceptMap(report.report_path);
check("concept map is a graph", Array.isArray(graph.nodes) && graph.nodes.length > 0,
  `${graph.nodes?.length} nodes, ${graph.edges?.length} edges`);
const claims = await room.export.claimAudit({ reportPath: report.report_path });
check("claim audit produced", claims.claim_count > 0, `${claims.claim_count} claims`);
const manifest = await room.export.manifest({
  reportPath: report.report_path,
  sourcePath: epub,
});
check("manifest records the model", Boolean(manifest.generation_model), manifest.generation_model);
check("manifest records review state", manifest.jev_evaluation_enabled === true);
check("manifest holds no secrets",
  !JSON.stringify(manifest).includes("mock-llm-key") &&
  !JSON.stringify(manifest).includes("mock-jev-key"));
const usage = await room.export.usage(report.report_path);
check("usage reported", Number(usage.gemini?.calls) > 0,
  `${usage.gemini?.calls} calls, ${usage.gemini?.total_tokens} tokens`);
const artifacts = await room.export.artifacts(report.report_path);
check("artifact listing", artifacts.length > 0, `${artifacts.length} artifacts`);

console.log("\n=== review ===");
const evaluation = await room.review.evaluate({
  sourceExcerpt: "Water freezes at zero degrees Celsius.",
  summary: "Water freezes at zero degrees Celsius.",
});
check("standalone JEv evaluation", Boolean(evaluation.answers), Object.keys(evaluation).join(","));
const records = await room.review.report(report.report_path);
check("16-category gate returned records", records.length === 16, `${records.length}`);
const stored = await room.review.evaluations(report.report_path);
check("stored evaluations readable", Object.keys(stored).length > 0,
  Object.keys(stored).join(","));

console.log("\n=== async job ===");
const job = await room.jobs.studyGuide({ path: epub, outputSlug: "ts-job" });
check("job started", Boolean(job.id), job.id);
const finished = await room.jobs.waitFor(job.id, { timeoutMs: 900000, intervalMs: 400 });
check("job succeeded", finished.status === "succeeded", finished.status);
check("job recorded progress", finished.message_count > 0, `${finished.message_count} messages`);
const jobList = await room.jobs.list();
check("job listing", Array.isArray(jobList) && jobList.length > 0, `${jobList.length} jobs`);
check("job deletable", Boolean(await room.jobs.delete(job.id)));

console.log("\n=== errors ===");
try {
  await room.extract.extract({ path: "no-such-book.epub" });
  check("missing file raises BookroomError", false, "no error thrown");
} catch (error) {
  check("missing file raises BookroomError", error instanceof BookroomError,
    `${error.name} code=${error.code}`);
  check("error carries a status", typeof error.status === "number", String(error.status));
}
try {
  await room.review.evaluate({ sourceExcerpt: "", summary: "x" });
  check("empty input rejected", false, "no error thrown");
} catch (error) {
  check("empty input rejected", error instanceof BookroomError, String(error.code));
}
try {
  const anonymous = new Bookroom({ baseUrl, timeoutMs: 30000 });
  await anonymous.describe();
  check("missing token rejected", false, "request succeeded");
} catch (error) {
  check("missing token rejected",
    error instanceof BookroomError && String(error.status) === "401",
    `status ${error.status}`);
}

console.log(`\n${"=".repeat(62)}`);
console.log(`PASSED ${passed}   FAILED ${failures.length}`);
if (failures.length) {
  console.log("\nFailures:");
  for (const name of failures) console.log(`  - ${name}`);
  process.exit(1);
}
console.log("All cross-language checks passed.");
