# Network Simulation

Base repository for a research proposal on infrastructure, LLMs, and Infrastructure as Code (IaC), focused on generating, validating, and refining configurations in parameterized scenarios.

## Initial objective

This repository starts with the experimental orchestration layer:

- versioned scenario definitions;
- execution manifests;
- standardized result collection;
- support for comparing manual generation, LLM-assisted generation, and automated validation.

This is deliberate: network emulation is not the proposal's main focus, but it can provide methodological support at specific stages. We first structure the generation and validation pipeline, then connect an execution or experimentation backend when necessary.

## Structure

- `configs/`: experiment configurations.
- `scenarios/`: network scenarios in YAML.
- `results/`: execution outputs.
- `src/network_simulation/prompts/`: generation prompts bundled with the package.
- `scripts/`: setup and execution automation.
- `src/network_simulation/`: Python orchestration package.
- `tests/`: initial tests.

## Controlled research study

The controlled protocol is now separate from the historical B1/T1 workflow.
It provides common-candidate one-shot, blind-refinement, and tool-feedback arms;
seeded repeated trials; finite structural contracts for all ten scenarios; and
opt-in Azure deployment/runtime evaluation. See the
[study protocol](docs/STUDY_PROTOCOL.md) for hypotheses, limits, fixture
configuration, safety gates, and cost-accounting definitions.

```powershell
.\.venv\Scripts\python.exe -m network_simulation.main --validate-catalog
.\.venv\Scripts\python.exe main.py --mode study --config configs\experiment.example.yaml --dry-run
```

These commands make no paid requests or deployments. Execution requires
`--execute`; Azure additionally requires `cloud.enabled` and `--allow-azure`.
Cloud integration is covered by local mocked tests, not a live deployment
verification. A static pass is not runtime acceptance or PCI-DSS compliance.

Prepared [static smoke](configs/smoke-static.yaml) and
[static pilot](configs/pilot-static.yaml) configurations select `gpt-5.3-codex`
and `gpt-6.1-sol`, using the GitHub Copilot SDK and Copilot CLI credentials.
Both requested model IDs were verified through authenticated discovery;
unavailable models block execution without substitution. Cached CLI credentials
are reused. For browser sign-in without generation, run
`python -m network_simulation.copilot_client --login`. Interactive study runs
offer sign-in when needed; scripts can opt in with `--execute --login`.
The pilot has five exploratory repetitions over all ten scenarios, capped at
900 SDK generation requests (backend retries may add inference calls). See the
readiness report for current execution status. Install the optional SDK with `pip install -e '.[dev,copilot]'` and follow the
[readiness checklist](GOING_LIVE_CHECKLIST.md) before authorizing any paid call.

### Live execution dashboard

The packaged **Network IaC Study Monitor** combines monitoring and static-study
execution controls. It runs from the normal CLI or the project canvas in VS Code:

```powershell
# Open the dashboard without model calls.
.\.venv\Scripts\python.exe main.py --ui

# Start the selected static configuration and monitor it together.
.\.venv\Scripts\python.exe main.py --mode study --config configs\pilot-static.yaml --ui --execute --login

# Resume a managed interrupted run, or make a completely fresh rerun.
.\.venv\Scripts\python.exe main.py --mode study --resume results\ui-runs\study-<run-id> --execute
.\.venv\Scripts\python.exe main.py --mode study --resume results\ui-runs\study-<run-id> --full-rerun --execute
```

Add `--ui` to either resume/rerun command to open the workspace alongside it.
`--ui` alone starts no experiment. The **Run / rerun** tab offers configuration,
models, scenarios, repetitions, attempt budget, schedule seed and output-token
limit. Previewing makes no model calls; starting requires confirmation of a
single-use plan. Changing parameters invalidates confirmation. Cached Copilot
authentication is reused; browser sign-in requires the login checkbox or
`--execute --login`. CLI `--execute` is itself explicit authorization.

The canvas opens with `{}` to select the latest saved run, or
`{"run":"pilot-static/study-<run-id>"}` relative to `results`.
It discovers `results/study-*` and `results/<group>/study-*` directories.
Canvas ID: `cloud-network-study-monitor`; actions: `list_runs`, `get_progress`,
and `select_run`.

The dashboard refreshes every five seconds and shows paired-trial progress,
final-candidate compilation, acceptance by condition/model, scenario progress,
attempts, latency, known token usage, and errors. Filters and downloadable
manifest/call-ledger/final-summary artifacts support inspection. Missing metrics
remain unknown, and malformed artifacts produce explicit errors or warnings.
Copilot cost is not inferred from Azure token prices.
Every monitoring section has a keyboard-accessible collapse control. **Expand
all sections** and **Collapse all sections** change them together; automatic
refresh preserves their open/closed state.

