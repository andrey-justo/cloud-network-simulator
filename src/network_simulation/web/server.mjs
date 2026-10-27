import { createMonitor } from "./monitor.mjs";
import { createController } from "./controller.mjs";

if (Number(process.versions.node.split(".")[0]) < 22) throw new Error("The study dashboard requires Node.js 22 or newer.");

let input = "";
for await (const chunk of process.stdin) input += chunk;
const startup = JSON.parse(input);
const controller = createController(startup.workspace, startup.python, {defaultConfig:startup.parameters?.config, parameters:startup.parameters});
const monitor = await createMonitor(startup.workspace, {
  run: startup.parameters?.source_run, controller,
  onError: error => process.stderr.write(`${error.message}\n`),
});
process.stdout.write(`${JSON.stringify({url:monitor.url})}\n`);
if (startup.execute) {
  const preview = await controller.plan(startup.parameters);
  await controller.start({plan_id:preview.plan_id, confirmed:true});
}
async function shutdown() {
  controller.close();
  await monitor.close();
}
process.once("SIGINT", shutdown);
process.once("SIGTERM", shutdown);
