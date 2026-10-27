import { createServer } from "node:http";
import { readFile, readdir, realpath, stat } from "node:fs/promises";
import path from "node:path";

export const ARMS = ["one_shot", "blind_refinement", "tool_feedback"];

export class MonitorError extends Error {
  constructor(code, message, status = 422) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function requireValue(condition, message) {
  if (!condition) throw new MonitorError("invalid_manifest", message);
}

const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value) => Number.isSafeInteger(value) && value >= 0;
const number = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;
const text = (value) => typeof value === "string" && value.length > 0;
const key = (job) => JSON.stringify([job.scenario_id, job.model, job.repetition,job.target ?? "azure-bicep"]);

async function jsonFile(filename) {
  let contents;
  try {
    contents = await readFile(filename, "utf8");
  } catch (error) {
    throw new MonitorError("artifact_unavailable", `Cannot read ${path.basename(filename)} (${error.code}).`, 404);
  }
  try {
    return JSON.parse(contents);
  } catch {
    throw new MonitorError("invalid_json", `Cannot parse ${path.basename(filename)}. The writer may be updating it; retry. Persistent errors indicate corrupt data.`, 409);
  }
}

async function executionState(directory) {
  const entries = await readdir(directory);
  const candidates = entries.filter(name => name === "checkpoint.json" || /^checkpoint-recovery-[a-f0-9]{32}\.json$/.test(name));
  if (!candidates.length) {
    const filename = await confined(directory, path.join(directory, "manifest.json"));
    return {manifest:validateManifest(await jsonFile(filename)),info:await stat(filename)};
  }
  const files = await Promise.all(candidates.map(async name => {
    const filename = await confined(directory,path.join(directory,name));
    return {filename,info:await stat(filename)};
  }));
  files.sort((a,b) => b.info.mtimeMs-a.info.mtimeMs || Number(path.basename(a.filename)!=="checkpoint.json")-Number(path.basename(b.filename)!=="checkpoint.json"));
  const latest = files[0];
  const checkpoint = await jsonFile(latest.filename);
  requireValue(object(checkpoint) && checkpoint.schema_version === 1 && Array.isArray(checkpoint.calls), "Invalid execution checkpoint.");
  return {
    manifest:validateManifest(checkpoint.manifest),calls:checkpoint.calls,info:latest.info,
    recoveryUsed:path.basename(latest.filename)!=="checkpoint.json",
  };
}

async function observedStatus(manifest, directory) {
  if (manifest.status !== "started" || !Number.isSafeInteger(manifest.runner_pid) || manifest.runner_pid <= 0) return manifest.status;
  let recordedDirectory;
  try { recordedDirectory = await realpath(manifest.output_directory); }
  catch(error) {
    if (error.code === "ENOENT") return manifest.status;
    throw error;
  }
  if (recordedDirectory !== await realpath(directory)) return manifest.status;
  try { process.kill(manifest.runner_pid,0); }
  catch(error) {
    if (error.code === "ESRCH") return "interrupted";
    if (error.code !== "EPERM") throw error;
  }
  return manifest.status;
}

