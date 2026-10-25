# Controlled Azure network IaC study

## Research question and scope

Under a fixed generation budget, does validator-guided repair improve independent
acceptance of Azure/Bicep network configurations compared with blind refinement,
and what are its cost, latency, and security-regression tradeoffs?

The contribution is an Azure-network benchmark and controlled evaluation, not
the invention of an IaC feedback loop. The latter already appears in
[Palavalli and Santolucito's 2024 preprint](https://arxiv.org/abs/2411.19043).
The older bibliography is a discovery list: entries without verified primary
sources must not substantiate novelty claims.

This protocol supersedes the synthetic H1/H2/H3 claims in historical reports.
Software tests, static policy passes, and simulated timings are not experimental
confirmation. No main-study sample-size or significance claim is made here.

## Conditions and experimental unit

The unit is scenario x model identifier x repetition. Each unit generates one
common initial candidate, shared by three paired workflows:

| Condition | Budget | Revision information |
|---|---|---|
| `one_shot` | One generation | None |
| `blind_refinement` | Up to K generations, including the shared initial one | Scenario, contract, and previous candidate; no validator diagnostics |
| `tool_feedback` | Same K | Same inputs plus visible compilation/policy diagnostics |

The initial prompt and generation settings are identical. Scenario/model units
and arm execution order are shuffled using a recorded seed. This seed controls
the scheduler, not model determinism. Different model IDs are analyzed
separately. API response model/version metadata is retained when available.

Each arm stops at the first visible-validator pass, generation failure, or K
attempts. Independent acceptance is evaluated only after all trajectories for
that unit have been frozen, and never enters a repair prompt or stopping rule.
These are final-artifact success rates under a bounded workflow, not oracle
selection of the best candidate seen during the run.

Maximum physical model calls per unit: `1 + 2 * (K - 1)`. Each workflow's token,
time, and cost totals include the shared first candidate. The physical call
ledger counts that generation once. Do not sum workflow costs to estimate the
actual experiment invoice.

## Prepared exploratory static batches

The [smoke configuration](../configs/smoke-static.yaml) uses NET-01, both
`gpt-5.3-codex` and `gpt-6.1-sol`, one repetition and K=2: two paired units,
six workflows, and at most six physical calls. The
[pilot configuration](../configs/pilot-static.yaml) uses the same models, all
ten scenarios, five repetitions and K=5: 100 paired units, 300 workflows, and
at most 900 physical calls. Neither batch has been executed against a model.
Five repetitions are exploratory, not a power analysis or confirmatory design.

Both profiles enable all three static validators and disable cloud deployment.
They explicitly select Microsoft Entra authentication via the Azure CLI;
install the optional `azure-auth` extra and follow the
[authentication instructions](POC_GUIDE.md#microsoft-entra-id-aad-for-the-prepared-static-pilot).
The CLI plans without acquiring credentials or making model requests:

```powershell
.\.venv\Scripts\python.exe main.py --mode study --config configs\smoke-static.yaml --dry-run
.\.venv\Scripts\python.exe main.py --mode study --config configs\pilot-static.yaml --dry-run
```

Endpoint access, model/deployment identifiers, pricing and a spending limit
must be verified before explicitly authorizing `--execute`. Cost estimates are
undefined while prices remain unset. Check the smoke artifacts before approving
the larger pilot; static success is not live Azure acceptance.

## Scenario contracts

All ten original YAML definitions must load before execution. Versioned finite
contracts are implemented in
[`study_acceptance.py`](../src/network_simulation/study_acceptance.py) and are
included in each plan and trace. Requirements are public; evaluator code/results
are not repair diagnostics. The evaluator implementation hash is recorded.

| Scenario | Additional contract focus | Runtime observations |
|---|---|---|
| NET-01 | RFC1918 VNet/subnet, containment, non-overlap, Experiment tag | Same-subnet fixture connectivity |
| NET-02 | Three named tiers | Cross-tier connectivity without NSGs |
| NET-03 | Explicit allowlists and terminal inbound deny rules | Allowed and forbidden tier flows; public web fixture only |
| NET-04 | NAT, Standard static public IP, subnet association | Observed egress IP and lack of direct inbound access |
| NET-05 | Exact discard route for `10.250.0.0/16` | Next-hop discard and blocked target flow |
| NET-06 | Four directional peerings, disjoint addresses, no nonexistent VPN gateway | Hub/spoke connectivity and spoke isolation |
| NET-07 | Azure Firewall, dedicated subnet, default spoke routes, HTTPS allowlist | Next hop, egress IP, permitted HTTPS and denied HTTP |
| NET-08 | Application Gateway as sole public entry, protected SQL tier | End-to-end gateway HTTP, tier isolation, blocked data egress |
| NET-09 | Premium Service Bus, disabled public access, private endpoint and DNS links for all VNets | Private DNS, AMQP TLS-port connectivity, effective public-access setting |
| NET-10 | WAF prevention configuration, private SQL endpoint, audit destination | Gateway HTTP, private SQL DNS/connectivity and effective public-access setting |

The benchmark deliberately standardizes names, CIDRs, and rule sets for
reproducibility. This narrows external validity; it is not a general verifier
for every equivalent Azure design. Resource absence and unsupported ARM
expressions never count as acceptance. Inline and child subnet declarations,
common parameter/variable references, `concat`, `format`, and same-group
`resourceId` are supported. Resource loops, arbitrary deployment-time functions,
and conditionally deployed resources require a resolved deployment view and
currently fail closed. Do not interpret an unsupported expression as a policy
violation; the per-check `blocked` status preserves the distinction.

All candidates target an existing resource group; the cloud harness creates
that group. A candidate must not deploy a subscription-level resource group.
Declare `param studySuffix string = 'local'` and use it in SQL and Service Bus
names. The cloud backend substitutes a unique suffix to prevent global-name
collisions across trials. Secrets must be supplied through local deployment
parameters, never committed or embedded in prompts.

Static acceptance is **only the finite structural contract**. It does not prove
deployability, effective routes, NSG behavior, application correctness,
production readiness, or regulatory compliance. TCP success is not a successful
SQL query or Service Bus operation; WAF configuration is not an exhaustive WAF
attack-resistance test.

SQL and Service Bus may share public frontends that accept a TCP handshake
even when public data access is disabled. Their public-access assertion reads
the effective deployed `publicNetworkAccess` setting; it is a control-plane
observation, not a claim that every public TCP handshake must fail. Private
connectivity and DNS are measured separately.

## Outcomes and analysis

Choose the primary scope before collecting data:

- Cloud disabled: final artifact passes visible validators and finite structural
  acceptance. Runtime remains unverified.
- Cloud enabled: the same plus successful Azure deployment and every required
  runtime check passing. Missing/blocked probes cannot count as success.

Primary H1: the paired acceptance risk difference for tool feedback versus
blind refinement is positive. Comparison with one-shot is a workflow comparison,
not an isolated feedback effect. Secondary measures include executed and
failed policy checks, structural criterion coverage, first-attempt outcomes,
non-convergence, newly failing security-check/resource pairs between iterations,
tokens, nominal model cost, and wall-clock durations.

Do not assert that repair must be faster than one-shot. Cost/latency versus
success is an empirical tradeoff. Report all-trial cost and duration first;
successful-only duration is explicitly conditional. Unknown usage/prices remain
`null`, not zero. User-supplied USD-per-million rates are nominal estimates:
`study.model_prices` maps model IDs to `[input, output]` rates and overrides the
optional common rates. Caching discounts and Azure resource costs are not
inferred or included in model-token estimates.

The summary reports paired effect estimates and exploratory 95% family-cluster
bootstrap intervals, separately by model. Family groups are basic, three-tier
(NET-02/03/08/10), egress-routing (NET-04/05), and hub-spoke (NET-06/07/09).
With fewer than two families, intervals are undefined. Even four families are
too few for strong broad-population inference: treat intervals as exploratory.
Repetitions do not turn inherited scenarios into independent samples.

Retain generation, tool, deployment, probe, and cleanup failures. No
post-generation exclusions are permitted by the implementation. Preflight
blocks are reported separately from completed experimental units. A pilot is
needed to estimate variability, operational failure rates, and costs before
pre-registering the main-study repetition count, detectable effect/precision,
analysis, and any infrastructure-failure retry policy.

## Safe local commands

Use the local venv from the repository root:

```powershell
.\.venv\Scripts\python.exe -m network_simulation.main --validate-catalog
.\.venv\Scripts\python.exe main.py --mode study --config configs\experiment.example.yaml --dry-run
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

The example selects all ten scenarios with one repetition for planning/smoke
purposes, not as a statistically adequate main experiment. A plan makes no
model, Azure, or validator subprocess calls.

Paid model execution requires `--execute`. Cloud execution additionally requires
`cloud.enabled: true`, explicit Azure configuration, and `--allow-azure`.
**Do not run either example below without reviewing the plan and budget:**

```powershell
# Paid model requests; cloud remains disabled in the example configuration.
.\.venv\Scripts\python.exe main.py --mode study --config configs\experiment.example.yaml --execute
# Paid model requests AND Azure resources, only with a separately reviewed cloud configuration.
.\.venv\Scripts\python.exe main.py --mode study --config configs\cloud.local.yaml --execute --allow-azure
```

Cloud parameter/binding file paths are resolved from the configuration's
directory; the output root is relative to the selected workspace.
Use a disposable, non-production subscription. Azure Firewall, Application
Gateway, Premium Service Bus, SQL, probe VMs, IP addresses, and audit storage can
be costly. Cleanup is best effort, is recorded, and is not a spending guarantee.
Review retained resource-group IDs and cleanup failures after every run.

Runtime execution needs explicit fixture bindings, an external test vantage
point for Internet-originated checks, working Network Watcher permissions,
healthy probe VMs/listeners, and the required Azure control-plane connectivity.
Absent or unhealthy fixtures are blocked measurements, not evidence of
isolation. Never add permissive candidate rules merely to make the test harness
work; record harness limitations separately.

The cloud backend's binding schema and fixed probe behavior are documented in
[`study_cloud.py`](../src/network_simulation/study_cloud.py). Auto-created
fixtures are in the uniquely owned trial group and use the candidate's subnet
controls; external fixtures remain operator-owned. Dynamic gateway, NAT,
Firewall, Service Bus, and SQL destinations must refer to that trial's resources.

### Preparing cloud configuration

Copy the three examples to ignored local files before filling any credentials:

```powershell
Copy-Item configs\cloud.example.yaml configs\cloud.local.yaml
Copy-Item configs\runtime-bindings.example.json configs\runtime-bindings.local.json
Copy-Item configs\deployment-parameters.example.json configs\deployment-parameters.local.json
```

In the local YAML, point `runtime_bindings_file` and `parameters_file` to the
local JSON names, fill the disposable subscription and location, and review
the selected scenarios, repetition count, and maximum resource/model budget.
Replace the placeholder external VM IDs and `.example.test` endpoints with
operator-owned healthy fixtures. The examples are **not execution-ready**.

The parameter JSON supports a `scenarios` mapping, so SQL/audit credentials
are supplied only to NET-10, not accidentally to the other nine templates.
Ordinary ARM parameter JSON is also supported for single-scenario runs.
Do not place secret defaults in Bicep. NET-10 declares secure
`sqlAdministratorPassword` and `auditStorageKey` parameters and nonsecret
`sqlAdministratorLogin` and `auditStorageEndpoint` parameters. Supply real
values locally; the default audit URI is only a structural-validation placeholder.
The backend's unique `studySuffix` override is deliberately not operator-controlled.

NET-08/10 web fixtures request the explicit private address `10.1.1.4`, matching
the gateway backend pool. Their listener and gateway HTTP checks share
`expected_body: "study-{study_suffix}"`, preventing a gateway handshake alone
from counting as backend success. NET-03 has separate `web` (private) and
`web-public` destination roles. Only its web fixture may request a public IP.

DNS expectations can bind to a deployed private endpoint instead of guessing
its IP, and NET-07 next-hop expectations bind to the deployed Firewall private
IP. Owned fixture SSH private keys must be removed after public-key generation;
they are not experimental evidence.

## Evidence and reproducibility

Every run preserves the plan/schedule, exact source specifications and resolved
context, contract, tool versions, prompt and evaluator hashes, individual model
calls, usage/cost availability, candidates, visible diagnostics, independent
structural results, and (when enabled) deployment/runtime/cleanup evidence.
The manifest is persisted before generation and after each complete unit.
API keys and deployment secret values must not appear in evidence.

Legacy `--mode live` retains its original B1/T1 workflow and does not implement
this controlled protocol. Legacy `--mode simulated` remains synthetic. Neither
is a replacement for this study's independent outcomes.
