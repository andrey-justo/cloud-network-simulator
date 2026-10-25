# Experiment Readiness Checklist

**Last reviewed:** 2026-10-25
**Status:** Controlled study implemented with local regression coverage. Azure deployment and runtime behavior remain unverified in a live subscription.

Use the [controlled study protocol](docs/STUDY_PROTOCOL.md) for research data.
The older B1/T1 live path and synthetic reports are retained for compatibility,
not as evidence of a controlled treatment effect.

## Current State

| Area | Current status |
|---|---|
| Scenario specifications | All ten specifications load through the shared resolver. NET-02 YAML, NET-07 Firewall egress, NET-05 discard routing, NET-06 gateway assumptions, NET-09 DNS links, and NET-08/10 database/ingress requirements were clarified. |
| Bicep artifacts | The three unverified B0 files were removed. Bicep is generated per run/scenario/condition/iteration; no manual baseline is currently selected. See the [reference policy](README.md#referencias-externas-de-iac). |
| Prompt templates | B1, T1, and iterative prompts are bundled under `src/network_simulation/prompts/` and loaded through package resources by `PromptConfig`. |
| Azure model access | `gpt-6.1-sol`, `gpt-5.3-codex`, and `gpt-4o` are selectable. Historical smoke claims are not locally reproducible evidence: the referenced artifact is absent from this checkout. No model calls or deployments were made while implementing the controlled study. |
| Live experiment path | `python main.py --mode live` runs B1/T1 and writes unique, traceable run folders. Missing validators block before model calls. |
| Trace configuration | `--output-dir` overrides `ExperimentConfig.output_directory`; each run records the manifest, resolved context, original scenario sources/hashes, prompt copies, model generation settings, generated artifacts, and validation output. API keys are not recorded. |
| Validation tools | Historical smoke results used Bicep 0.48.1 and Checkov 3.3.19. These are not proof of current installation; recheck all tool versions in the local environment. Conftest and Rego execution remain to be verified. |
| Scenario acceptance | Study mode has finite structural contracts for all ten scenarios and guarded optional deployment/runtime checks. Legacy live mode still records `not_automated`. Candidates target an existing group; the cloud harness creates that group. A structural pass never establishes runtime correctness. |
| Metrics | Composite `quality_score` removed from the package metrics. Both metric paths now base policy violation rate on failed checks over executed checks; a rate with no executed checks is undefined. |
| Tests | Run the regression suite with the local venv. Mocked model/validator paths do not prove live Bicep or Conftest availability. |
| Controlled design | Shared initial candidate; one-shot, blind refinement and tool feedback; repeated seeded schedules; all-trial cost/time summaries and exploratory paired family-cluster intervals. |

## Before a Live Experiment

- [ ] Install and pin Conftest using the Windows instructions in [the POC guide](docs/POC_GUIDE.md), then run the Rego rules against compiled NET-01 ARM JSON.
- [ ] Verify the current Bicep CLI installation with a fresh local compilation; historical version claims are not current installation checks.
- [ ] Re-run Checkov against fresh compiled artifacts and preserve the report; earlier smoke checks are engineering verification, not hypothesis evidence.
- [ ] Review the initial Rego rules against all applicable scenarios; expand policy tests beyond NET-01 before the main experiment.
- [x] Implement finite structural contracts for all ten scenarios, with catalog-wide regression coverage and explicit resource-group scope.
- [ ] Verify the selected Azure deployment supports the configured Responses API version and model ID.
- [ ] Run the live command below and confirm the manifest records `completed_with_unverified_scenario_acceptance` only when automated checks pass; do not report acceptance until the scenario assertions exist.
- [ ] Select the scenario scope from the YAML specifications; do not require pre-existing Bicep solutions. If a manual B0 is needed, select, pin, and independently validate an external reference first.
- [x] Implement configurable repetitions, stopping rules, model settings, and non-convergence reporting.
- [ ] Use pilot variance/costs to choose and pre-register the main-study sample size and analysis.

## Run and Trace Output

The historical synthetic runner remains the default and must not be presented as live model evidence:

```powershell
python main.py --mode simulated --output-dir reports/simulated
```

A live B1/T1 run uses the workspace `.env` endpoint/key and can select scenarios and an output root:

```powershell
python main.py --mode live --scenario NET-01 --output-dir results/live
```

Set `LLM_MODEL` to one configured model ID to choose the model. `DEFAULT_MODEL_ENDPOINT` and `az_api_key` are supported, as are the Azure-specific variable names. Use `--disable-opa` only when OPA is explicitly excluded from the experiment protocol. Keep credentials out of source control and logs.

The runner creates a unique folder under the configured root, with this shape:

```text
<output-root>/<run-id>/
  manifest.json
  prompts/
  scenarios/<scenario-id>/
    specification.yml
    # Created only after required validation preflight passes:
    B1/result.json
    B1/iteration-01/{prompt.md,response.txt,template.bicep,generation.json,validation.json,result.json}
    T1/result.json
    T1/iteration-01/{prompt.md,response.txt,template.bicep,generation.json,validation.json,result.json}
```

When required validators are absent, the runner still records the specification, prompts, tool status, and a blocked run manifest, but makes no model request. It never deploys cloud resources.

## Before Any Cloud Deployment

- [ ] Review the study plan and maximum deployment count; use `--execute --allow-azure` only after explicit budget approval.
- [ ] Supply and validate runtime bindings, external vantage points, healthy endpoint controls, and audit parameters.
- [ ] Verify cleanup and retained-group reporting in a disposable subscription before a study-wide run.
- [ ] Keep generation, validation, approval, and deployment as separate steps.
- [ ] Use least-privilege identities and require human review before write operations.
- [ ] Test deployment preview, rollback, and emergency-change procedures in a non-production subscription.
- [ ] Define audit retention/redaction and a drift-detection/reconciliation process for out-of-band changes.

## Validator Installation

For Windows installation and verification commands, see the [Bicep CLI and Conftest section](docs/POC_GUIDE.md). The verified Bicep and Checkov versions are recorded in the current-state table. Conftest remains to be installed and verified before OPA-enabled runs.

**Readiness decision:** Local controlled-study orchestration and cloud adapters are regression-tested; live Azure deployment/runtime checks still require operator configuration, approval, and verification. Missing validators block execution. No empirical hypothesis has been confirmed. Do not present synthetic outcomes or mocked tests as live research evidence, or use this prototype to authorize production changes.

## Project References

- [POC guide](docs/POC_GUIDE.md)
- [Live experiment runner](src/network_simulation/live_experiment.py)
- [Azure Responses client](src/network_simulation/azure_responses_client.py)
- [Bicep compiler adapter](src/network_simulation/validation/bicep_compiler.py)
- [Conftest adapter](src/network_simulation/validation/conftest_validator.py)
- [Metric implementation](src/network_simulation/metrics/types.py)
