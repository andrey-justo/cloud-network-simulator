import assert from "node:assert/strict";
import { get } from "node:http";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { ARMS, createMonitor, listRuns, loadDetail, loadSnapshot, validateManifest, validateOpenInput } from "../../../src/network_simulation/web/monitor.mjs";

async function save(filename, value) {
  await mkdir(path.dirname(filename), { recursive: true });
  await writeFile(filename, JSON.stringify(value), "utf8");
}

async function fixture(t) {
  const workspace = await mkdtemp(path.join(os.tmpdir(), "network-study-monitor-"));
  const results = path.join(workspace, "results");
  const id = "pilot-static/study-test";
  const run = path.join(results, "pilot-static", "study-test");
  const candidates = ARMS.map((arm) => path.join(run, "trial-00001", arm));
  const manifest = {
    schema_version: 1, mode: "controlled_study", status: "started",
    provider: "copilot", output_directory: run, cloud: { enabled: false },
    created_at_utc: "2026-10-25T19:00:00Z", models: ["model-a", "model-b"],
    maximum_generation_requests: 6,
    schedule: [
      { scenario_id: "NET-01", model: "model-a", repetition: 1 },
      { scenario_id: "NET-01", model: "model-b", repetition: 1 },
    ],
    trials: [{
      scenario_id: "NET-01", model: "model-a", repetition: 1,
      conditions: Object.fromEntries(ARMS.map((arm, index) => [arm, {
        accepted: index === 2, structural_accepted: index === 2,
        visible_checks_passed: index === 2, generation_failed: false,
        operational_error: false, attempts: index === 0 ? 1 : 2,
        elapsed_seconds: 10 * (index + 1), cost_usd: null,
        candidates: [candidates[index]], new_security_check_failures: [],
        structural_evaluations: [{
          status: index === 2 ? "passed" : "failed",
          checks: [{ id: "required-resource", status: index === 2 ? "passed" : "failed" }],
        }],
      }])),
    }],
  };
  await save(path.join(run, "manifest.json"), manifest);
  for (const [index, candidate] of candidates.entries()) {
    await save(path.join(candidate, "validation.json"), {
      bicep: { status: index ? "passed" : "failed" },
      checkov: { status: index === 2 ? "passed" : "failed" },
      conftest: { status: index === 2 ? "passed" : "skipped" },
    });
  }
  await save(path.join(run, "calls.json"), [
    { model: "model-a", status: "generated", usage: { input_tokens: 10, output_tokens: 5 }, cost_usd: null },
    { model: "model-a", status: "generated", usage: null, cost_usd: null },
    { model: "model-a", status: "generated", usage: { input_tokens: 20, output_tokens: 10 }, cost_usd: null },
  ]);
  const state = { workspace, results, run, id, manifest, candidates, monitor: null };
  t.after(async () => {
    if (state.monitor) await state.monitor.close();
    await rm(workspace, { recursive: true, force: true });
  });
  return state;
}

test("dead runners are interrupted, not indefinitely running",async t=>{
  const f=await fixture(t);
  const exited=spawnSync(process.execPath,["-e",""]);
  assert.equal(exited.status,0);
  f.manifest.runner_pid=exited.pid;
  await save(path.join(f.run,"manifest.json"),f.manifest);
  const data=await loadSnapshot(f.results,f.id);
  assert.equal(data.status,"interrupted");
  assert.equal(data.recordedStatus,"started");
  assert.equal(data.activeJob,null);
  assert.ok(data.warnings.some(message=>message.includes("runner process is no longer present")));
  assert.equal((await listRuns(f.results))[0].status,"interrupted");
});

