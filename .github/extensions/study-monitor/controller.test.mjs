import assert from "node:assert/strict";
import test from "node:test";
import { createController } from "../../../src/network_simulation/web/controller.mjs";

test("execution requires a single-use, confirmed preview and blocks double starts", async () => {
  const calls = [];
  let finish;
  const controller = createController(".", "unused", {
    runWorker: async (command, input, onMessage) => {
      calls.push({command,input});
      if (command === "options") return {configs:[{config:"configs/smoke-static.yaml"}]};
      if (command === "plan") return {digest:"frozen",total:2};
      if (command === "run") {
        onMessage({event:"started",run:"ui-runs/study-mock"});
        return new Promise(resolve => { finish = resolve; });
      }
    },
  });
  const input = {operation:"new",models:["model-a"]};
  const plan = await controller.plan(input);
  input.models.push("must-not-change-preview");
  await assert.rejects(controller.start({plan_id:plan.plan_id,confirmed:false}), {code:"confirmation_required"});
  assert.equal(calls.filter(c => c.command === "run").length, 0);
  await controller.start({plan_id:plan.plan_id,confirmed:true});
  await assert.rejects(controller.start({plan_id:plan.plan_id,confirmed:true}), {code:"already_running"});
  assert.deepEqual(calls.find(c => c.command === "run").input.parameters.models, ["model-a"]);
  assert.equal((await controller.state()).job.run, "ui-runs/study-mock");
  finish({event:"finished"});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await controller.state()).job.status, "completed");
  await assert.rejects(controller.start({plan_id:plan.plan_id,confirmed:true}), {code:"plan_expired"});
});

test("worker failures remain explicit and never look like successful execution", async () => {
  const controller = createController(".", "unused", {
    runWorker: async command => {
      if (command === "plan") return {digest:"frozen"};
      if (command === "options") return {configs:[]};
      throw Error("Authentication unavailable");
    },
  });
  const plan = await controller.plan({operation:"resume",source_run:"group/study-test"});
  await controller.start({plan_id:plan.plan_id,confirmed:true});
  await new Promise(resolve => setImmediate(resolve));
  const state = await controller.state();
  assert.equal(state.job.status, "failed");
  assert.equal(state.job.message, "Authentication unavailable");
});

test("an unimplemented requirements evaluator blocks paid execution even with confirmation", async () => {
  let runs = 0;
  const controller = createController(".", "unused", {
    runWorker: async command => {
      if (command === "plan") return {digest:"frozen",execution_blockers:["Requirements evaluator is not implemented."]};
      if (command === "options") return {configs:[]};
      if (command === "run") runs++;
    },
  });
  const plan = await controller.plan({operation:"new",config:"configs/multicloud-static.yaml"});
  await assert.rejects(controller.start({plan_id:plan.plan_id,confirmed:true}),
    {code:"execution_not_ready",message:"Requirements evaluator is not implemented."});
  assert.equal(runs, 0);
  assert.equal((await controller.state()).job, null);
});