### High-level multi-cloud scenario specifications

The original NET-01–10 specifications and retained results are unchanged.
The [planning profile](configs/multicloud-static.yaml) selects **NET-11 through
NET-30**, all defined as YAML in [scenarios/specs](scenarios/specs).
The specifications describe objectives, acceptance criteria, connectivity and
security requirements, not infrastructure resource graphs. `supported_targets`
declares the applicable cloud/IaC combinations. This yields 56 planned variants:

- `azure-bicep`: 19 variants.
- `azure-terraform`: 19 variants.
- `aws-terraform`: 18 variants.

Seventeen specifications have all three variants. Dual-stack addressing and
managed-container network integration currently have Azure variants only; S3
gateway routing has an AWS variant only. The preview lists every excluded
combination and its reason rather than treating unlike services as equivalent.

```powershell
.\.venv\Scripts\python.exe main.py --mode study --list-scenarios
.\.venv\Scripts\python.exe main.py --mode study --config configs\multicloud-static.yaml --validate-catalog
.\.venv\Scripts\python.exe main.py --ui --config configs\multicloud-static.yaml
```

The last command opens the UI without starting generation. Select cloud/IaC
targets in **Run / rerun** for a no-call preview. The two-model, one-repetition
profile plans 112 paired trials, 336 workflows and at most 1,008 generation requests.
Automated acceptance studies remain blocked until independent requirements-based
acceptance is implemented. The removed exact-resource grader is not a valid
substitute. Explicit `study.assessment_mode: human_review` permits static generation
and measurement while leaving requirement satisfaction **unassessed**, not failed
or accepted. This also bypasses the old resource-shape oracle for NET-01--NET-10.

The [human-requirements profile](configs/human-requirements-static.yaml) selects all
30 specifications: 66 supported cloud/IaC variants, two models, one repetition,
132 paired trials, 396 workflows and at most 1,188 saved generation requests:

```powershell
.\.venv\Scripts\python.exe -m network_simulation.main --config configs\human-requirements-static.yaml --execute --login
```

Prompts render the written requirements as prose and bullet lists, not JSON/YAML
examples or resource blueprints. Compilation and policy results stay separate
from requirement satisfaction. Each trial saves an unassessed review-preparation
record; this is not a completed or blinded human evaluation.

The monitoring token tables report whole-execution and per-model unique usage,
plus model-by-condition workflow attribution and elapsed time. Condition rows
include the shared initial candidate: **do not sum them as billing totals**.
Known tokens remain visible when some requests lack usage; coverage reports those
unknowns explicitly. Copilot dollar costs remain unknown. The same breakdowns are
saved in `summary.json`; request-level evidence remains in `calls.json`.

Initial and repair prompts use only the high-level specification, target/output
constraints, previous candidate and permitted visible diagnostics. Private
evaluation contracts are never appended. The old NET exact-shape evaluator is
retained for historical interpretation; its score is not a general verifier of
high-level network requirements. Historical prompts/results are not rewritten.

Terraform uses pinned official providers (`azurerm` 4.0.1 / `aws` 5.70.0), HCL
parsing and `terraform validate`; it never runs `plan` or `apply`. Install the
Terraform CLI on PATH or in `.tools\terraform` (ignored by Git). Provider
initialization may download provider binaries before model calls, but needs no
cloud credentials. Validation uses isolated temporary workspaces and does not
inherit cloud credentials or user Terraform CLI arguments/configuration.
Backend/module/data/provisioner blocks and unsupported expressions
are rejected explicitly. Provider configuration and lock files are saved with
candidate evidence.