test("operational retry provenance stays visible with current metrics and authoritative summary",async t=>{
  const f=await fixture(t);
  f.manifest.operational_retries=[{trial_index:1,status:"running"}];
  f.manifest.summary={retryAware:true};
  await save(path.join(f.run,"checkpoint.json"),{schema_version:1,manifest:f.manifest,calls:[]});
  await save(path.join(f.run,"summary.json"),{stale:true});
  const data=await loadSnapshot(f.results,f.id);
  assert.equal(data.activeJob.retryTrialIndex,1);
  assert.ok(data.warnings.some(message=>message.includes("original failed evidence")));
  assert.equal(data.operationalRetries.length,1);
  f.monitor=await createMonitor(f.workspace,{run:f.id});
  assert.deepEqual(await (await fetch(f.monitor.url+"/api/download/summary")).json(),{retryAware:true});
});

test("recovery checkpoints keep monitor, ledger, details and downloads consistent",async t=>{
  const f=await fixture(t);
  const manifest=structuredClone(f.manifest);
  manifest.trials[0].conditions.one_shot.accepted=true;
  const calls=[{model:"model-a",status:"generated",usage:{input_tokens:99,output_tokens:1},cost_usd:null}];
  await save(path.join(f.run,"checkpoint-recovery-"+"a".repeat(32)+".json"),{schema_version:1,manifest,calls});
  const data=await loadSnapshot(f.results,f.id);
  assert.equal(data.conditions.one_shot.accepted,1);
  assert.equal(data.usage.inputTokens,99);
  assert.ok(data.warnings.some(message=>message.includes("recovery checkpoint")));
  assert.equal((await listRuns(f.results))[0].completed,1);
  const detail=await loadDetail(f.results,new URLSearchParams({run:f.id,trial:"0",arm:"one_shot"}));
  assert.equal(detail.accepted,true);
  f.monitor=await createMonitor(f.workspace,{run:f.id});
  const downloadedManifest=await (await fetch(f.monitor.url+"/api/download/manifest")).json();
  assert.equal(downloadedManifest.trials[0].conditions.one_shot.accepted,true);
  assert.deepEqual(await (await fetch(f.monitor.url+"/api/download/calls")).json(),calls);
});

test("aggregates exact progress, paired denominators, compilation and known usage", async (t) => {
  const f = await fixture(t);
  const data = await loadSnapshot(f.results, f.id);
  assert.equal(data.completed, 1);
  assert.equal(data.total, 2);
  assert.equal(data.trials.length, 3);
  assert.equal(data.generationRequests, 3);
  assert.equal(data.maximumGenerationRequests, 6);
  assert.equal(data.conditions.one_shot.compilationFailed, 1);
  assert.equal(data.conditions.blind_refinement.compilationPassed, 1);
  assert.equal(data.conditions.blind_refinement.accepted, 0);
  assert.equal(data.conditions.tool_feedback.accepted, 1);
  assert.equal(data.conditions.tool_feedback.evaluated, 1);
  assert.equal(data.conditions.tool_feedback.meanAttempts, 2);
  assert.equal(data.conditions.tool_feedback.meanElapsedSeconds, 30);
  assert.equal(data.models[1].conditions.one_shot.meanElapsedSeconds, null);
  const {byModel,byModelCondition,...usage}=data.usage;
  assert.deepEqual(usage, { knownRequests: 2, unknownRequests: 1, inputTokens: 30, outputTokens: 15, costUsd: null });
  assert.deepEqual(byModel[0], {model:"model-a",requests:3,knownRequests:2,unknownRequests:1,inputTokens:30,outputTokens:15,totalTokens:45,generationSeconds:null});
  assert.equal(byModelCondition[0].unknownRequests,1);
  assert.equal(data.summaryAvailable, false);
  assert.equal(data.cloudEnabled, false);
  assert.equal(data.activeJob.model, "model-b");
  assert.deepEqual(data.warnings, []);
  const modelA = data.scenarios[0].models.find(entry => entry.model === "model-a");
  const modelB = data.scenarios[0].models.find(entry => entry.model === "model-b");
  assert.equal(modelA.completed, 1);
  assert.equal(modelA.total, 1);
  assert.equal(modelA.conditions.tool_feedback.accepted, 1);
  assert.equal(modelA.conditions.tool_feedback.evaluated, 1);
  assert.equal(modelA.conditions.one_shot.compilationFailed, 1);
  assert.equal(modelB.completed, 0);
  assert.equal(modelB.total, 1);
  assert.equal(modelB.conditions.tool_feedback.evaluated, 0);
});

