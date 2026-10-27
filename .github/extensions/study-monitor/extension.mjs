import { createCanvas, CanvasError, joinSession } from "@github/copilot-sdk/extension";
import { fileURLToPath } from "node:url";
import { createMonitor, MonitorError, validateOpenInput } from "../../../src/network_simulation/web/monitor.mjs";
import { createController } from "../../../src/network_simulation/web/controller.mjs";
import path from "node:path";

const workspace = fileURLToPath(new URL("../../../", import.meta.url));
const instances = new Map();
const runSchema = {
  type: "object",
  properties: { run: { type: "string", minLength: 1, maxLength: 512, description: "Initial run directory relative to results. Reopening retains selection; use select_run to change it." } },
  additionalProperties: false,
};

async function perform(operation) {
  try {
    return await operation();
  } catch (error) {
    throw new CanvasError(
      error instanceof MonitorError ? error.code : "monitor_error",
      error.message,
    );
  }
}

function instance(ctx) {
  const monitor = instances.get(ctx.instanceId);
  if (!monitor) throw new CanvasError("not_open", "Open the study monitor first.");
  return monitor;
}

const canvas = createCanvas({
  id: "cloud-network-study-monitor",
  displayName: "Network IaC Study Monitor",
  description: "Monitor IaC results and explicitly launch, resume or fully rerun static experiments with previewed parameters.",
  inputSchema: runSchema,
  actions: [
    {
      name: "list_runs",
      description: "List saved controlled-study executions and their recorded status.",
      handler: (ctx) => perform(() => instance(ctx).listRuns()),
    },
    {
      name: "get_progress",
      description: "Refresh and return compact progress, per-condition metrics and scenario coverage for the selected execution.",
      handler: (ctx) => perform(async () => {
        const { trials, ...progress } = await instance(ctx).snapshot();
        return progress;
      }),
    },
    {
      name: "select_run",
      description: "Select another saved execution by its directory relative to results.",
      inputSchema: { ...runSchema, required: ["run"] },
      handler: (ctx) => perform(async () => {
        await instance(ctx).select(ctx.input);
        return { run: instance(ctx).selected };
      }),
    },
  ],
  open: (ctx) => perform(async () => {
    const run = validateOpenInput(ctx.input);
    let monitor = instances.get(ctx.instanceId);
    if (!monitor) {
      monitor = await createMonitor(workspace, {
        run,
        controller: createController(workspace, path.join(workspace, ".venv", process.platform === "win32" ? "Scripts" : "bin", process.platform === "win32" ? "python.exe" : "python")),
        onError: (error) => session.log(error.message, { level: "error" }),
      });
      instances.set(ctx.instanceId, monitor);
    }
    await monitor.snapshot();
    return { url: monitor.url, title: "Network IaC Study Monitor", status: "Static study workspace" };
  }),
  onClose: async (ctx) => {
    const monitor = instances.get(ctx.instanceId);
    if (monitor) {
      await monitor.close();
      instances.delete(ctx.instanceId);
    }
  },
});

const session = await joinSession({ canvases: [canvas] });