function relativeId(value) {
  if (!text(value) || value.length > 512 || /^[\\/]/.test(value)) {
    throw new MonitorError("invalid_run", "Provide a run directory relative to results.", 400);
  }
  const parts = value.replaceAll("\\", "/").split("/");
  if (parts.some((part) => !part || part === "." || part === ".." || /[<>:"|?*\x00-\x1f]/.test(part))) {
    throw new MonitorError("invalid_run", "Run directories cannot contain traversal or absolute paths.", 400);
  }
  return parts.join("/");
}

export function validateOpenInput(input) {
  if (!object(input) || Object.keys(input).some((field) => field !== "run")) {
    throw new MonitorError("invalid_input", "Expected an object containing only an optional run directory.", 400);
  }
  return input.run === undefined ? undefined : relativeId(input.run);
}

async function confined(root, filename) {
  const [base, target] = await Promise.all([realpath(root), realpath(filename)]);
  const relative = path.relative(base, target);
  if (relative.startsWith(`..${path.sep}`) || relative === ".." || path.isAbsolute(relative)) {
    throw new MonitorError("outside_results", "Artifact resolves outside the selected results directory.", 403);
  }
  return target;
}

export function validateManifest(manifest) {
  requireValue(object(manifest) && manifest.schema_version === 1
    && manifest.mode === "controlled_study", "Unsupported study manifest format/version.");
  requireValue(text(manifest.status) && text(manifest.output_directory)
    && Number.isFinite(Date.parse(manifest.created_at_utc)), "Missing run status, directory or creation time.");
  requireValue(Array.isArray(manifest.models) && manifest.models.length > 0
    && manifest.models.every(text) && new Set(manifest.models).size === manifest.models.length, "Invalid model list.");
  requireValue(Array.isArray(manifest.schedule) && manifest.schedule.length > 0
    && Array.isArray(manifest.trials), "Invalid schedule or completed trials.");
  requireValue(object(manifest.cloud) && typeof manifest.cloud.enabled === "boolean", "Missing cloud execution scope.");
  requireValue(text(manifest.provider), "Missing model provider.");
  const jobs = new Set();
  for (const job of manifest.schedule) {
    requireValue(object(job) && text(job.scenario_id) && manifest.models.includes(job.model)
      && count(job.repetition) && job.repetition > 0, "Invalid scheduled trial.");
    requireValue(job.target === undefined || ["azure-bicep","azure-terraform","aws-terraform"].includes(job.target),"Unsupported study target.");
    requireValue(!jobs.has(key(job)), "Duplicate scheduled trial.");
    jobs.add(key(job));
  }
  const seen = new Set();
  for (const trial of manifest.trials) {
    requireValue(object(trial) && jobs.has(key(trial)) && !seen.has(key(trial)), "Completed trials do not match the unique schedule.");
    seen.add(key(trial));
    requireValue(object(trial.conditions) && Object.keys(trial.conditions).length === ARMS.length, "Missing or unrecognized condition results.");
    for (const arm of ARMS) {
      const result = trial.conditions[arm];
      const humanReview = manifest.study?.assessment_mode === "human_review";
      requireValue(object(result)
        && ["visible_checks_passed", "generation_failed", "operational_error"]
          .every((field) => typeof result[field] === "boolean")
        && (humanReview
          ? result.accepted === null && result.structural_accepted === null && result.requirement_assessment?.status === "awaiting_human_review"
          : ["accepted","structural_accepted"].every(field => typeof result[field] === "boolean"))
        && count(result.attempts) && result.attempts > 0 && number(result.elapsed_seconds)
        && (result.cost_usd === null || number(result.cost_usd))
        && Array.isArray(result.candidates) && result.candidates.length > 0 && result.candidates.every(text)
        && Array.isArray(result.structural_evaluations) && result.structural_evaluations.every((evaluation) =>
          object(evaluation) && text(evaluation.status) && Array.isArray(evaluation.checks)
          && evaluation.checks.every((check) => object(check) && text(check.id) && text(check.status)
            && (check.reason === undefined || typeof check.reason === "string")))
        && Array.isArray(result.new_security_check_failures), `Invalid ${arm} condition result.`);
    }
  }
  return manifest;
}

async function candidateFile(run, manifest, candidate, filename) {
  // Recorded runs can be moved between machines; rebase their original artifact paths.
  const flavor = /^[A-Za-z]:[\\/]/.test(manifest.output_directory)
    || manifest.output_directory.startsWith("\\\\") ? path.win32 : path.posix;
  const relative = flavor.relative(manifest.output_directory, candidate);
  const id = relativeId(relative);
  return confined(run, path.join(run, ...id.split("/"), filename));
}

function aggregate(rows) {
  return {
    evaluated: rows.length,
    accepted: rows.filter((row) => row.accepted).length,
    acceptanceUnknown: rows.filter(row => row.accepted === null).length,
    structuralAccepted: rows.filter((row) => row.structuralAccepted).length,
    structuralUnknown: rows.filter((row) => !["passed", "failed"].includes(row.structuralStatus)).length,
    visiblePassed: rows.filter((row) => row.visiblePassed).length,
    compilationPassed: rows.filter((row) => row.compilation === "passed").length,
    compilationFailed: rows.filter((row) => row.compilation === "failed").length,
    compilationUnknown: rows.filter((row) => !["passed", "failed"].includes(row.compilation)).length,
    generationFailures: rows.filter((row) => row.generationFailed).length,
    operationalErrors: rows.filter((row) => row.operationalError).length,
    meanAttempts: rows.length ? rows.reduce((sum, row) => sum + row.attempts, 0) / rows.length : null,
    meanElapsedSeconds: rows.length ? rows.reduce((sum, row) => sum + row.elapsedSeconds, 0) / rows.length : null,
    newSecurityFailures: rows.reduce((sum, row) => sum + row.newSecurityFailures, 0),
  };
}

function observedUsage(calls) {
  const known = calls.filter(call => call.usage !== null);
  const inputTokens = known.length ? known.reduce((sum,call) => sum + call.usage.input_tokens,0) : null;
  const outputTokens = known.length ? known.reduce((sum,call) => sum + call.usage.output_tokens,0) : null;
  return {
    requests:calls.length,knownRequests:known.length,unknownRequests:calls.length-known.length,
    inputTokens,outputTokens,totalTokens:known.length ? inputTokens+outputTokens : null,
    generationSeconds:calls.length && calls.every(call => number(call.generation_seconds))
      ? calls.reduce((sum,call) => sum+call.generation_seconds,0) : null,
  };
}

function attributedUsage(conditions) {
  const values = conditions.map(condition => {
    const usage = condition.usage_accounting;
    if (usage !== undefined) {
      requireValue(object(usage) && count(usage.known_requests) && count(usage.unknown_requests)
        && usage.known_requests+usage.unknown_requests === condition.attempts
        && (usage.known_requests ? count(usage.input_tokens) && count(usage.output_tokens)
          : usage.input_tokens === null && usage.output_tokens === null), "Invalid workflow usage accounting.");
      return usage;
    }
    return {
      known_requests:condition.usage ? condition.attempts : 0,
      unknown_requests:condition.usage ? 0 : condition.attempts,
      input_tokens:condition.usage?.input_tokens ?? null,output_tokens:condition.usage?.output_tokens ?? null,
    };
  });
  const knownRequests = values.reduce((sum,value) => sum+value.known_requests,0);
  const inputTokens = knownRequests ? values.reduce((sum,value) => sum+(value.input_tokens ?? 0),0) : null;
  const outputTokens = knownRequests ? values.reduce((sum,value) => sum+(value.output_tokens ?? 0),0) : null;
  return {
    workflows:conditions.length,knownRequests,
    unknownRequests:values.reduce((sum,value) => sum+value.unknown_requests,0),
    inputTokens,outputTokens,totalTokens:knownRequests ? inputTokens+outputTokens : null,
    meanElapsedSeconds:conditions.length ? conditions.reduce((sum,value) => sum+value.elapsed_seconds,0)/conditions.length : null,
  };
}

export async function loadSnapshot(results, id, target) {
  const runId = relativeId(id);
  const run = await confined(results, path.join(results, ...runId.split("/")));
  const saved = await executionState(run);
  const {manifest,info} = saved;
  const targets = [...new Set(manifest.schedule.map(job => job.target ?? "azure-bicep"))];
  const selectedTarget = target ?? targets[0];
  if (!targets.includes(selectedTarget)) throw new MonitorError("invalid_target","Select a target present in this execution.",400);
  const scopedTrials = manifest.trials.filter(trial => (trial.target ?? "azure-bicep") === selectedTarget);
  const scopedSchedule = manifest.schedule.filter(job => (job.target ?? "azure-bicep") === selectedTarget);
  const warnings = [];
  const status = await observedStatus(manifest,run);
  const operationalRetries = manifest.operational_retries ?? [];
  requireValue(Array.isArray(operationalRetries) && operationalRetries.every(event =>
    object(event) && count(event.trial_index) && event.trial_index > 0 && text(event.status)),
  "Invalid operational retry history.");
  if (operationalRetries.length) warnings.push(
    `${operationalRetries.length} explicitly authorized operational retry attempt(s). Current scenario metrics use replacement results; original failed evidence and its usage remain in the audit and unique execution totals. No quality/policy-based retries are implied.`,
  );
  if (status === "interrupted") warnings.push("The recorded runner process is no longer present. This execution stopped before completion; resume from its checkpoint instead of starting over.");
  if (saved.recoveryUsed) warnings.push("Using a complete recovery checkpoint because Windows blocked the canonical checkpoint replacement. Completed evidence and usage are preserved.");
  if (manifest.resume_history?.length) {
    warnings.push("Resumed execution: incomplete paired trials were archived and restarted. Known abandoned calls remain in usage accounting; uncheckpointed interrupted wall time is unavailable. Review interruption history before pooling results.");
  }
  if (manifest.unknown_interrupted_requests > 0) {
    warnings.push(`${manifest.unknown_interrupted_requests} potentially interrupted requests have unknown invocation/outcome and usage; the saved call ledger cannot account for them.`);
  }
  const validationCache = new Map();
  const rows = [];
  for (const [trialIndex, trial] of manifest.trials.entries()) {
    if ((trial.target ?? "azure-bicep") !== selectedTarget) continue;
    for (const arm of ARMS) {
      const condition = trial.conditions[arm];
      const candidate = condition.candidates.at(-1);
      if (!validationCache.has(candidate)) {
        validationCache.set(candidate, (async () => {
          try {
            const file = await candidateFile(run, manifest, candidate, "validation.json");
            const data = await jsonFile(file);
            requireValue(object(data) && object(data.bicep ?? data.terraform) && text((data.bicep ?? data.terraform).status), "Invalid validation report.");
            return data;
          } catch (error) {
            warnings.push(`Validation unavailable for a final candidate: ${error.message}`);
            return null;
          }
        })());
      }
      const validation = await validationCache.get(candidate);
      const finalStructure = condition.structural_evaluations.at(-1);
      rows.push({
        trialIndex, scenario: trial.scenario_id, model: trial.model, repetition: trial.repetition, arm,
        explanation: outcomeSummary(condition, manifest.cloud.enabled),
        accepted: condition.accepted, structuralAccepted: condition.structural_accepted,
        structuralStatus: finalStructure?.status ?? "unknown",
        visiblePassed: condition.visible_checks_passed, generationFailed: condition.generation_failed,
        operationalError: condition.operational_error, attempts: condition.attempts,
        elapsedSeconds: condition.elapsed_seconds, newSecurityFailures: condition.new_security_check_failures.length,
        compilation: (validation?.bicep ?? validation?.terraform)?.status ?? "unknown",
        checkov: validation?.checkov?.status ?? "unknown",
        conftest: validation?.conftest?.status ?? "unknown",
        failures: Array.isArray(finalStructure?.checks)
          ? finalStructure.checks.filter((check) => check.status !== "passed")
            .map((check) => `${check.id}: ${check.status}${check.reason || check.error ? ` - ${check.reason || check.error}` : ""}`) : [],
      });
    }
  }
  let calls = null;
  try {
    calls = saved.calls ?? await jsonFile(await confined(run, path.join(run, "calls.json")));
    requireValue(Array.isArray(calls) && calls.every((call) => object(call)
      && text(call.model) && text(call.status)
      && (call.usage === null || (object(call.usage) && count(call.usage.input_tokens) && count(call.usage.output_tokens)))),
    "Invalid call ledger.");
  } catch (error) {
    calls = null;
    warnings.push(`Call ledger unavailable: ${error.message}`);
  }
  const knownUsage = calls?.filter((call) => call.usage !== null) ?? [];
  const scenarioIds = [...new Set(scopedSchedule.map((job) => job.scenario_id))].sort();
  const active = status === "started";
  const completedJobs = new Set(manifest.trials.map(key));
  const retryIndex = active ? operationalRetries.findLast(event => event.status === "running")?.trial_index : null;
  const retryJob = retryIndex ? manifest.schedule[retryIndex - 1] : null;
  const nextJob = active ? retryJob ?? scopedSchedule.find((job) => !completedJobs.has(key(job))) : null;
  let summaryAvailable = false;
  try {
    await confined(run, path.join(run, "summary.json"));
    summaryAvailable = true;
  } catch (error) {
    if (error.code !== "ENOENT") warnings.push(`Summary unavailable: ${error.message}`);
  }
  return {
    run: runId, status, recordedStatus:manifest.status, provider: manifest.provider,
    operationalRetries,
    target:selectedTarget,targets,executionCompleted:manifest.trials.length,executionTotal:manifest.schedule.length,
    securityCheckIds:manifest.target_security_checks?.[selectedTarget] ?? [],
    checkovEnabled:typeof manifest.validation?.run_checkov === "boolean" ? manifest.validation.run_checkov : null,
    cloudEnabled: manifest.cloud.enabled,
    assessmentMode:manifest.study?.assessment_mode ?? "finite_contract",
    createdAt: manifest.created_at_utc, completedAt: manifest.completed_at_utc ?? null,
    updatedAt: info.mtime.toISOString(), observedAt: new Date().toISOString(),
    completed: scopedTrials.length, total: scopedSchedule.length,
    generationRequests: calls?.length ?? null,
    maximumGenerationRequests: manifest.maximum_generation_requests ?? manifest.maximum_physical_model_calls ?? null,
    summaryAvailable, activeJob: nextJob ? {
      scenario: nextJob.scenario_id, model: nextJob.model, repetition: nextJob.repetition,
      retryTrialIndex:retryIndex ?? null,
    } : null,
    usage: {
      byModel:manifest.models.map(model => ({model,...(calls ? observedUsage(calls.filter(call => call.model === model))
        : {requests:null,knownRequests:null,unknownRequests:null,inputTokens:null,outputTokens:null,totalTokens:null,generationSeconds:null})})),
      byModelCondition:manifest.models.flatMap(model => ARMS.map(arm => ({
        model,arm,...attributedUsage(manifest.trials.filter(trial => trial.model === model).map(trial => trial.conditions[arm])),
      }))),
      knownRequests: knownUsage.length,
      unknownRequests: calls ? calls.length - knownUsage.length : null,
      inputTokens: knownUsage.length ? knownUsage.reduce((sum, call) => sum + call.usage.input_tokens, 0) : null,
      outputTokens: knownUsage.length ? knownUsage.reduce((sum, call) => sum + call.usage.output_tokens, 0) : null,
      costUsd: calls?.length && calls.every((call) => number(call.cost_usd))
        ? calls.reduce((sum, call) => sum + call.cost_usd, 0) : null,
    },
    conditions: Object.fromEntries(ARMS.map((arm) => [arm, aggregate(rows.filter((row) => row.arm === arm))])),
    models: manifest.models.map((model) => ({
      model,
      completed: scopedTrials.filter((trial) => trial.model === model).length,
      total: scopedSchedule.filter((job) => job.model === model).length,
      conditions: Object.fromEntries(ARMS.map((arm) => [arm, aggregate(rows.filter((row) => row.model === model && row.arm === arm))])),
    })),
    scenarios: scenarioIds.map((scenario) => ({
      scenario, completed: scopedTrials.filter((trial) => trial.scenario_id === scenario).length,
      total: scopedSchedule.filter((job) => job.scenario_id === scenario).length,
      feedback: aggregate(rows.filter((row) => row.scenario === scenario && row.arm === "tool_feedback")),
      models: manifest.models.map((model) => ({
        model,
        completed: scopedTrials.filter(trial => trial.scenario_id === scenario && trial.model === model).length,
        total: scopedSchedule.filter(job => job.scenario_id === scenario && job.model === model).length,
        conditions: Object.fromEntries(ARMS.map(arm => [arm, aggregate(rows.filter(row =>
          row.scenario === scenario && row.model === model && row.arm === arm))])),
      })),
    })),
    warnings: [...new Set(warnings)], trials: rows,
  };
}

export async function listRuns(results) {
  let groups;
  try {
    groups = await readdir(results, { withFileTypes: true });
  } catch (error) {
    if (error.code === "ENOENT") return [];
    throw error;
  }
  const runs = [];
  async function addRun(id, directory) {
    try {
      const {manifest,info} = await executionState(directory);
      runs.push({ run: id, status: await observedStatus(manifest,directory), completed: manifest.trials.length,
        total: manifest.schedule.length, updatedAt: info.mtime.toISOString() });
    } catch (error) {
      runs.push({ run: id, status: "unreadable", error: error.message, updatedAt: null });
    }
  }
  for (const group of groups.filter((entry) => entry.isDirectory())) {
    const groupPath = await confined(results, path.join(results, group.name));
    if (group.name.startsWith("study-")) {
      await addRun(group.name, groupPath);
      continue;
    }
    for (const folder of await readdir(groupPath, { withFileTypes: true })) {
      if (!folder.isDirectory() || !folder.name.startsWith("study-")) continue;
      const id = `${group.name}/${folder.name}`;
      await addRun(id, path.join(groupPath, folder.name));
    }
  }
  return runs.sort((a, b) => (b.updatedAt ?? "").localeCompare(a.updatedAt ?? ""));
}

export function outcomeSummary(condition, cloudEnabled) {
  if (condition.accepted === null) return "Requirement satisfaction has not been assessed. Compilation/policy results are separate observations, not a human-quality verdict.";
  if (condition.accepted) return cloudEnabled
    ? "All recorded acceptance gates passed for this workflow."
    : "All enabled visible validators and the finite structural contract passed. Deployment and runtime behavior remain unverified.";
  if (condition.generation_failed) return "Generation failed; there is no accepted complete candidate.";
  if (condition.operational_error) return "An execution or validation operation failed. This is an operational failure, not simply a scenario mismatch.";
  if (!condition.visible_checks_passed) return "Compilation or an enabled policy validator did not pass.";
  if (!condition.structural_accepted) return "Compilation and enabled policy checks passed, but the independent scenario contract did not. This is a benchmark mismatch, not necessarily invalid or unsafe infrastructure.";
  return "Static checks passed, but a required deployment/runtime acceptance gate did not pass.";
}

async function detailSource(results, parameters) {
  const allowed = new Set(["run", "trial", "arm", "file"]);
  if ([...parameters.keys()].some(key => !allowed.has(key) || parameters.getAll(key).length !== 1)) {
    throw new MonitorError("invalid_detail", "Unrecognized or repeated detail parameters.", 400);
  }
  const runId = relativeId(parameters.get("run"));
  const index = parameters.get("trial");
  const arm = parameters.get("arm");
  if (!/^(0|[1-9]\d*)$/.test(index ?? "") || !Number.isSafeInteger(Number(index)) || !ARMS.includes(arm)) {
    throw new MonitorError("invalid_detail", "Choose a saved trial index and condition.", 400);
  }
  const directory = await confined(results, path.join(results, ...runId.split("/")));
  const {manifest} = await executionState(directory);
  const trial = manifest.trials[Number(index)];
  if (!trial) throw new MonitorError("missing_trial", "This paired trial has not been saved.", 404);
  const condition = trial.conditions[arm];
  return {runId, directory, manifest, trial, arm, condition, candidate:condition.candidates.at(-1)};
}

export async function loadDetail(results, parameters, explain) {
  const source = await detailSource(results, parameters);
  const {manifest, trial, condition, arm, directory, candidate} = source;
  const warnings = [];
  async function artifact(name) {
    try { return await jsonFile(await candidateFile(directory, manifest, candidate, name)); }
    catch (error) { warnings.push(`${name}: ${error.message}`); return null; }
  }
  const [validation, template] = await Promise.all([artifact("validation.json"), artifact("template.json")]);
  const evaluation = condition.structural_evaluations.at(-1) ?? {status:"unknown",checks:[]};
  const contract = manifest.scenarios?.[trial.scenario_id]?.contract;
  const evidence = {evaluation, template, contract, evaluator_sha256:contract?.version === "network-intents-v1" ? manifest.target_implementation_sha256?.["network_cases.py"] : manifest.acceptance_implementation_sha256};
  const terraform = trial.target?.endsWith("-terraform") === true;
  const compilation = terraform ? validation?.terraform : validation?.bicep;
  let interpretation = {checks:evaluation.checks.map(check => ({
    ...check, title:check.id, explanation:"See the saved contract and structural report.", evidence:[check.error || check.reason].filter(Boolean),
  })), warnings:[]};
  if (condition.accepted === null) interpretation = {checks:[],warnings:["Human requirement satisfaction is unassessed. No resource-shape interpretation is applied."]};
  else if (explain && evidence.contract) interpretation = await explain(evidence);
  else warnings.push("Detailed resource interpretation is unavailable. Use the project Python environment and the saved scenario contract; recorded results are unchanged.");
  const limit = arm === "one_shot" ? 1 : manifest.study?.max_iterations;
  const stopped = arm === "one_shot" ? "One-shot always uses one generation and does not refine."
    : condition.generation_failed ? "Generation failed, so refinement stopped."
    : condition.visible_checks_passed ? "Refinement stopped when the enabled visible validators passed."
    : condition.attempts >= limit ? "The attempt budget was reached without a visible-validator pass."
    : "Inspect the recorded generation and validator evidence for the stopping cause.";
  const policyResults = validation?.checkov?.results;
  if (policyResults !== undefined && !Array.isArray(policyResults)) warnings.push("Checkov result details have an invalid shape; inspect the downloaded validator report.");
  const policyFailures = (Array.isArray(policyResults) ? policyResults : [])
    .filter(check => object(check) && check.result === "failed")
    .map(check => `${check.check_id}: ${check.check_name}${check.resource ? ` / ${check.resource}` : ""}`);
  if (validation?.checkov?.baseline_error) policyFailures.push(validation.checkov.baseline_error);
  if (compilation?.status !== "passed") {
    if (compilation?.stderr) policyFailures.push(compilation.stderr);
    if (compilation?.diagnostics?.length) policyFailures.push(JSON.stringify(compilation.diagnostics,null,2));
  }
  if (validation?.conftest?.status !== "passed" && validation?.conftest?.status !== "disabled") {
    if (validation?.conftest?.stdout) policyFailures.push(`Conftest diagnostics: ${validation.conftest.stdout}`);
    if (validation?.conftest?.stderr) policyFailures.push(validation.conftest.stderr);
  }
  const gates = [
    {name:"Generation",status:condition.generation_failed ? "failed" : "passed",description:"Requires a complete model response."},
    {name:terraform ? "Terraform validation" : "Bicep compilation",status:compilation?.status ?? "unknown",description:terraform ? "terraform validate against pinned provider schemas; no plan/apply or runtime test." : "Syntax/type compilation to ARM; not a deployment test."},
    {name:"Checkov",status:validation?.checkov?.status ?? "unknown",description:validation?.checkov?.selected_check_ids?.length ? `Scoped network baseline: ${validation.checkov.selected_check_ids.join(", ")}. Not the complete Checkov policy universe or a full security assurance.` : "The enabled static security/policy checks, not all possible security requirements."},
    {name:"Conftest",status:validation?.conftest?.status ?? "unknown",description:"The configured project policy rules."},
    {name:condition.accepted === null ? "Human requirement review" : "Independent scenario contract",status:evaluation.status,description:condition.accepted === null ? "Awaiting independent review against the original human-written requirements. No exact-resource oracle was used." : "Exact required resources/properties and global benchmark restrictions. This is evaluated after generation/refinement."},
  ];
  if (manifest.cloud.enabled) for (const name of ["deployment", "runtime"]) gates.push({
    name, status:condition.cloud?.[`${name}_status`] ?? "unknown", description:"Recorded cloud evaluation, separate from static checks.",
  });
  return {
    run:source.runId, scenario:trial.scenario_id, model:trial.model, repetition:trial.repetition, arm,
    accepted:condition.accepted, summary:outcomeSummary(condition, manifest.cloud.enabled),
    attempts:condition.attempts, attemptLimit:limit, gates, checks:interpretation.checks,
    artifacts:[...(terraform ? [["terraform","Terraform HCL"],["providers","Pinned provider configuration"],["lock","Provider lock"],["arm","Parsed Terraform configuration"]] : [["bicep","Bicep candidate"],["arm","Compiled ARM"]]),["validation","Validator report"],["structure",condition.accepted === null ? "Requirement assessment status" : "Structural report"],["generation","Generation metadata"],["contract",condition.accepted === null ? "Assessment metadata (not an answer key)" : "Scenario contract"]],
    stopping:`${stopped} ${condition.accepted === null ? "Requirement satisfaction is unassessed and does not control stopping." : "Independent structural diagnostics are held out: they do not enter repair prompts or control stopping."}`,
    warnings:[...warnings,...interpretation.warnings,...(interpretation.evaluationError ? [interpretation.evaluationError] : [])],
    policyFailures,
    sharedInitial:"All three conditions in this paired trial share the initial candidate; repeated appearances are not independent generations.",
  };
}

export async function createMonitor(workspace, { run, controller = null, onError = () => {} } = {}) {
  const results = path.join(workspace, "results");
  const assets = new Map(await Promise.all([
    ["/", "index.html", "text/html; charset=utf-8"],
    ["/app.js", "app.js", "text/javascript; charset=utf-8"],
    ["/comparison.mjs", "comparison.mjs", "text/javascript; charset=utf-8"],
    ["/styles.css", "styles.css", "text/css; charset=utf-8"],
  ].map(async ([route, filename, type]) => [route, { type, body: await readFile(new URL(`./public/${filename}`, import.meta.url)) }])));
  let selected = run === undefined ? (await listRuns(results))[0]?.run : relativeId(run);
  let selectedTarget;
  if (selected) await loadSnapshot(results, selected);
  let closePromise;
  const monitor = {
    get selected() { return selected ?? null; },
    url: null,
    listRuns: () => listRuns(results),
    snapshot: async (target) => {
      selected ??= (await listRuns(results))[0]?.run;
      if (selected) {
        const result = await loadSnapshot(results,selected,target ?? selectedTarget);
        selectedTarget = result.target;
        return result;
      }
      return {
        run: null, status: "empty", message: "No saved controlled-study executions found under results.",
      };
    },
    async select(input) {
      const candidate = validateOpenInput(input);
      if (candidate === undefined) throw new MonitorError("invalid_input", "A run directory is required.", 400);
      await loadSnapshot(results, candidate);
      selected = candidate;
      selectedTarget = undefined;
    },
    close: () => closePromise ??= new Promise((resolve, reject) => {
      controller?.close();
      server.close((error) => error ? reject(error) : resolve());
      server.closeIdleConnections();
    }),
  };
  const server = createServer(async (request, response) => {
    const send = (status, body, type = "application/json; charset=utf-8", headers = {}) => {
      response.writeHead(status, {
        "Content-Type": type, "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'; form-action 'none'",
        ...headers,
      });
      response.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
    };
    try {
      if (request.headers.host !== new URL(monitor.url).host) {
        throw new MonitorError("invalid_host", "Unexpected request host.", 403);
      }
      const url = new URL(request.url, monitor.url);
      if (request.method === "GET" && assets.has(url.pathname)) {
        const asset = assets.get(url.pathname);
        send(200, asset.body, asset.type);
      } else if (request.method === "GET" && url.pathname === "/favicon.ico") {
        send(204, "", "image/x-icon");
      } else if (request.method === "GET" && url.pathname === "/api/runs") {
        send(200, await monitor.listRuns());
      } else if (request.method === "GET" && url.pathname === "/api/state") {
        if ([...url.searchParams.keys()].some(key => key !== "target") || url.searchParams.getAll("target").length > 1) throw new MonitorError("invalid_target","Only one target query parameter is permitted.",400);
        send(200, await monitor.snapshot(url.searchParams.get("target") ?? undefined));
      } else if (request.method === "GET" && url.pathname === "/api/control") {
        send(200, controller ? await controller.state() : { enabled: false });
      } else if (request.method === "GET" && url.pathname === "/api/detail") {
        send(200, await loadDetail(results, url.searchParams, controller?.explain));
      } else if (request.method === "GET" && url.pathname === "/api/detail/artifact") {
        const source = await detailSource(results, url.searchParams);
        const files = {validation:"validation.json",structure:"structural-acceptance.json",generation:"generation.json",bicep:"template.bicep",terraform:"main.tf",providers:"providers.tf",lock:".terraform.lock.hcl",arm:"template.json",contract:"contract.json"};
        const filename = files[url.searchParams.get("file")];
        if (!filename || !Object.hasOwn(files, url.searchParams.get("file"))) throw new MonitorError("invalid_artifact", "Choose a permitted candidate artifact.", 400);
        if (url.searchParams.get("file") === "contract") {
          const contract = source.manifest.scenarios?.[source.trial.scenario_id]?.contract;
          if (!object(contract)) throw new MonitorError("missing_contract", "The saved scenario contract is unavailable.", 404);
          send(200, contract, "application/json", {"Content-Disposition":'attachment; filename="contract.json"'});
          return;
        }
        const file = await candidateFile(source.directory, source.manifest, source.candidate, filename);
        send(200, await readFile(file), filename.endsWith(".json") ? "application/json" : "text/plain", {"Content-Disposition":`attachment; filename="${filename}"`});
      } else if (request.method === "POST" && ["/api/select", "/api/settings", "/api/plan", "/api/start", "/api/shutdown"].includes(url.pathname)) {
        if (request.headers.origin !== monitor.url || request.headers["content-type"]?.split(";")[0] !== "application/json") {
          throw new MonitorError("invalid_origin", "Selection requires same-origin JSON.", 403);
        }
        const limit = url.pathname === "/api/select" ? 2048 : 16384;
        let size = 0;
        const chunks = [];
        for await (const chunk of request) {
          size += chunk.length;
          if (size <= limit) chunks.push(chunk);
        }
        if (size > limit) throw new MonitorError("input_too_large", `Input exceeds ${limit} bytes.`, 413);
        let input;
        try { input = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
        catch { throw new MonitorError("invalid_input", "Selection must be valid JSON.", 400); }
        if (url.pathname === "/api/select") {
          await monitor.select(input);
          send(200, { run: selected });
        } else {
          if (!controller) throw new MonitorError("read_only", "Launch with --ui to enable execution controls.", 403);
          if (url.pathname === "/api/shutdown") {
            if (!object(input) || Object.keys(input).length) throw new MonitorError("invalid_input", "Shutdown expects an empty object.", 400);
            send(200, {status:"closing"});
            setImmediate(() => monitor.close().catch(onError));
          } else {
            const operation = url.pathname.slice(5);
            send(200, await controller[operation](input));
          }
        }
      } else if (request.method === "GET" && /^\/api\/download\/(manifest|calls|summary)$/.test(url.pathname)) {
        if (!selected) throw new MonitorError("no_run", "Select an execution first.", 404);
        const name = `${url.pathname.split("/").at(-1)}.json`;
        const directory = await confined(results, path.join(results, ...selected.split("/")));
        const saved = await executionState(directory);
        const data = name === "manifest.json" ? saved.manifest
          : name === "calls.json" && saved.calls ? saved.calls
          : name === "summary.json" && object(saved.manifest.summary) ? saved.manifest.summary
          : await jsonFile(await confined(directory, path.join(directory, name)));
        send(200, data, "application/json; charset=utf-8", { "Content-Disposition": `attachment; filename="${name}"` });
      } else {
        throw new MonitorError("not_found", "Unknown monitor endpoint.", 404);
      }
    } catch (error) {
      send(error instanceof MonitorError ? error.status : error.code === "ENOENT" ? 404 : 500, {
        error: error.code ?? "monitor_error",
        message: error instanceof MonitorError ? error.message : `Cannot read execution artifacts (${error.code ?? "unexpected error"}).`,
      });
      await onError(error);
    }
  });
  server.requestTimeout = 15000;
  server.headersTimeout = 15000;
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  monitor.url = `http://127.0.0.1:${server.address().port}`;
  return monitor;
}