test("human review remains unassessed and never invokes the shape interpreter",async t=>{
  const f=await fixture(t);
  f.manifest.study={assessment_mode:"human_review",max_iterations:2};
  f.manifest.scenarios={"NET-01":{contract:{version:"human-review-v1"}}};
  for(const condition of Object.values(f.manifest.trials[0].conditions)) {
    condition.accepted=null;
    condition.structural_accepted=null;
    condition.requirement_assessment={status:"awaiting_human_review"};
    condition.structural_evaluations=[{status:"not_assessed",checks:[]}];
  }
  await save(path.join(f.run,"manifest.json"),f.manifest);
  const data=await loadSnapshot(f.results,f.id);
  assert.equal(data.assessmentMode,"human_review");
  assert.equal(data.conditions.one_shot.acceptanceUnknown,1);
  assert.equal(data.conditions.tool_feedback.compilationPassed,1);
  const detail=await loadDetail(f.results,new URLSearchParams({run:f.id,trial:"0",arm:"one_shot"}),()=>assert.fail("Must not invoke exact-resource interpreter"));
  assert.equal(detail.accepted,null);
  assert.match(detail.summary,/not been assessed/);
  assert.equal(detail.checks.length,0);
  assert.ok(detail.gates.some(gate=>gate.name==="Human requirement review" && gate.status==="not_assessed"));
  delete f.manifest.study;
  assert.throws(()=>validateManifest(f.manifest),/Invalid one_shot/);
});

test("usage separates unique requests from shared attribution and retains partial known tokens",async t=>{
  const f=await fixture(t);
  const conditions=f.manifest.trials[0].conditions;
  conditions.one_shot.usage_accounting={known_requests:1,unknown_requests:0,input_tokens:10,output_tokens:5};
  conditions.blind_refinement.usage_accounting={known_requests:1,unknown_requests:1,input_tokens:10,output_tokens:5};
  conditions.tool_feedback.usage_accounting={known_requests:2,unknown_requests:0,input_tokens:30,output_tokens:15};
  await save(path.join(f.run,"manifest.json"),f.manifest);
  const data=await loadSnapshot(f.results,f.id);
  assert.equal(data.usage.inputTokens,30);
  const attributed=data.usage.byModelCondition.filter(value=>value.model==="model-a");
  assert.equal(attributed.reduce((sum,value)=>sum+value.inputTokens,0),50);
  assert.equal(attributed[1].knownRequests,1);
  assert.equal(attributed[1].unknownRequests,1);
  assert.equal(attributed[1].inputTokens,10);
  assert.equal(attributed[1].meanElapsedSeconds,20);
  conditions.blind_refinement.usage_accounting.unknown_requests=0;
  await save(path.join(f.run,"manifest.json"),f.manifest);
  await assert.rejects(loadSnapshot(f.results,f.id),/Invalid workflow usage/);
});

