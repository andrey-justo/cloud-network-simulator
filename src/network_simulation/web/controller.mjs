import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { MonitorError } from "./monitor.mjs";

export function createController(workspace, python, {defaultConfig, parameters, runWorker} = {}) {
  let job = null;
  let child = null;
  let cachedOptions = null;
  const plans = new Map();
  function worker(command, input, onMessage) {
    return new Promise((resolve, reject) => {
      const process = spawn(python, ["-m", "network_simulation.ui_worker", "--workspace", workspace, command], {
        cwd: workspace, shell: false, windowsHide: true, stdio: ["pipe", "pipe", "inherit"],
      });
      if (command === "run") child = process;
      let buffer = "";
      let last = null;
      let error = null;
      process.stdout.setEncoding("utf8");
      process.stdout.on("data", data => {
        buffer += data;
        if (buffer.length > 1048576) {
          error = new MonitorError("worker_protocol", "Worker output exceeds its protocol limit.");
          process.kill();
          return;
        }
        let end;
        while ((end = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, end);
          buffer = buffer.slice(end + 1);
          if (!line.trim()) continue;
          try {
            last = JSON.parse(line);
            if (last.error) error = new MonitorError("execution_failed", last.error);
            onMessage?.(last);
          } catch (failure) {
            error = new MonitorError("worker_protocol", `Invalid worker response: ${failure.message}`);
          }
        }
      });
      process.once("error", failure => reject(new MonitorError("worker_unavailable", `Python worker could not start: ${failure.message}. Configure the project venv or launch with python -m network_simulation.main --ui.`, 503)));
      process.stdin.on("error", failure => { error = new MonitorError("worker_input", failure.message); });
      process.once("close", code => {
        if (command === "run") child = null;
        if (error) reject(error);
        else if (code !== 0) reject(new MonitorError("worker_failed", last?.message ?? `Worker exited with code ${code}. See terminal diagnostics.`));
        else if (!last) reject(new MonitorError("worker_protocol", "Worker returned no result."));
        else resolve(last);
      });
      process.stdin.end(JSON.stringify(input));
    });
  }
  const invoke = runWorker ?? worker;
  return {
    async state() {
      cachedOptions ??= invoke("options", {}).catch(error => { cachedOptions = null; throw error; });
      const options = await cachedOptions;
      return {enabled:true, ...options, parameters, defaultConfig:defaultConfig ?? options.configs.find(c => c.config.endsWith("smoke-static.yaml"))?.config ?? options.configs[0]?.config, job};
    },
    settings: input => invoke("settings", input),
    explain: input => invoke("explain", input),
    async plan(input) {
      const preview = await invoke("plan", input);
      for (const [id, plan] of plans) if (Date.now() - plan.created > 900000) plans.delete(id);
      if (plans.size >= 20) plans.delete(plans.keys().next().value);
      const id = randomUUID();
      plans.set(id, {input:structuredClone(input), digest:preview.digest, blockers:preview.execution_blockers ?? [], created:Date.now()});
      return {...preview, plan_id:id};
    },
    async start(input) {
      if (!input || Object.keys(input).some(key => !["plan_id","confirmed"].includes(key)) || input.confirmed !== true) {
        throw new MonitorError("confirmation_required", "Explicit confirmation of a previewed plan is required.", 400);
      }
      if (job?.status === "running") throw new MonitorError("already_running", "This dashboard already owns an active execution.", 409);
      const plan = plans.get(input.plan_id);
      if (!plan || Date.now() - plan.created > 900000) throw new MonitorError("plan_expired", "Preview again before starting.", 409);
      if (plan.blockers.length) throw new MonitorError("execution_not_ready", plan.blockers.join(" "), 409);
      plans.delete(input.plan_id);
      job = {id:randomUUID(), status:"running", run:null, message:null};
      const current = job;
      invoke("run", {parameters:plan.input, expected_digest:plan.digest}, message => {
        if (message.run) current.run = message.run;
        if (message.event === "finished") current.message = message.message ?? message.status;
      }).then(() => { current.status = "completed"; }, error => {
        current.status = "failed";
        current.message = error.message;
      });
      return {...current};
    },
    close() {
      if (child) child.kill();
    },
  };
}
