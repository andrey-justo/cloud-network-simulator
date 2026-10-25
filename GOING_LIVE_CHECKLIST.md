# Experiment Readiness Checklist

**Last reviewed:** 2026-10-25
**Status:** Static pilot prepared; local Bicep, Checkov, and Conftest smoke checks pass. Entra endpoint access and both model deployments still require verification. No paid experiment has run.

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
| Validation tools | Locally verified Bicep 0.48.1, Checkov 3.3.29, Conftest 0.71.1 / OPA 1.21.1. A fresh test-only Bicep fixture compiles, passes Checkov/Conftest and structural acceptance; negative policy controls also fail as expected. |
| Scenario acceptance | Study mode has finite structural contracts for all ten scenarios and guarded optional deployment/runtime checks. Legacy live mode still records `not_automated`. Candidates target an existing group; the cloud harness creates that group. A structural pass never establishes runtime correctness. |
| Metrics | Composite `quality_score` removed from the package metrics. Both metric paths now base policy violation rate on failed checks over executed checks; a rate with no executed checks is undefined. |
| Tests | Run the regression suite with the local venv. Mocked model/validator paths do not prove live Bicep or Conftest availability. |
| Controlled design | Shared initial candidate; one-shot, blind refinement and tool feedback; repeated seeded schedules; all-trial cost/time summaries and exploratory paired family-cluster intervals. |
| Authentication | API keys remain supported. Prepared batches select Microsoft Entra via `AzureCliCredential`; tokens refresh through the Azure Identity SDK and are never written to experiment artifacts. No automatic API-key fallback. |

## Prepared Static Batches

| Configuration | Models | Scenarios | Repetitions | K | Paired units / workflows | Maximum physical model calls |
|---|---|---|---|---|---|---|
| [Smoke](configs/smoke-static.yaml) | `gpt-5.3-codex`, `gpt-6.1-sol` | NET-01 | 1 | 2 | 2 / 6 | 6 |
| [Exploratory pilot](configs/pilot-static.yaml) | Same two models | All ten | 5 | 5 | 100 / 300 | 900 |

Both configurations disable Azure deployment. Five repetitions are for
exploration, not a justified confirmatory sample size. Model prices are unset;
cost estimates remain undefined until actual rates are supplied.

Preparation verification: **406 Python tests and 10 Rego tests passed**;
correctness lint and dependency consistency checks passed. Dry-run schedules
were generated and checked against the exact limits above. This is local
engineering evidence, not model-performance evidence.

Prepare/review without authentication or paid requests:

```powershell
.\.venv\Scripts\python.exe main.py --mode study --config configs\smoke-static.yaml --dry-run
.\.venv\Scripts\python.exe main.py --mode study --config configs\pilot-static.yaml --dry-run
```

Before authorizing even the six-call smoke:

- [ ] Configure `DEFAULT_MODEL_ENDPOINT` for the intended Azure OpenAI Responses endpoint.
- [ ] Log in to the correct tenant with `az login`; optionally set `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID` in the ignored local environment.
- [ ] Verify the signed-in identity has **Cognitive Services OpenAI User** access to the target resource.
- [ ] Verify the endpoint exposes both configured model/deployment identifiers.
- [ ] Supply nominal per-model token prices and approve a spending limit.
- [ ] Explicitly authorize the paid smoke using `--execute`, inspect its artifacts, then separately authorize the larger pilot.

Installing the optional SDK: `.\.venv\Scripts\python.exe -m pip install -e '.[dev,azure-auth]'`.
The preparatory work installed it locally. Authenticated model access has not
been tested, and no Azure resource/RBAC changes were made.

## Before a Live Experiment

- [x] Install Conftest 0.71.1, verify its official archive SHA256, and run Rego against fresh compiled test ARM JSON.
- [x] Verify Bicep 0.48.1 with a fresh local compilation.
- [x] Run Checkov 3.3.29 against the fresh test artifact. This is engineering verification, not hypothesis evidence.
- [ ] Review the initial Rego rules against all applicable scenarios; expand policy tests beyond NET-01 before the main experiment.
- [x] Implement finite structural contracts for all ten scenarios, with catalog-wide regression coverage and explicit resource-group scope.
- [ ] Verify the selected Azure deployment supports the configured Responses API version and model ID.
- [ ] Run the live command below and confirm the manifest records `completed_with_unverified_scenario_acceptance` only when automated checks pass; do not report acceptance until the scenario assertions exist.
- [ ] Select the scenario scope from the YAML specifications; do not require pre-existing Bicep solutions. If a manual B0 is needed, select, pin, and independently validate an external reference first.
- [x] Implement configurable repetitions, stopping rules, model settings, and non-convergence reporting.
- [ ] Use pilot variance/costs to choose and pre-register the main-study sample size and analysis.

## Run and Trace Output

Use the prepared static configurations above for the controlled study.
The following legacy commands are retained for compatibility only.
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

For Windows installation and verification commands, see the [Bicep CLI and Conftest section](docs/POC_GUIDE.md). The compiler also discovers the Azure CLI-managed copy under `~/.azure/bin`; Conftest supports `CONFTEST_CLI`, `PATH`, then `~/.local/bin`. No permanent PATH edit is required.

**Readiness decision:** Local static validation is ready. Model identity/RBAC, endpoint/deployment availability, pricing and paid-run authorization remain open. Cloud deployment is not part of the selected pilot. No empirical hypothesis has been confirmed. Do not present test fixtures or mocked tests as live research evidence, or use this prototype to authorize production changes.

## Project References

- [POC guide](docs/POC_GUIDE.md)
- [Live experiment runner](src/network_simulation/live_experiment.py)
- [Azure Responses client](src/network_simulation/azure_responses_client.py)
- [Bicep compiler adapter](src/network_simulation/validation/bicep_compiler.py)
- [Conftest adapter](src/network_simulation/validation/conftest_validator.py)
- [Metric implementation](src/network_simulation/metrics/types.py)