test("cloud/IaC targets are stratified and Terraform retains original detail indices", async (t) => {
  const f=await fixture(t);
  const scenario="CASE-01--aws-terraform";
  const job={scenario_id:scenario,model:"model-a",repetition:1,target:"aws-terraform"};
  f.manifest.schedule.push(job);
  const trial=structuredClone(f.manifest.trials[0]);
  Object.assign(trial,job);
  for(const arm of ARMS) {
    const directory=path.join(f.run,"trial-00002",arm);
    trial.conditions[arm].candidates=[directory];
    await save(path.join(directory,"validation.json"),{terraform:{status:"passed"},checkov:{status:"passed",selected_check_ids:["CKV2_AWS_11"]},conftest:{status:"disabled"}});
    await save(path.join(directory,"template.json"),{resource:[]});
  }
  f.manifest.trials.push(trial);
  await save(path.join(f.run,"manifest.json"),f.manifest);
  const data=await loadSnapshot(f.results,f.id,"aws-terraform");
  assert.equal(data.target,"aws-terraform");
  assert.deepEqual(data.targets,["azure-bicep","aws-terraform"]);
  assert.equal(data.total,1);
  assert.equal(data.completed,1);
  assert.equal(data.executionTotal,3);
  assert.equal(data.executionCompleted,2);
  assert.equal(data.trials[0].trialIndex,1);
  assert.equal(data.conditions.one_shot.compilationPassed,1);
  assert.equal(data.scenarios[0].models[0].conditions.one_shot.evaluated,1);
  const detail=await loadDetail(f.results,new URLSearchParams({run:f.id,trial:"1",arm:"one_shot"}));
  assert.ok(detail.gates.some(gate=>gate.name==="Terraform validation"));
  assert.ok(detail.artifacts.some(([file])=>file==="terraform"));
  assert.ok(!detail.artifacts.some(([file])=>file==="bicep"));
  await assert.rejects(loadSnapshot(f.results,f.id,"gcp-terraform"),/Select a target/);
  f.monitor=await createMonitor(f.workspace,{run:f.id});
  const response=await fetch(f.monitor.url+"/api/state?target=aws-terraform");
  assert.equal(response.status,200);
  assert.equal((await response.json()).target,"aws-terraform");
  assert.equal((await f.monitor.snapshot()).target,"aws-terraform");
  assert.equal((await fetch(f.monitor.url+"/api/state?target=aws-terraform&target=azure-bicep")).status,400);
});

test("zero completed trials have undefined means and missing ledger remains unknown", async (t) => {
  const f = await fixture(t);
  f.manifest.trials = [];
  await save(path.join(f.run, "manifest.json"), f.manifest);
  await rm(path.join(f.run, "calls.json"));
  const data = await loadSnapshot(f.results, f.id);
  assert.equal(data.conditions.one_shot.evaluated, 0);
  assert.equal(data.conditions.one_shot.meanAttempts, null);
  assert.equal(data.generationRequests, null);
  assert.equal(data.usage.inputTokens, null);
  assert.ok(data.warnings.some((warning) => warning.includes("Call ledger unavailable")));
});

test("malformed optional artifacts are explicit warnings, not zero/success-shaped defaults", async (t) => {
  const f = await fixture(t);
  await writeFile(path.join(f.candidates[0], "validation.json"), "{", "utf8");
  await save(path.join(f.run, "calls.json"), { wrong: "shape" });
  const data = await loadSnapshot(f.results, f.id);
  assert.equal(data.conditions.one_shot.compilationUnknown, 1);
  assert.equal(data.scenarios[0].models[0].conditions.one_shot.compilationUnknown, 1);
  assert.equal(data.conditions.one_shot.compilationPassed, 0);
  assert.equal(data.generationRequests, null);
  assert.ok(data.warnings.some((warning) => warning.includes("Invalid call ledger")));
  assert.ok(data.warnings.some((warning) => warning.includes("Validation unavailable")));
});

test("unsupported/corrupt manifests and duplicate or unknown trials are rejected", async (t) => {
  const f = await fixture(t);
  for (const mutate of [
    (m) => { m.schema_version = 999; },
    (m) => { m.schedule.push(m.schedule[0]); },
    (m) => { m.trials.push(m.trials[0]); },
    (m) => { m.trials[0].model = "unknown"; },
    (m) => { m.trials[0].conditions.one_shot.accepted = "true"; },
    (m) => { m.trials[0].conditions.one_shot.elapsed_seconds = -1; },
    (m) => { m.trials[0].conditions.extra = {}; },
  ]) {
    const copy = structuredClone(f.manifest);
    mutate(copy);
    assert.throws(() => validateManifest(copy), { code: "invalid_manifest" });
  }
  await writeFile(path.join(f.run, "manifest.json"), '{"status":', "utf8");
  await assert.rejects(loadSnapshot(f.results, f.id), { code: "invalid_json" });
  const entries = await listRuns(f.results);
  assert.equal(entries[0].status, "unreadable");
  assert.match(entries[0].error, /Cannot parse/);
});

