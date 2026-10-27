import {CONDITION_LABELS, COMPARISON_METRICS, poolConditions, rankConditions} from "./comparison.mjs";

(() => {
  const $ = (id) => document.getElementById(id);
  const labels = CONDITION_LABELS;
  const comparisonMetrics = COMPARISON_METRICS;
  const selectedComparisonModels = new Set();
  let comparisonModelsInitialized = false;
  let comparisonModelSignature = null;
  let comparisonRun = null;
  let snapshot = null;
  let busy = false;
  let failures = 0;
  let control = null;
  let planId = null;
  let followedJob = null;
  let detailKey = null;
  const expandedChecks = new Set();
  const format = (value) => value === null || value === undefined ? "Unknown" : new Intl.NumberFormat().format(value);
  const percent = (accepted, total) => total ? `${(100 * accepted / total).toFixed(1)}%` : "Not evaluated";
  const duration = (seconds) => {
    if (seconds === null || !Number.isFinite(seconds)) return "Unknown";
    if (seconds < 0) return "Clock mismatch";
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
  };
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const badge = (status) => node("span", status, `badge ${status === "passed" || status === "Accepted" ? "good" : status === "failed" || status === "Not accepted" ? "bad" : "neutral"}`);

  for (const section of document.querySelectorAll("#monitor-view > section, #dashboard > section, #dashboard > .two-column > section, #dashboard > footer")) {
    const fold = node("details",undefined,"monitor-collapse");
    fold.open = true;
    fold.hidden = section.hidden;
    const summary = node("summary");
    const heading = section.querySelector("h2") ?? node("h2",section.getAttribute("aria-label") ?? (section.matches("footer") ? "Saved evidence" : "Monitoring section"));
    section.before(fold);
    fold.append(summary,section);
    summary.append(heading);
    new MutationObserver(() => { fold.hidden = section.hidden; }).observe(section,{attributes:true,attributeFilter:["hidden"]});
  }
  for (const [id,open] of [["expand-monitor",true],["collapse-monitor",false]]) $(id).addEventListener("click",() => {
    for (const fold of document.querySelectorAll(".monitor-collapse")) fold.open = open;
  });

  async function api(endpoint, options) {
    const response = await fetch(endpoint, { cache: "no-store", ...options });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "Execution artifacts could not be read.");
    return data;
  }

  function options(id, values, allLabel, selectedValue) {
    const select = $(id);
    const selected = selectedValue ?? select.value;
    const elements = [];
    if (allLabel) {
      const option = node("option", allLabel);
      option.value = "";
      elements.push(option);
    }
    for (const { value, label } of values) {
      const option = node("option", label);
      option.value = value;
      elements.push(option);
    }
    select.replaceChildren(...elements);
    select.value = elements.some((option) => option.value === selected) ? selected : "";
  }

  function renderConditions() {
    const selectedModel = $("model-filter").value;
    const conditions = selectedModel
      ? snapshot.models.find((entry) => entry.model === selectedModel).conditions : snapshot.conditions;
    const rows = [];
    for (const [arm, value] of Object.entries(conditions)) {
      const row = node("tr");
      row.append(node("td", labels[arm], "arm-name"), node("td", value.acceptanceUnknown ? "Unassessed" : `${value.accepted} / ${value.evaluated}`));
      const rate = node("td");
      const group = node("div", undefined, "rate");
      const meter = node("meter");
      meter.min = 0;
      meter.max = Math.max(1, value.evaluated);
      meter.value = value.accepted;
      meter.setAttribute("aria-label", `${labels[arm]} acceptance: ${percent(value.accepted, value.evaluated)}`);
      if (value.acceptanceUnknown) group.append(node("span","Awaiting human review"));
      else group.append(meter, node("span", percent(value.accepted, value.evaluated)));
      rate.append(group);
      row.append(rate, node("td", `${value.compilationPassed} / ${value.evaluated}${value.compilationUnknown ? ` (${value.compilationUnknown} unknown)` : ""}`),
        node("td", value.meanAttempts === null ? "Unknown" : value.meanAttempts.toFixed(2)),
        node("td", duration(value.meanElapsedSeconds)));
      rows.push(row);
    }
    $("condition-rows").replaceChildren(...rows);
    const feedback = conditions.tool_feedback;
    const blind = conditions.blind_refinement;
    $("comparison").textContent = feedback.acceptanceUnknown || blind.acceptanceUnknown
      ? "Requirement satisfaction awaits human review. Compare compilation, visible policies, tokens and latency separately; there is no acceptance winner yet."
      : feedback.evaluated
      ? `Tool feedback minus blind refinement: ${((feedback.accepted - blind.accepted) / feedback.evaluated * 100).toFixed(1)} percentage points in completed paired trials. Preliminary, not a significance claim.`
      : "No completed paired trials to compare yet.";
  }

  function renderTrials() {
    const model = $("model-filter").value;
    const scenario = $("scenario-filter").value;
    const outcome = $("outcome-filter").value;
    const rows = snapshot.trials.filter((row) => (!model || row.model === model)
      && (!scenario || row.scenario === scenario)
      && (!outcome || (outcome === "accepted" ? row.accepted === true : outcome === "unassessed" ? row.accepted === null : row.accepted === false || row.operationalError || row.generationFailed)));
    $("row-count").textContent = `${rows.length} saved condition workflows shown. Shared initial candidates are paired, not independent observations.`;
    $("trial-rows").replaceChildren(...rows.map((value) => {
      const row = node("tr");
      row.append(node("td", `${value.scenario} / ${value.repetition}`), node("td", value.model),
        node("td", labels[value.arm]));
      for (const status of [value.compilation, value.checkov, value.conftest]) {
        const cell = node("td");
        cell.append(badge(status));
        row.append(cell);
      }
      const result = node("td");
      result.append(badge(value.accepted === null ? "Awaiting human review" : value.accepted ? "Accepted" : "Not accepted"));
      result.append(node("p", value.explanation, "micro"));
      if (value.operationalError) result.append(node("p", "Operational error", "micro"));
      if (value.failures.length) {
        const details = node("details");
        const identity = JSON.stringify([value.scenario, value.model, value.repetition, value.arm]);
        details.open = expandedChecks.has(identity);
        details.addEventListener("toggle", () => {
          if (details.open) expandedChecks.add(identity);
          else expandedChecks.delete(identity);
        });
        details.append(node("summary", `${value.failures.length} structural checks need attention`));
        const list = node("ul");
        list.append(...value.failures.map((failure) => node("li", failure.startsWith("bounded-resource-types-and-scope:")
          ? "An extra resource or explicit ARM scope failed the fixed benchmark restrictions. Explain outcome shows the exact evidence."
          : failure)));
        details.append(list);
        result.append(details);
      }
      const explain = node("button", "Explain outcome", "explain-button");
      explain.type = "button";
      const sourceRun = snapshot.run;
      explain.addEventListener("click", () => showOutcome(sourceRun, value.trialIndex, value.arm));
      result.append(explain);
      row.append(result);
      return row;
    }));
  }

  function renderComparisonModels() {
    const models = snapshot.models.map(entry => entry.model);
    if (!comparisonModelsInitialized) {
      models.forEach(model => selectedComparisonModels.add(model));
      comparisonModelsInitialized = true;
    }
    for (const model of selectedComparisonModels) if (!models.includes(model)) selectedComparisonModels.delete(model);
    const signature = JSON.stringify(models);
    if (signature !== comparisonModelSignature) {
      comparisonModelSignature = signature;
      $("comparison-model-options").replaceChildren(...models.map(model => {
        const label = node("label",undefined,"toggle model-choice");
        const checkbox = node("input");
        checkbox.type = "checkbox";
        checkbox.value = model;
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) selectedComparisonModels.add(model);
          else selectedComparisonModels.delete(model);
          renderScenarioComparison();
        });
        label.append(checkbox,node("span",model));
        return label;
      }));
    }
    for (const input of $("comparison-model-options").querySelectorAll("input")) input.checked = selectedComparisonModels.has(input.value);
  }

  function rankBadge(rank) {
    const badge = node("span",undefined,`rank-badge rank-${rank.kind}`);
    const arrow = node("span",rank.arrow);
    arrow.setAttribute("aria-hidden","true");
    badge.append(arrow,node("span",rank.label));
    if (rank.reason) badge.title = rank.reason;
    return badge;
  }

  function renderBestCondition(models) {
    const pooled = poolConditions(snapshot.models.filter(entry => selectedComparisonModels.has(entry.model)));
    const metricKey = $("comparison-metric").value;
    const metric = comparisonMetrics[metricKey];
    const ranks = rankConditions(pooled.conditions,metricKey);
    const best = ranks.best[0] ? pooled.conditions[ranks.best[0]] : null;
    $("best-condition-metric").textContent = metric.label;
    $("best-condition-scope").textContent = models.length
      ? `${snapshot.target} / ${models.join(", ")} / all ${snapshot.scenarios.length} scenarios / ${pooled.completed} of ${pooled.total} planned paired trials completed.`
      : "No models selected.";
    $("best-condition-summary").textContent = !models.length ? "Select at least one comparison model to identify the best observed condition."
      : ranks.reason ? `No recommendation yet: ${ranks.reason}`
      : metricKey === "accepted" && !best.accepted ? "No condition produced an accepted outcome in the selected completed trials. There is no successful condition to recommend."
      : ranks.best.length > 1 ? `No unique best condition: ${ranks.best.map(arm => labels[arm]).join(", ")} are tied at ${best[metricKey]} / ${best.evaluated} (${percent(best[metricKey],best.evaluated)}) for ${metric.label}.`
      : `${labels[ranks.best[0]]} has the ${metric.lowerIsBetter ? "lowest" : "highest"} observed rate for ${metric.label}: ${best[metricKey]} / ${best.evaluated} (${percent(best[metricKey],best.evaluated)}). This ranks only the selected metric, not overall requirement satisfaction or performance on a new run.`;
    $("best-condition-rows").replaceChildren(...(models.length ? Object.keys(labels).map(arm => {
      const value = pooled.conditions[arm];
      const row = node("tr");
      row.dataset.condition = arm;
      const ranking = node("td");
      ranking.append(rankBadge(ranks.entries[arm]));
      row.append(node("td",labels[arm]),node("td",metric.unknown && value[metric.unknown] ? "Unassessed / unknown" : `${value[metricKey]} / ${value.evaluated} (${percent(value[metricKey],value.evaluated)})`),
        ranking,node("td",value.meanAttempts === null ? "Unknown" : value.meanAttempts.toFixed(2)),
        node("td",duration(value.meanElapsedSeconds)),node("td",`${value.operationalErrors} / ${value.evaluated}`));
      return row;
    }) : []));
  }

  function renderScenarioComparison() {
    const metricKey = $("comparison-metric").value;
    const metric = comparisonMetrics[metricKey];
    const models = snapshot.models.filter(entry => selectedComparisonModels.has(entry.model)).map(entry => entry.model);
    $("scenario-comparison").hidden = !models.length;
    $("comparison-selection").textContent = models.length
      ? `Pooling ${models.length} selected model(s) for ${snapshot.target}: ${models.join(", ")}.`
      : "Select at least one model. No results are pooled or ranked for an empty selection.";
    const scenarioHeading = node("th","Scenario");
    scenarioHeading.scope = "col";
    scenarioHeading.rowSpan = 2;
    const modelHeadings = [scenarioHeading];
    const conditionHeadings = [];
    if (models.length) {
      const heading = node("th",`Selected models pooled (${models.length})`);
      heading.colSpan = Object.keys(labels).length;
      heading.scope = "colgroup";
      modelHeadings.push(heading);
      for (const label of Object.values(labels)) {
        const condition = node("th",label);
        condition.scope = "col";
        conditionHeadings.push(condition);
      }
    }
    $("scenario-model-headings").replaceChildren(...modelHeadings);
    $("scenario-condition-headings").replaceChildren(...conditionHeadings);
    $("scenario-comparison-note").textContent = `${metric.label}: ${metric.description} Each condition cell sums the selected models' completed repetitions for that scenario.`;
    $("scenario-comparison-rows").replaceChildren(...(models.length ? snapshot.scenarios.map(scenario => {
      const row = node("tr");
      const heading = node("th",scenario.scenario);
      heading.scope = "row";
      row.append(heading);
      const group = poolConditions(scenario.models.filter(entry => selectedComparisonModels.has(entry.model)));
      const ranks = rankConditions(group.conditions,metricKey);
        for (const arm of Object.keys(labels)) {
          const value = group.conditions[arm];
          const cell = node("td",undefined,"scenario-metric-cell");
          cell.dataset.scenario = scenario.scenario;
          cell.dataset.models = JSON.stringify(models);
          cell.dataset.condition = arm;
          if (value.evaluated && metric.unknown && value[metric.unknown] === value.evaluated) {
            cell.append(node("strong","Unassessed / unknown"));
          } else if (value.evaluated) {
            cell.append(node("strong",`${value[metricKey]} / ${value.evaluated} (${percent(value[metricKey],value.evaluated)})`));
          } else {
            cell.append(node("span",group.total ? "Not evaluated" : "Not scheduled"));
          }
          if (group.completed < group.total) cell.append(node("p",`${group.completed} / ${group.total} planned trials completed`,"micro"));
          const unknown = metric.unknown ? value[metric.unknown] : 0;
          if (unknown) cell.append(node("p",`${unknown} unknown / blocked; not counted as passed`,"micro"));
          cell.append(rankBadge(ranks.entries[arm]));
          cell.title = `${scenario.scenario} / pooled ${models.join(", ")} / ${labels[arm]} / ${metric.label}`;
          row.append(cell);
        }
      return row;
    }) : []));
    renderBestCondition(models);
  }

  function renderUsage() {
    $("model-token-rows").replaceChildren(...(snapshot.usage.byModel ?? []).map(value => {
      const row = node("tr");
      row.append(...[
        value.model,format(value.requests),format(value.inputTokens),format(value.outputTokens),
        format(value.totalTokens),`${format(value.knownRequests)} known / ${format(value.unknownRequests)} unknown`,
        duration(value.generationSeconds),
      ].map(text => node("td",text)));
      return row;
    }));
    $("condition-token-rows").replaceChildren(...(snapshot.usage.byModelCondition ?? []).map(value => {
      const row = node("tr");
      row.append(...[
        value.model,labels[value.arm],format(value.workflows),format(value.inputTokens),
        format(value.outputTokens),format(value.totalTokens),
        `${format(value.knownRequests)} known / ${format(value.unknownRequests)} unknown`,
        duration(value.meanElapsedSeconds),
      ].map(text => node("td",text)));
      return row;
    }));
  }

  function render(data) {
    if (snapshot?.run !== data.run) {
      detailKey = null;
      $("workflow-detail").hidden = true;
    }
    snapshot = data;
    const empty = !data.run;
    $("empty").hidden = !empty;
    $("dashboard").hidden = empty;
    if (empty) {
      $("run-status").textContent = "No runs";
      return;
    }
    if (comparisonRun !== data.run) {
      comparisonRun = data.run;
      $("comparison-metric").value = data.assessmentMode === "human_review" ? "visiblePassed" : "accepted";
    }
    for (const option of $("comparison-metric").options) {
      const unassessed = data.assessmentMode === "human_review" && ["accepted","structuralAccepted"].includes(option.value);
      option.textContent = `${comparisonMetrics[option.value].label}${unassessed ? " (unassessed)" : ""}`;
    }
    options("target-filter",data.targets.map(target => ({value:target,label:target})),null,data.target);
    options("model-filter", data.models.map(({ model }) => ({ value: model, label: model })), "All models");
    renderComparisonModels();
    options("scenario-filter", data.scenarios.map(({ scenario }) => ({ value: scenario, label: scenario })), "All scenarios");
    const active = data.status === "started";
    $("run-status").textContent = active ? "Recorded as running" : data.status.replaceAll("_", " ");
    $("run-status").className = `badge ${active ? "running" : data.status === "completed" ? "good" : "bad"}`;
    const age = (Date.now() - Date.parse(data.updatedAt)) / 1000;
    $("updated").textContent = `Artifact updated ${new Date(data.updatedAt).toLocaleTimeString()}; refreshed ${new Date(data.observedAt).toLocaleTimeString()}`;
    $("scope-label").textContent = `${data.cloudEnabled ? "CLOUD-ENABLED STUDY" : "STATIC ONLY"} / ${data.target}`;
    $("target-profile").textContent = data.assessmentMode === "human_review"
      ? "Human-written requirements: no resource-shape oracle or automated quality verdict. Compilation and policy results are separate observations. Acceptance awaits human review. Usage breakdowns cover the whole execution."
      : data.securityCheckIds.length ? `network-intents-v1 / scoped Checkov baseline: ${data.securityCheckIds.join(", ")} / enabled: ${data.checkovEnabled ?? "unknown"}. Outcomes are stratified by cloud/IaC target; usage covers the whole execution.` : "Legacy NET benchmark: original provider-specific contracts and validation scope are preserved.";
    $("outcomes-scope").textContent = data.assessmentMode === "human_review"
      ? "Compilation and visible policy checks only. Requirement satisfaction remains unassessed; these results are not human quality scores."
      : "Final artifacts from completed paired trials only. Acceptance requires visible validators and the finite structural contract.";
    $("trial-count").textContent = `${data.completed} / ${data.total}`;
    $("run-progress").max = data.total;
    $("run-progress").value = data.completed;
    $("progress-caption").textContent = `${percent(data.completed, data.total)} for selected target / ${data.completed * 3} workflows. Whole execution: ${data.executionCompleted}/${data.executionTotal} paired trials.`;
    $("request-count").textContent = format(data.generationRequests);
    $("request-caption").textContent = `Whole execution: maximum ${format(data.maximumGenerationRequests)} generation requests; backend calls may differ. Token accounting and wall time also cover all targets.`;
    $("elapsed").textContent = duration(((data.completedAt ? Date.parse(data.completedAt) : Date.now()) - Date.parse(data.createdAt)) / 1000);
    $("active-job").textContent = data.activeJob
      ? `${data.activeJob.retryTrialIndex ? `Retrying operationally failed trial ${data.activeJob.retryTrialIndex}` : "Next unfinished"}: ${data.activeJob.scenario}, ${data.activeJob.model}, rep ${data.activeJob.repetition}.`
      : "No unfinished scheduled trial recorded.";
    $("error-count").textContent = format(Object.values(data.conditions).reduce((sum, value) => sum + value.operationalErrors, 0));
    $("generation-failures").textContent = `${Object.values(data.conditions).reduce((sum, value) => sum + value.generationFailures, 0)} workflows with generation failure`;
    $("scenario-grid").replaceChildren(...data.scenarios.map((value) => {
      const card = node("article", undefined, "scenario");
      const progress = node("progress");
      progress.max = value.total;
      progress.value = value.completed;
      progress.setAttribute("aria-label", `${value.scenario}: ${value.completed} of ${value.total} paired trials completed`);
      card.append(node("strong", value.scenario), progress,
        node("p", `${value.completed} / ${value.total}`, "micro"),
        node("p", value.feedback.acceptanceUnknown ? "Requirement review pending" : `Feedback accepted ${value.feedback.accepted}/${value.feedback.evaluated}`, "micro"));
      return card;
    }));
    $("input-tokens").textContent = format(data.usage.inputTokens);
    $("output-tokens").textContent = format(data.usage.outputTokens);
    $("known-usage").textContent = `${format(data.usage.knownRequests)} known / ${format(data.usage.unknownRequests)} unknown`;
    $("cost").textContent = data.usage.costUsd === null ? "Unknown / not an invoice" : `$${data.usage.costUsd.toFixed(4)}`;
    $("run-path").textContent = `results/${data.run}`;
    $("summary-link").setAttribute("aria-disabled", String(!data.summaryAvailable));
    $("summary-link").tabIndex = data.summaryAvailable ? 0 : -1;
    $("summary-link").textContent = data.summaryAvailable ? "Final summary" : active ? "Summary pending" : "No final summary";
    const warnings = [...data.warnings];
    if (active && age > 600) warnings.push(`No completed-trial update in ${duration(age)}. A long trial or an interrupted runner may cause this; process liveness is not inferred.`);
    $("warnings").hidden = warnings.length === 0;
    $("warnings").replaceChildren(...warnings.map((warning) => node("p", warning)));
    renderConditions();
    renderUsage();
    renderScenarioComparison();
    renderTrials();
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    $("refresh").disabled = true;
    $("run-select").disabled = true;
    try {
      const target = $("target-filter").value;
      const [runs, data] = await Promise.all([api("/api/runs"), api(`/api/state${target ? `?${new URLSearchParams({target})}` : ""}`), refreshControl().catch(error => {
        $("run-error").textContent = error.message;
        $("run-error").hidden = false;
      })]);
      options("run-select", runs.map((run) => ({
        value: run.run,
        label: `${run.run} / ${run.error ? `unreadable: ${run.error}` : `${run.completed}/${run.total} ${run.status}`}`,
      })), null, data.run);
      render(data);
      $("error").hidden = true;
      failures = 0;
    } catch (error) {
      failures += 1;
      $("run-status").textContent = "Disconnected / status unknown";
      $("run-status").className = "badge bad";
      $("error").textContent = `${error.message} ${snapshot ? "Previous snapshot retained; it may be stale." : "No snapshot available."} Retry ${failures}; automatic refresh will try again.`;
      $("error").hidden = false;
    } finally {
      busy = false;
      $("refresh").disabled = false;
      $("run-select").disabled = false;
    }
  }

  $("run-select").addEventListener("change", async () => {
    if (busy) return;
    busy = true;
    $("run-select").disabled = true;
    try {
      await api("/api/select", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run: $("run-select").value }),
      });
      $("target-filter").replaceChildren();
    } catch (error) {
      $("run-select").value = snapshot?.run ?? "";
      $("error").textContent = error.message;
      $("error").hidden = false;
      return;
    } finally {
      busy = false;
      $("run-select").disabled = false;
    }
    await refresh();
  });
  $("refresh").addEventListener("click", refresh);
  $("model-filter").addEventListener("change", () => { renderConditions(); renderTrials(); });
  $("comparison-metric").addEventListener("change", renderScenarioComparison);
  $("target-filter").addEventListener("change",() => { detailKey = null; $("workflow-detail").hidden = true; refresh(); });
  $("comparison-all-models").addEventListener("click", () => {
    snapshot.models.forEach(entry => selectedComparisonModels.add(entry.model));
    renderComparisonModels();
    renderScenarioComparison();
  });
  $("comparison-clear-models").addEventListener("click", () => {
    selectedComparisonModels.clear();
    renderComparisonModels();
    renderScenarioComparison();
  });
  $("scenario-filter").addEventListener("change", renderTrials);
  $("outcome-filter").addEventListener("change", renderTrials);
  $("summary-link").addEventListener("click", (event) => {
    if ($("summary-link").getAttribute("aria-disabled") === "true") event.preventDefault();
  });
  async function showOutcome(run, trial, arm) {
    const identity = {run,trial:String(trial),arm};
    const key = JSON.stringify(identity);
    detailKey = key;
    $("workflow-detail").hidden = false;
    $("detail-title").textContent = "Loading recorded workflow evidence";
    $("detail-summary").textContent = "Reading saved results. No model calls or evaluation changes.";
    for (const id of ["detail-gates","detail-checks","detail-policies","detail-artifacts","detail-warnings"]) $(id).replaceChildren();
    for (const id of ["detail-attempts","detail-stopping","detail-pairing"]) $(id).textContent = "";
    const detailFold = $("workflow-detail").closest(".monitor-collapse");
    detailFold.hidden = false;
    detailFold.open = true;
    $("workflow-detail").scrollIntoView({block:"start"});
    try {
      const detail = await api(`/api/detail?${new URLSearchParams(identity)}`);
      if (detailKey !== key) return;
      $("detail-title").textContent = `${detail.scenario} / ${detail.model} / repetition ${detail.repetition} / ${labels[detail.arm]}`;
      $("detail-summary").textContent = `${detail.accepted === null ? "Unassessed" : detail.accepted ? "Accepted" : "Not accepted"}: ${detail.summary}`;
      $("detail-attempts").textContent = `${detail.attempts} generation attempt(s); condition budget ${detail.attemptLimit ?? "unknown"}. This explanation interprets saved evidence; it does not rescore the experiment.`;
      $("detail-gates").replaceChildren(...detail.gates.map(gate => {
        const line = node("div", undefined, "gate-line");
        line.append(node("strong", gate.name), badge(gate.status), node("p", gate.description, "micro"));
        return line;
      }));
      $("detail-stopping").textContent = detail.stopping;
      $("detail-pairing").textContent = detail.sharedInitial;
      const checks = [...detail.checks].sort((a,b) => Number(a.status === "passed") - Number(b.status === "passed"));
      $("detail-checks").replaceChildren(...checks.map(check => {
        const block = node("details", undefined, "check-explanation");
        block.open = check.status !== "passed";
        const summary = node("summary", `${check.title}: ${check.status}`);
        const evidence = node("ul");
        evidence.append(...check.evidence.map(item => node("li", item)));
        block.append(summary, node("code", check.id), node("p", check.explanation), evidence);
        return block;
      }));
      if (detail.policyFailures.length) {
        $("detail-policies").append(node("h3","Visible-validator diagnostics"));
        for (const failure of detail.policyFailures) $("detail-policies").append(node("pre",failure,"validator-diagnostic"));
      }
      $("detail-warnings").hidden = !detail.warnings.length;
      $("detail-warnings").replaceChildren(...detail.warnings.map(message => node("p",message)));
      for (const [file,label] of detail.artifacts) {
        const link = node("a",label);
        link.href = `/api/detail/artifact?${new URLSearchParams({...identity,file})}`;
        link.download = "";
        $("detail-artifacts").append(link);
      }
    } catch (error) {
      if (detailKey === key) $("detail-summary").textContent = `Outcome details could not be loaded: ${error.message}`;
    }
  }
  $("close-detail").addEventListener("click", () => { detailKey = null; $("workflow-detail").hidden = true; });
  function showTab(runner) {
    $("runner").hidden = !runner;
    $("monitor-view").hidden = runner;
    $("monitor-tab").setAttribute("aria-pressed", String(!runner));
    $("run-tab").setAttribute("aria-pressed", String(runner));
  }
  $("monitor-tab").addEventListener("click", () => showTab(false));
  $("run-tab").addEventListener("click", () => showTab(true));

  function invalidatePlan() {
    planId = null;
    $("run-preview").hidden = true;
    $("confirm-paid").checked = false;
    $("start-run").disabled = true;
  }
  function applySettings(settings) {
    for (const [id, value] of Object.entries({
      "run-models": settings.models.join(", "), "run-scenarios": settings.scenarios.join(", "),
      "run-targets": settings.targets.join(", "),
      "run-repetitions": settings.repetitions, "run-iterations": settings.max_iterations,
      "run-seed": settings.random_seed, "run-tokens": settings.max_tokens,
    })) $(id).value = value;
    invalidatePlan();
  }
  function requestParameters() {
    const operation = $("run-operation").value;
    const input = { operation, login: $("run-login").checked };
    if (operation !== "new") input.source_run = snapshot?.run;
    else input.config = $("run-config").value;
    if (operation !== "resume") Object.assign(input, {
      models: $("run-models").value.split(",").map(v => v.trim()).filter(Boolean),
      targets: $("run-targets").value.split(",").map(v => v.trim()).filter(Boolean),
      scenarios: $("run-scenarios").value.split(",").map(v => v.trim()).filter(Boolean),
      repetitions: Number($("run-repetitions").value),
      max_iterations: Number($("run-iterations").value),
      random_seed: Number($("run-seed").value), max_tokens: Number($("run-tokens").value),
    });
    return input;
  }
  async function post(route, input) {
    return api(route, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
  }
  async function refreshControl() {
    const next = await api("/api/control");
    const initial = control === null;
    control = next;
    $("runner-unavailable").hidden = next.enabled;
    $("run-form").hidden = !next.enabled;
    if (!next.enabled) return;
    $("mode-label").textContent = "STATIC STUDY WORKSPACE";
    $("runner-warnings").hidden = !next.warnings?.length;
    $("runner-warnings").textContent = next.warnings?.join("; ") ?? "";
    if (initial) {
      options("run-config", next.configs.map(c => ({value:c.config,label:c.config})), null, next.defaultConfig);
      $("run-operation").value = next.parameters?.operation ?? "new";
      await loadOperation(next.parameters?.source_run);
      if (next.parameters?.scenarios) $("run-scenarios").value = next.parameters.scenarios.join(", ");
      $("run-login").checked = next.parameters?.login ?? false;
    }
    const job = next.job;
    $("job-status").textContent = job
      ? `Execution ${job.status}${job.run ? ` / ${job.run}` : ""}${job.message ? `: ${job.message}` : ""}`
      : "No execution started by this dashboard.";
    if (job?.run && followedJob !== job.id) {
      await post("/api/select", {run:job.run});
      $("target-filter").replaceChildren();
      followedJob = job.id;
    }
    $("start-run").disabled = !planId || !$("confirm-paid").checked || job?.status === "running";
  }
  $("run-config").addEventListener("change", () => {
    const config = control?.configs.find(c => c.config === $("run-config").value);
    if (config) applySettings(config);
  });
  async function loadOperation(sourceRun) {
    invalidatePlan();
    const operation = $("run-operation").value;
    $("run-config").disabled = operation !== "new";
    for (const id of ["run-models","run-targets","run-scenarios","run-repetitions","run-iterations","run-seed","run-tokens"]) $(id).disabled = operation === "resume";
    $("run-error").hidden = true;
    try {
      if (operation === "new") {
        $("run-source").textContent = "Output: results/ui-runs (new directory for each execution).";
        const config = control.configs.find(c => c.config === $("run-config").value);
        if (config) applySettings(config);
      } else {
        const source = sourceRun ?? snapshot?.run;
        if (!source) throw Error("Select an execution in Monitor first.");
        const settings = await post("/api/settings", {source_run:source});
        applySettings(settings);
        $("run-source").textContent = `Source: ${source}`;
      }
    } catch (error) {
      $("run-error").textContent = error.message;
      $("run-error").hidden = false;
    }
  }
  $("run-operation").addEventListener("change", () => loadOperation());
  $("run-form").addEventListener("input", invalidatePlan);
  $("confirm-paid").addEventListener("input", event => {
    event.stopPropagation();
    $("start-run").disabled = !planId || !$("confirm-paid").checked || control?.job?.status === "running";
  });
  $("run-form").addEventListener("submit", async event => {
    event.preventDefault();
    invalidatePlan();
    $("run-error").hidden = true;
    $("preview-run").disabled = true;
    try {
      const preview = await post("/api/plan", requestParameters());
      const blockers = preview.execution_blockers ?? [];
      planId = blockers.length ? null : preview.plan_id;
      $("confirm-paid").disabled = blockers.length > 0;
      $("run-preview").textContent = `${preview.completed} completed / ${preview.total} planned paired trials. At most ${preview.maximum_new_generation_requests} new generation requests; ${preview.workflows} remaining workflows. Targets: ${preview.targets.join(", ")}. ${preview.note}${preview.skipped_variants.length ? "\nUnsupported combinations excluded: "+preview.skipped_variants.map(item=>`${item.intent} / ${item.target}: ${item.reason}`).join("; ") : ""}`;
      $("run-preview").hidden = false;
      if (blockers.length) $("run-preview").textContent += `\nExecution blocked: ${blockers.join(" ")}`;
    } catch (error) {
      $("run-error").textContent = error.message;
      $("run-error").hidden = false;
    } finally { $("preview-run").disabled = false; }
  });
  $("start-run").addEventListener("click", async () => {
    $("start-run").disabled = true;
    try {
      await post("/api/start", {plan_id:planId,confirmed:$("confirm-paid").checked});
      invalidatePlan();
      await refreshControl();
    } catch (error) {
      $("run-error").textContent = error.message;
      $("run-error").hidden = false;
    }
  });
  setInterval(() => { if ($("auto-refresh").checked) refresh(); }, 5000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  refresh();
})();