The removed CASE catalog, prescribed security scaffolding and exact-resource
oracle are no longer used. Static compilation and policy results must remain
separate from scenario correctness. ARM Rego policies cannot evaluate Terraform.
See the [corrected protocol](docs/STUDY_PROTOCOL.md#high-level-multi-cloud-specifications)
for scope and execution-readiness limitations.

Monitoring selects one cloud/IaC target at a time; model pooling and
recommendations stay within that target. Tokens, generation requests and wall
time cover the whole execution and are labeled accordingly. Additional clouds
require explicit target capabilities, validators and reviewed evaluation coverage,
not just another model prompt.

The scenario comparison has its own multi-select model checkboxes, independent
of the overall outcome/workflow model filter. Selected models are pooled into
one result per scenario/condition by summing counts and denominators, not
averaging percentages. Select acceptance, compilation, visible-validator pass,
structural pass, generation failures or operational errors. Each cell reports
`count / completed trials (percentage)`; scheduled but incomplete trials are
not failures. Unknown/blocked evidence is noted separately and prevents a
best/worst ranking for that metric.

Green/red arrows identify the best/worst conditions within each scenario.
Failure metrics prefer lower rates, pass metrics higher rates; exact-ratio
ties are explicit and all-equal results are neutral. The final **Best condition
for selected models** section ranks pooled acceptance over all scenarios,
regardless of the matrix metric, explains ties/no-success/no-data cases, and
shows weighted attempt/latency tradeoffs without using them as tie breakers.
These are descriptive comparisons, not significance or runtime assurances.

Use **Explain outcome** on a workflow to inspect its separate generation,
compilation, policy and independent scenario-contract gates, stopping reason,
failed-check explanations and exact candidate evidence downloads. For example,
`bounded-resource-types-and-scope` can reject an extra NSG even when compilation
and every enabled policy check passed: the frozen contract enforces an exact
resource allowlist, not general semantic equivalence or infrastructure safety.
The detail view identifies the extra resource or explicit scope, where the
compiled evidence can be resolved. It interprets saved evidence without changing
scores or feeding held-out failures back into generation.

Monitoring remains read-only. Execution controls never enable Azure deployment;
cloud-enabled configurations are rejected. UI-created runs go to
`results/ui-runs/study-*`; full reruns always create a new directory and record
their source. Resume uses the original directory and frozen schedule, preserving
completed paired trials. An OS-owned lock prevents concurrent resume.
`checkpoint.json` is authoritative for recovery and `config.yaml` stores the
configuration without API keys. Unfinished trajectories are archived under
`interrupted-attempts` and retried as entire paired units. Known abandoned calls
remain in usage accounting, unknown interrupted requests are identified, and
additional retry budget is recorded. Held-out acceptance never guides recovery.
Uncheckpointed interrupted wall time cannot be recovered.

On Windows, checkpoint replacement retries sharing/access conflicts. If the
canonical checkpoint remains locked, a uniquely named complete recovery checkpoint
is committed instead, with an explicit error log. Resume and monitoring use the
newest checkpoint, including its matching call ledger; they never merge partial
JSON or truncate a locked file. Mirror refresh failures are logged separately.
Unrelated storage errors still stop execution. Recovery snapshots are retained
as evidence. A missing recorded runner is shown as interrupted; a lost dashboard
connection shows status unknown rather than retaining a running badge.

An explicitly authorized operational failure can be retried without regenerating
later successful trials. Preview the 1-based paired-trial index first, then add
`--execute` to authorize generation:

```powershell
.\.venv\Scripts\python.exe -m network_simulation.study_retry --run results\<group>\<study-directory> --trial 77
.\.venv\Scripts\python.exe -m network_simulation.study_retry --run results\<group>\<study-directory> --trial 77 --execute --login
```

Only a completed static study with identical frozen settings and an operationally
failed trial is eligible; policy/quality failures are not retry candidates.
Original checkpoints, results and artifacts remain under `operational-retries`
and their original candidate paths. Current metrics use the replacement paired
result; unique execution usage includes both the failed and replacement requests.
The history is displayed in monitoring warnings. A retry is not hidden or
reported as an additional independent repetition.

Scenario comparison defaults to **Visible validators passed** for human-review
studies, showing counts and percentages instead of an unassessed acceptance
matrix. Compilation, generation-failure and operational-error metrics are also
selectable. The best-condition summary follows that selected metric. Acceptance
and structural assessment remain explicitly unassessed until human review.
Atomic checkpoint replacement retries transient Windows sharing/access conflicts
for up to 4.5 seconds, logging each retry. Persistent or unrelated permission
errors still stop execution explicitly; recovery uses the last committed checkpoint.

Legacy runs without managed checkpoints can be inspected and fully rerun, but
cannot safely be resumed. Resume requires the original location and unchanged
study configuration, specifications, prompt, runner and acceptance implementation.
Completed runs resume as a no-op; use full rerun to generate again.
Keep the owning canvas/CLI open during execution: closing it interrupts its
managed worker, leaving checkpoints for recovery. An independently launched
experiment is never stopped by the dashboard.

Selection and unconsumed previews live in the UI instance; experiment artifacts
remain durable. Updates are recorded at paired-trial boundaries, not as a
process heartbeat. Interim comparisons are provisional, and static acceptance
does not establish runtime correctness.

The CLI uses the current Python interpreter and Node.js 22+ on PATH. The canvas
uses the project `.venv`. Both share the packaged web assets and native Node
server; no npm installation or separate server command is needed. The canvas
alone also uses the host-provided Copilot extension SDK. Run focused tests:

```powershell
node --test .github\extensions\study-monitor\monitor.test.mjs .github\extensions\study-monitor\controller.test.mjs .github\extensions\study-monitor\comparison.test.mjs
.\.venv\Scripts\python.exe -m pytest tests\test_study.py tests\test_study_ui.py -q
```

## Legacy quick start

### 1. Create and activate the virtual environment

Always use the local `.venv` environment to keep the setup reproducible and consistent with the rest of the project.

```powershell
.\scripts\bootstrap.ps1
.\.venv\Scripts\Activate.ps1
```

> If the environment already exists, activate it with ` .\.venv\Scripts\Activate.ps1 `.

The script installs dependencies and the editable package in `.venv` without
requiring activation. Install Python 3.11 before running it:

```powershell
winget install -e --id Python.Python.3.11 --scope user --silent
```

For another installation, use `.\scripts\bootstrap.ps1 -PythonExecutable 'C:\path\python.exe'`.
To test without activation: `.\.venv\Scripts\python.exe -m pytest -q`.

### 2. List available scenarios

```powershell
python -m network_simulation.main --list-scenarios
```

### 3. Generate an execution manifest

```powershell
python -m network_simulation.main --config configs/experiment.example.yaml --dry-run
```

### 4. Generate and validate experiment artifacts

Configure the model and validators according to the [POC guide](docs/POC_GUIDE.md), then run:

```powershell
python main.py --mode live --scenario NET-01 --output-dir results/live
```

Each iteration preserves `response.txt`, `template.bicep`, compiled ARM, and reports
under `results/live/<run-id>/scenarios/<scenario>/<B1-or-T1>/iteration-<number>/`.
Treat generated files as evidence: do not fix them manually; a correction must
be a new, traceable iteration. Validation takes place after generation, and its
results remain available for subsequent metric extraction.
The pipeline does not yet automate full scenario acceptance.

Specifications with `extends` are resolved before generation. Each scenario
preserves the original sources in `sources/`, their hashes, and the resolved
context in `specification.yml`; all attempts receive this complete context.
A Checkov execution error, invalid JSON, parsing errors, or zero executed checks
never counts as a validation pass.

`python main.py --mode simulated` uses only synthetic data; it neither generates
Bicep nor validates a manual B0 baseline. The former files in `templates/bicep`
were removed because they were not verified references.

## Configuration and installation

`POCConfig.save_yaml()` and `POCConfig.load_yaml()` preserve experiment, model,
validator, and prompt settings. Loading accepts the legacy keys
(`phase`, `scenarios`, `model`, `checkov`, `opa`) and rejects unknown types or
settings. API keys are not saved; obtain credentials from the environment
before creating a client.

`max_tokens` is sent as `max_output_tokens` (default: 2000).
`temperature` and `top_p` are disabled by default (`null`); this client accepts
these sampling controls only for `gpt-4o`. Configuring them for reasoning models
produces an explicit error. Incomplete responses are recorded as generation
failures, not complete templates.

Prompts and the Checkov adapter are included in the wheel. The installed path is
`network_simulation.validation.checkov_validator`; the legacy
`validation.checkov_validator` module remains available in the checkout as a wrapper.
Checkov is optional: install the dependencies in `requirements.txt` when you want
to run these checks. A configuration with Checkov disabled does not require
its installation.

The CLI strategy respects `cwd` and `env`. Native binaries receive arguments
directly; built-in commands use the selected shell's quoting rules. A command
that returns a nonzero exit code is not retried in another shell.

Reports calculate H3 from observed time, not iteration counts. Non-convergent
attempts use `null` for iterations to acceptance and are excluded from the
efficiency comparison; without convergent pairs, H3 and the iteration reduction
remain undefined.

## External IaC references

- [Azure Verified Modules](https://github.com/Azure/bicep-registry-modules):
  primary reference for Bicep modules, including network resources.
- [Azure Quickstart Templates](https://github.com/Azure/azure-quickstart-templates):
  topology and deployment examples; they require scenario-specific assessment.

These repositories are design references, not experiment results or automatically
accepted baselines. Before adopting an example as B0, record its URL, commit or
version, license, parameters, and scenario; compile and validate the artifact
using the same protocol as generated results. Keep any local references separate
from prompts and outputs, for example in `references/`, only after a selection
has been reviewed. No external example was imported, and references are not
injected into B1/T1 prompts.

## Next research milestone

Review the [controlled protocol](docs/STUDY_PROTOCOL.md), run local catalog
validation, and prepare operator-owned external fixtures in a disposable Azure
subscription. After explicit budget approval, use a pilot to determine the
main-study replication and analysis plan. No empirical hypothesis is confirmed
by the synthetic reports or software regression tests.

## Windows note

For actual emulation with Mininet/Containernet, the safest approach is to use:

- WSL2 with Ubuntu; or
- a dedicated Linux container.

Even without this layer, the repository already supports organizing scenarios, validations, and metrics without blocking research in the local environment.
