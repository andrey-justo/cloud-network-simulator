export const CONDITION_LABELS = {one_shot:"One-shot",blind_refinement:"Blind refinement",tool_feedback:"Tool feedback"};
export const COMPARISON_METRICS = {
  accepted: {label:"Acceptance",description:"All required acceptance gates passed. Human-review runs remain unassessed.",unknown:"acceptanceUnknown"},
  compilationPassed: {label:"Compilation / validation passed",description:"Final Bicep compiled to ARM or Terraform passed schema validation for the selected target.",unknown:"compilationUnknown"},
  visiblePassed: {label:"Visible validators passed",description:"Compilation and every enabled visible policy validator passed."},
  structuralAccepted: {label:"Independent structural contract passed",description:"The final candidate met the finite scenario contract.",unknown:"structuralUnknown"},
  generationFailures: {label:"Generation failures",description:"Workflows whose final generation failed. A lower percentage is better.",lowerIsBetter:true},
  operationalErrors: {label:"Operational errors",description:"Workflows with an execution or validator operational error. A lower percentage is better.",lowerIsBetter:true},
};
const arms = Object.keys(CONDITION_LABELS);
const counts = ["evaluated","accepted","acceptanceUnknown","compilationPassed","compilationUnknown","structuralAccepted","structuralUnknown","visiblePassed","generationFailures","operationalErrors"];

function addCount(left, right) {
  if (!Number.isSafeInteger(right) || right < 0 || !Number.isSafeInteger(left + right)) throw new RangeError("Invalid or overflowing comparison count.");
  return left + right;
}

export function poolConditions(groups) {
  const completed = groups.reduce((sum, group) => addCount(sum, group.completed), 0);
  const total = groups.reduce((sum, group) => addCount(sum, group.total), 0);
  const conditions = Object.fromEntries(arms.map(arm => {
    const values = groups.map(group => group.conditions[arm]);
    const result = Object.fromEntries(counts.map(field => [field,values.reduce((sum, value) => addCount(sum,field === "acceptanceUnknown" ? value[field] ?? 0 : value[field]),0)]));
    for (const field of ["meanAttempts","meanElapsedSeconds"]) {
      const observed = values.filter(value => value.evaluated > 0);
      result[field] = result.evaluated && observed.every(value => Number.isFinite(value[field]) && value[field] >= 0)
        ? observed.reduce((sum,value) => sum + value[field] * value.evaluated, 0) / result.evaluated
        : null;
    }
    return [arm,result];
  }));
  return {completed,total,conditions};
}

function compareRates(left, right, metric) {
  const difference = BigInt(left[metric]) * BigInt(right.evaluated) - BigInt(right[metric]) * BigInt(left.evaluated);
  return difference > 0n ? 1 : difference < 0n ? -1 : 0;
}

export function rankConditions(conditions, metric) {
  const definition = COMPARISON_METRICS[metric];
  if (!definition) throw new RangeError("Unknown comparison metric.");
  const reason = arms.some(arm => !conditions[arm].evaluated)
    ? "All conditions need completed observations before ranking."
    : definition.unknown && arms.some(arm => conditions[arm][definition.unknown] > 0)
      ? "Unknown or blocked evidence could change this ranking."
      : null;
  if (reason) return {
    best:[],worst:[],reason,
    entries:Object.fromEntries(arms.map(arm => [arm,{kind:"unavailable",label:"Not ranked",arrow:"",reason}])),
  };
  const sorted = [...arms].sort((a,b) => compareRates(conditions[a],conditions[b],metric) * (definition.lowerIsBetter ? 1 : -1));
  const best = arms.filter(arm => compareRates(conditions[arm],conditions[sorted[0]],metric) === 0);
  const worst = arms.filter(arm => compareRates(conditions[arm],conditions[sorted.at(-1)],metric) === 0);
  const entries = Object.fromEntries(arms.map(arm => {
    if (best.length === arms.length) return [arm,{kind:"tie",label:"All tied",arrow:"="}];
    if (best.includes(arm)) return [arm,{kind:"best",label:best.length > 1 ? "Best (tie)" : "Best",arrow:definition.lowerIsBetter ? "\u2193" : "\u2191"}];
    if (worst.includes(arm)) return [arm,{kind:"worst",label:worst.length > 1 ? "Worst (tie)" : "Worst",arrow:definition.lowerIsBetter ? "\u2191" : "\u2193"}];
    return [arm,{kind:"middle",label:"Middle",arrow:"\u2194"}];
  }));
  return {best,worst,entries,reason:null};
}
