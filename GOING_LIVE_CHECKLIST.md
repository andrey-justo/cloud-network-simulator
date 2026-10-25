# Experiment Readiness Checklist

**Last reviewed:** 2026-10-06  
**Status:** Prototype in progress. Live generation and trace capture work; full validation and scenario acceptance remain incomplete.

## Current State

| Area | Current status |
|---|---|
| Scenario specifications | 10 YAML specifications exist under `scenarios/specs/`. |
| Bicep templates | 3 reference templates exist (NET-01 through NET-03); NET-04 through NET-10 remain. |
| Prompt templates | B1, T1, and iterative prompts are Markdown files under `templates/` and loaded by `PromptConfig`. |
| Azure model access | `gpt-6.1-sol`, `gpt-5.3-codex`, and `gpt-4o` are selectable. One NET-01 B1 request succeeded with `gpt-5.3-codex`; its output is [saved here](results/smoke/NET-01-gpt-5.3-codex.bicep). No cloud deployment was performed. |
| Live experiment path | `python main.py --mode live` runs B1/T1 and writes unique, traceable run folders. Missing validators block before model calls. |
| Trace configuration | `--output-dir` overrides `ExperimentConfig.output_directory`; each run records the manifest, spec/prompt copies and hashes, model ID, generated templates, and validation output. API keys are not recorded. |
| Validation tools | Bicep CLI 0.48.1 is installed and the saved NET-01 template compiles to ARM JSON. Checkov 3.3.19's in-process fallback passed 2 ARM checks with zero failures/parser errors; its console launcher is absent. Conftest is not installed, so Rego policies have not been executed and live runs with OPA enabled remain blocked by preflight. |
| Scenario acceptance | The runner currently records this as `not_automated`. Syntax/policy checks alone do not count as meeting the scenario contract. NET-01 also specifies a resource group while the saved model template targets an existing resource group; clarify whether the group must be created. |
| Metrics | Composite `quality_score` removed from the package metrics. Both metric paths now base policy violation rate on failed checks over executed checks; a rate with no executed checks is undefined. |
| Tests | Latest full run: 27 tests passed. Tests use mocked model/validator paths and do not prove live validator availability. |

## Before a Live Experiment

- [ ] Install and pin Conftest using the Windows instructions in [the POC guide](docs/POC_GUIDE.md), then run the Rego rules against compiled NET-01 ARM JSON.
- [x] Install Bicep CLI and confirm `bicep build` succeeds for the saved NET-01 model response (version 0.48.1).
- [x] Run Checkov 3.3.19 against the compiled ARM JSON and confirm no parser errors (2 checks passed, 0 failed).
- [ ] Review the initial Rego rules against all applicable scenarios; expand policy tests beyond NET-01 before the main experiment.
- [ ] Implement deterministic scenario-acceptance assertions, starting with NET-01; include explicit handling of the resource-group requirement.
- [ ] Verify the selected Azure deployment supports the configured Responses API version and model ID.
- [ ] Run the live command below and confirm the manifest records `completed_with_unverified_scenario_acceptance` only when automated checks pass; do not report acceptance until the scenario assertions exist.
- [ ] Select the actual scenario scope. Only NET-01 through NET-03 currently have Bicep reference templates.
- [ ] Define repetitions, stopping rules, model settings, and non-convergence reporting before collecting comparative data.

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

- [ ] Keep generation, validation, approval, and deployment as separate steps.
- [ ] Use least-privilege identities and require human review before write operations.
- [ ] Test deployment preview, rollback, and emergency-change procedures in a non-production subscription.
- [ ] Define audit retention/redaction and a drift-detection/reconciliation process for out-of-band changes.

## Validator Installation

For Windows installation and verification commands, see the [Bicep CLI and Conftest section](docs/POC_GUIDE.md). The verified Bicep and Checkov versions are recorded in the current-state table. Conftest remains to be installed and verified before OPA-enabled runs.

**Readiness decision:** The model-generation path has passed one NET-01 smoke request, and its Bicep compiled and passed the current Checkov ARM checks. OPA-enabled B1/T1 runs remain blocked until Conftest is installed and the Rego policies are executed. Scenario acceptance is still unautomated. Do not describe synthetic pilot results as live model results or use this prototype to authorize production changes.

## Project References

- [POC guide](docs/POC_GUIDE.md)
- [Live experiment runner](src/network_simulation/live_experiment.py)
- [Azure Responses client](src/network_simulation/azure_responses_client.py)
- [Bicep compiler adapter](src/network_simulation/validation/bicep_compiler.py)
- [Conftest adapter](src/network_simulation/validation/conftest_validator.py)
- [Metric implementation](src/network_simulation/metrics/types.py)
