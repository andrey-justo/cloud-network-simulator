import assert from "node:assert/strict";
import test from "node:test";
import {poolConditions,rankConditions} from "../../../src/network_simulation/web/public/comparison.mjs";

function value(evaluated, accepted, overrides={}) {
  return {
    evaluated,accepted,compilationPassed:evaluated,compilationUnknown:0,
    structuralAccepted:accepted,structuralUnknown:0,visiblePassed:evaluated,
    generationFailures:0,operationalErrors:0,meanAttempts:1,meanElapsedSeconds:10,
    ...overrides,
  };
}
function group(evaluated, accepted, overrides={}) {
  return {completed:evaluated,total:evaluated,conditions:Object.fromEntries(
    ["one_shot","blind_refinement","tool_feedback"].map(arm=>[arm,value(evaluated,accepted,overrides)]),
  )};
}

test("pools counts and denominators, weighting means rather than averaging model percentages", () => {
  const pooled = poolConditions([group(100,10),group(1,1,{meanAttempts:5,meanElapsedSeconds:110})]);
  assert.equal(pooled.completed,101);
  assert.equal(pooled.conditions.one_shot.accepted,11);
  assert.equal(pooled.conditions.one_shot.evaluated,101);
  assert.equal(pooled.conditions.one_shot.meanAttempts,105/101);
  assert.equal(pooled.conditions.one_shot.meanElapsedSeconds,1110/101);
});

test("empty selections and incomplete evidence do not fabricate a winner", () => {
  const empty = poolConditions([]);
  assert.equal(empty.completed,0);
  assert.equal(empty.conditions.one_shot.meanElapsedSeconds,null);
  assert.equal(rankConditions(empty.conditions,"accepted").best.length,0);
  const groups = [group(5,4)];
  groups[0].conditions.one_shot.compilationUnknown=1;
  assert.match(rankConditions(poolConditions(groups).conditions,"compilationPassed").reason,/Unknown/);
  groups[0].conditions.one_shot.structuralUnknown=1;
  assert.match(rankConditions(poolConditions(groups).conditions,"structuralAccepted").reason,/Unknown/);
});

test("pending human assessments cannot become zero percent winners",()=>{
  const pooled=poolConditions([group(5,0,{acceptanceUnknown:5,structuralUnknown:5})]);
  assert.equal(pooled.conditions.one_shot.acceptanceUnknown,5);
  assert.equal(rankConditions(pooled.conditions,"accepted").best.length,0);
  assert.match(rankConditions(pooled.conditions,"accepted").reason,/Unknown/);
  assert.equal(rankConditions(pooled.conditions,"compilationPassed").entries.one_shot.kind,"tie");
});

test("higher pass rates are best and exact ratio ties are explicit", () => {
  const conditions = {one_shot:value(3,1),blind_refinement:value(6,2),tool_feedback:value(6,4)};
  const ranks = rankConditions(conditions,"accepted");
  assert.deepEqual(ranks.best,["tool_feedback"]);
  assert.deepEqual(ranks.worst,["one_shot","blind_refinement"]);
  assert.equal(ranks.entries.tool_feedback.arrow,"\u2191");
  assert.equal(ranks.entries.one_shot.label,"Worst (tie)");
  assert.equal(ranks.entries.blind_refinement.kind,"worst");
});

test("all ties are neutral, including all-zero failures", () => {
  const conditions = {one_shot:value(4,2),blind_refinement:value(6,3),tool_feedback:value(8,4)};
  for (const metric of ["accepted","generationFailures","operationalErrors"]) {
    const ranks = rankConditions(conditions,metric);
    assert.ok(Object.values(ranks.entries).every(entry=>entry.kind==="tie" && entry.arrow==="="));
  }
});

test("two equal leaders are both labeled best without a tie breaker", () => {
  const conditions = {one_shot:value(5,2),blind_refinement:value(5,4),tool_feedback:value(5,4)};
  const ranks = rankConditions(conditions,"accepted");
  assert.deepEqual(ranks.best,["blind_refinement","tool_feedback"]);
  assert.equal(ranks.entries.blind_refinement.label,"Best (tie)");
  assert.equal(ranks.entries.tool_feedback.label,"Best (tie)");
});

test("lower failure rates use green/down for best and red/up for worst", () => {
  const conditions = {
    one_shot:value(10,5,{operationalErrors:1}),
    blind_refinement:value(10,5,{operationalErrors:0}),
    tool_feedback:value(10,5,{operationalErrors:2}),
  };
  const ranks = rankConditions(conditions,"operationalErrors");
  assert.equal(ranks.entries.blind_refinement.kind,"best");
  assert.equal(ranks.entries.blind_refinement.arrow,"\u2193");
  assert.equal(ranks.entries.tool_feedback.kind,"worst");
  assert.equal(ranks.entries.tool_feedback.arrow,"\u2191");
  assert.equal(ranks.entries.one_shot.kind,"middle");
});

test("ties are not manufactured by rounded display percentages", () => {
  const conditions = {one_shot:value(3000,1),blind_refinement:value(4000,1),tool_feedback:value(1,0)};
  const ranks = rankConditions(conditions,"accepted");
  assert.equal(ranks.entries.one_shot.kind,"best");
  assert.equal(ranks.entries.blind_refinement.kind,"middle");
  assert.equal(ranks.entries.tool_feedback.kind,"worst");
});

test("exact cross products preserve ranks beyond floating-point precision", () => {
  const n = Number.MAX_SAFE_INTEGER;
  const conditions = {one_shot:value(n,n-1),blind_refinement:value(n-1,n-2),tool_feedback:value(n-2,n-3)};
  const ranks = rankConditions(conditions,"accepted");
  assert.deepEqual(ranks.best,["one_shot"]);
  assert.deepEqual(ranks.worst,["tool_feedback"]);
});

test("unknown means remain unknown and invalid count inputs fail explicitly", () => {
  assert.equal(poolConditions([group(2,1,{meanElapsedSeconds:null})]).conditions.one_shot.meanElapsedSeconds,null);
  assert.throws(()=>poolConditions([group(2,1,{accepted:-1})]),RangeError);
  assert.throws(()=>rankConditions(poolConditions([group(2,1)]).conditions,"invalid"),RangeError);
});