test("moving recorded Windows artifacts preserves relative candidate associations", async (t) => {
  const f = await fixture(t);
  f.manifest.output_directory = "C:\\original\\results\\study-old";
  for (const [index, arm] of ARMS.entries()) {
    f.manifest.trials[0].conditions[arm].candidates = [
      `C:\\original\\results\\study-old\\trial-00001\\${ARMS[index]}`,
    ];
  }
  await save(path.join(f.run, "manifest.json"), f.manifest);
  const data = await loadSnapshot(f.results, f.id.replaceAll("/", "\\"));
  assert.equal(data.conditions.tool_feedback.compilationPassed, 1);
  assert.deepEqual(data.warnings, []);
});

test("run inputs reject traversal, absolute paths, extra fields and invalid types", async (t) => {
  const f = await fixture(t);
  for (const run of ["../outside", "pilot/../../outside", "/tmp/outside", "C:\\outside", "\\\\host\\share", "", "pilot//run", "pilot/./run"]) {
    assert.throws(() => validateOpenInput({ run }), { code: "invalid_run" });
  }
  for (const input of [null, [], { run: 1 }, { token: "not-allowed" }]) {
    assert.throws(() => validateOpenInput(input));
  }
  f.manifest.trials[0].conditions.one_shot.candidates = [path.join(f.workspace, "outside")];
  await save(path.join(f.run, "manifest.json"), f.manifest);
  const data = await loadSnapshot(f.results, f.id);
  assert.equal(data.conditions.one_shot.compilationUnknown, 1);
  assert.ok(data.warnings.some((warning) => warning.includes("traversal")));
});

test("directory junctions cannot escape the results root", async (t) => {
  const f = await fixture(t);
  const outside = path.join(f.workspace, "outside");
  await mkdir(outside);
  await symlink(outside, path.join(f.results, "outside-link"), process.platform === "win32" ? "junction" : "dir");
  await assert.rejects(loadSnapshot(f.results, "outside-link"), { code: "outside_results" });
});

test("catalog discovers direct and grouped runs and sees new progress without restarting", async (t) => {
  const f = await fixture(t);
  const direct = path.join(f.results, "study-direct");
  await save(path.join(direct, "manifest.json"), { ...f.manifest, output_directory: direct, trials: [] });
  assert.equal((await listRuns(f.results)).length, 2);
  const monitor = f.monitor = await createMonitor(f.workspace, { run: f.id });
  assert.equal((await monitor.snapshot()).completed, 1);
  f.manifest.trials = [];
  await save(path.join(f.run, "manifest.json"), f.manifest);
  assert.equal((await monitor.snapshot()).completed, 0);
  assert.equal(monitor.selected, f.id);
});

test("HTTP serves the UI and metrics and enforces read-only, origin, size and path boundaries", async (t) => {
  const f = await fixture(t);
  const monitor = f.monitor = await createMonitor(f.workspace, { run: f.id });
  assert.match(monitor.url, /^http:\/\/127\.0\.0\.1:\d+$/);
  const page = await fetch(monitor.url);
  assert.equal(page.status, 200);
  assert.match(page.headers.get("content-security-policy"), /script-src 'self'/);
  assert.match(await page.text(), /Execution monitor/);
  assert.equal((await fetch(`${monitor.url}/app.js`)).status, 200);
  const progress = await (await fetch(`${monitor.url}/api/state`)).json();
  assert.equal(progress.completed, 1);
  const invalidHostStatus = await new Promise((resolve, reject) => {
    get(`${monitor.url}/api/state`, { headers: { Host: "untrusted.example" } }, (response) => {
      response.resume();
      response.on("end", () => resolve(response.statusCode));
    }).on("error", reject);
  });
  assert.equal(invalidHostStatus, 403);
  const select = (body, origin = monitor.url) => fetch(`${monitor.url}/api/select`, {
    method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body,
  });
  assert.equal((await select(JSON.stringify({ run: f.id }), "https://untrusted.example")).status, 403);
  assert.equal((await select("{")).status, 400);
  const valid = JSON.stringify({ run: f.id });
  assert.equal((await select(valid.padEnd(2048, " "))).status, 200);
  assert.equal((await select(valid.padEnd(2049, " "))).status, 413);
  assert.equal((await select(JSON.stringify({ run: "../../outside" }))).status, 400);
  assert.equal((await fetch(`${monitor.url}/api/execute`, { method: "POST" })).status, 404);
  assert.equal((await fetch(`${monitor.url}/api/download/env`)).status, 404);
  const download = await fetch(`${monitor.url}/api/download/manifest`);
  assert.equal(download.status, 200);
  assert.match(download.headers.get("content-disposition"), /manifest\.json/);
  assert.equal((await download.json()).schema_version, 1);
  await monitor.close();
  await monitor.close();
});

test("an empty workspace opens without creating fake executions", async (t) => {
  const f = await fixture(t);
  await rm(f.results, { recursive: true });
  const monitor = f.monitor = await createMonitor(f.workspace);
  assert.deepEqual(await monitor.listRuns(), []);
  assert.equal((await monitor.snapshot()).status, "empty");
  await save(path.join(f.run, "manifest.json"), f.manifest);
  assert.equal((await monitor.snapshot()).run, f.id);
});

test("outcome details distinguish visible passes from independent benchmark rejection", async (t) => {
  const f = await fixture(t);
  const result = f.manifest.trials[0].conditions.one_shot;
  result.visible_checks_passed = true;
  result.structural_evaluations = [{status:"failed",checks:[{id:"bounded-resource-types-and-scope",status:"failed"}]}];
  await save(path.join(f.run,"manifest.json"), f.manifest);
  await save(path.join(f.candidates[0],"validation.json"), {bicep:{status:"passed"},checkov:{status:"passed"},conftest:{status:"passed"}});
  const detail = await loadDetail(f.results, new URLSearchParams({run:f.id,trial:"0",arm:"one_shot"}));
  assert.match(detail.summary, /Compilation and enabled policy checks passed/);
  assert.match(detail.summary, /not necessarily invalid or unsafe/);
  assert.match(detail.stopping, /do not enter repair prompts/);
  assert.match(detail.stopping, /One-shot/);
  assert.equal(detail.accepted, false);
  assert.equal(detail.gates.find(g => g.name === "Independent scenario contract").status, "failed");
  assert.ok(detail.gates.slice(0,4).every(gate => gate.status === "passed"));
});

test("candidate evidence downloads and detail selectors are confined and allowlisted", async (t) => {
  const f = await fixture(t);
  await writeFile(path.join(f.candidates[0],"template.bicep"), "// recorded Bicep", "utf8");
  const monitor = f.monitor = await createMonitor(f.workspace,{run:f.id});
  const query = new URLSearchParams({run:f.id,trial:"0",arm:"one_shot",file:"bicep"});
  const download = await fetch(`${monitor.url}/api/detail/artifact?${query}`);
  assert.equal(download.status,200);
  assert.equal(await download.text(),"// recorded Bicep");
  query.set("file","../../secret");
  assert.equal((await fetch(`${monitor.url}/api/detail/artifact?${query}`)).status,400);
  query.set("trial","-1");
  assert.equal((await fetch(`${monitor.url}/api/detail?${query}`)).status,400);
  query.set("trial","999");
  assert.equal((await fetch(`${monitor.url}/api/detail?${query}`)).status,404);
  query.set("trial","0"); query.set("run","../outside");
  assert.equal((await fetch(`${monitor.url}/api/detail?${query}`)).status,400);
});
