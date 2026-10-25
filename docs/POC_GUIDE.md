# Network Simulation - Proof of Concept

Este é um exemplo de implementação POC para a proposta: **IA Assistida para Infraestrutura como Código (IaC) na Avaliação de Configurações de Rede no Azure**.

For the controlled research experiment, use the
[study protocol](STUDY_PROTOCOL.md) and `--mode study`. The B1/T1 commands below
describe the preserved legacy workflow, not the paired equal-budget protocol.
The study adds finite structural checks for all ten scenarios and optional
deployment/runtime checks; those cloud integrations have not been live-verified.

## Quick Start

### 1. Instalação de dependências

```bash
# Criar virtual environment e instalar dependencias
.\scripts\bootstrap.ps1

# Ativar
.\.venv\Scripts\Activate.ps1  # Windows

```

### Install Bicep CLI and Conftest on Windows

The live runner needs the standalone `bicep` command on `PATH`. From an
administrator-free PowerShell terminal, install it with Winget and reopen the
terminal:

```powershell
winget install -e --id Microsoft.Bicep
bicep --version
```

Historical runs used **Bicep CLI 0.48.1**; verify the current installation.
Compile a generated template to ARM JSON without deploying it (replace the
example path with an actual run artifact):

```powershell
bicep build 'results\live\<run-id>\scenarios\NET-01\B1\iteration-01\template.bicep' --outfile "$env:TEMP\NET-01.json"
```

The application adapter also discovers the per-user Winget installation if the
current VS Code process has a stale `PATH`. To select another executable, set
`BICEP_CLI` to its full path.

The `az bicep` command installs an Azure CLI-managed copy that is not added to
`PATH`; the experiment runner invokes `bicep` directly. See the
[official Bicep installation guide](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/install)
for the Windows installer and other installation methods.

Install Conftest using [Scoop](https://scoop.sh/) or download a Windows release
from the [official Conftest installation page](https://www.conftest.dev/install/):

```powershell
scoop install conftest
conftest --version
```

After installation, close and reopen the terminal and verify both commands are
available with `Get-Command bicep,conftest`.

### 2. Executar POC simulada

```bash
python main.py
```

This is the legacy **simulated** path. It uses synthetic B1/T1 data and summarizes
that data. It does not generate Bicep files or validate a manual B0 baseline.
Its results are not live model evaluation results.

### 3. Run a live model experiment

Configure the endpoint and credential in the workspace `.env` file. Do not commit the file or print the credential:

```dotenv
DEFAULT_MODEL_ENDPOINT=https://<resource>.openai.azure.com/openai/responses?api-version=<supported-version>
az_api_key=<secret>
LLM_MODEL=gpt-5.3-codex
```

Run one or more scenario specifications and choose a trace root:

```powershell
python main.py --mode live --scenario NET-01 --output-dir results/live
```

Repeat `--scenario` to include more scenarios. `--output-dir` can be an absolute path or a path relative to the repository. The default is `reports/`. The live runner does not deploy Azure resources. A preflight block or unverified scenario acceptance exits non-zero; blocked traces record missing tools/policies without making a model request.

If OPA is explicitly excluded from the experiment protocol, add `--disable-opa`. This does not disable Bicep compilation or Checkov, and the trace records that OPA was disabled.

Each run creates a unique directory containing `manifest.json`, the resolved scenario specification, and prompt templates. Inherited scenario sources are copied into `sources/`, with their hashes and context chain recorded. Initial and retry prompts include the full resolved requirements. The manifest is written before preflight and updated as scenarios finish, so interrupted runs retain progress. After preflight passes, each iteration stores its prompt, raw model response, normalized Bicep, generation metadata, hashes, elapsed time, and validator results. A blocked preflight records missing tools and does not create condition folders or make a model request. The manifest never records API keys.

The live runner compiles Bicep to ARM JSON, runs Checkov using its ARM framework,
then runs Conftest on that JSON. It fails closed before model requests when
enabled validation tools or Rego policies are missing. Current scenario
acceptance is recorded as `not_automated`; passing compilation and policy
checks alone is not reported as scenario acceptance.

Checkov runs in a separate process, including the Python-package fallback.
Execution failures, malformed reports, parser errors, and zero executed checks
cannot produce a pass. Both Checkov and OPA require Bicep compilation enabled.

### 4. Verificar resultados

The simulated path writes reports to `reports/`. Live trace artifacts are written under the selected output directory:
- `experiment_*.json` - Resultados do experimento
- `stage3_analysis.json` - Análise de hipóteses
- `live-<timestamp>-<id>/manifest.json` - Live-run metadata and status

## Estrutura de Diretórios

```
network-simulation/
├── scenarios/                 # Definições e specs dos cenários
│   ├── scenario_specs.py     # Critérios de aceitação
│   └── NET-*.yaml            # Configs por cenário
│
├── src/network_simulation/prompts/  # Bundled prompt resources
│   ├── prompt_b1.md
│   ├── prompt_t1.md
│   └── prompt_iterative.md
├── results/                  # Generated experiment artifacts, grouped by run
│
├── validation/
│   ├── checkov_validator.py  # Integração Checkov
│   ├── checkov/              # Custom rules Checkov
│   └── opa/                  # Políticas OPA/Rego
│
├── experiments/
│   └── experiment_runner.py  # Orquestrador B1 vs T1
│
├── evaluation/
│   └── metric_analyzer.py    # Análise de métricas
│
├── main.py                   # Orchestrator principal
├── src/network_simulation/configuration/  # Configuração, um módulo por classe
└── reports/                  # Saída de relatórios
```

## Componentes Principais

### 1. Generated Bicep and external references

Bicep files are experiment outputs, not pre-authored solutions under `templates/`.
The previous three unverified B0 files were removed. Preserve generated artifacts
unchanged and record corrections as new iterations. Validation output is retained
for subsequent metric extraction; scenario acceptance is not yet automated.

Use [Azure Verified Modules](https://github.com/Azure/bicep-registry-modules)
and [Azure Quickstart Templates](https://github.com/Azure/azure-quickstart-templates)
as design references, not automatically accepted baselines. Before adopting a B0
reference, record its source, pinned revision, license, parameters, and scenario,
then compile and validate it under the experiment protocol. Keep reviewed local
references separate from prompts and run outputs. No external samples are
currently imported or supplied to the generation prompts.

### 2. Validação Checkov
```python
from network_simulation.validation.checkov_validator import CheckovValidator

validator = CheckovValidator(framework="arm")
report = validator.validate_template(
    "results/live/<run-id>/scenarios/NET-01/B1/iteration-01/template.json",
    scenario_id="NET-01",
)
print(f"Acceptance rate: {report.acceptance_rate:.1f}%")
```

### 3. Framework de Experimentos
```python
from experiments.experiment_runner import ExperimentRunner

runner = ExperimentRunner()
# Adicionar resultados B1 e T1 para cada cenário
runner.add_scenario_result(scenario_result)
runner.save_report()
```

### 4. Análise de Métricas
```python
from evaluation.metric_analyzer import MetricAnalyzer

analyzer = MetricAnalyzer()
# Adicionar métricas de cada condição
comparison = analyzer.compare_conditions("NET-01", "B1", "T1")
```

## Cenários Implementados

| ID | Nome | Objective |
|----|------|-----------|
| NET-01 | Basic Virtual Network | Criação de VNet com validação de CIDR |
| NET-02 | Network Segmentation | Segmentação por 3 camadas (Web, App, Data) |
| NET-03 | Secure Network with NSGs | Regras de segurança restritivas entre camadas |
| NET-04-10 | (Documentados, implementação gradual) | - |

## Métricas de Avaliação

### Primary Metrics (H1, H2, H3)
1. **Policy violation rate**: failed policy checks divided by executed policy checks. If no policy checks ran, report the rate as undefined. Do not use scenario acceptance criteria as its denominator. H1 compares B1 and T1 only when both rates are available.
2. **Scenario acceptance rate**: satisfied acceptance criteria divided by applicable criteria from the versioned scenario specification. H2 compares B1 and T1 for each model/specification pair. The current live runner does not yet automate these free-text criteria.
3. **Efficiency**: report iterations to automated-check pass and elapsed time separately; mark non-convergent runs explicitly with `null` iterations. H3 compares observed elapsed times for convergent pairs only; it is undefined without such pairs. Do not combine outcomes into a weighted score.

### Secundárias
- Corretude de conectividade (fluxos permitidos/bloqueados)
- Aderência arquitetural (requisitos atendidos)
- Tempo total até os checks automatizados passarem

Metrics remain separate; no composite quality score is calculated.

## Variáveis de Configuração

Veja `src/network_simulation/configuration/`:
- Fases experimentais (pilot, main)
- Modelo LLM (provider, modelo, temperatura)
- Validação (Checkov, OPA, Terraform)
- Limites de violações aceitáveis

`POCConfig.load_yaml()` restores saved settings and accepts the legacy aliases
used by earlier configuration files. Unknown keys and invalid types fail
explicitly. API keys are excluded from saved files.

Generation sends `max_tokens` as `max_output_tokens` (default 2000). Temperature
and top-p default to `None`; this client allows explicit sampling controls only
for `gpt-4o` and rejects them for reasoning models. Effective generation settings
are recorded in the manifest. A truncated API response is a generation failure.

Prompt files are loaded through package resources, so default configuration and
the Checkov adapter also work in a wheel installation outside this checkout.
Workspace scenario files and policy directories remain explicit experiment inputs.

## Exemplo: Executar Validação em um Template

```bash
# Validar um template
python -m network_simulation.validation.checkov_validator 'results\live\<run-id>\scenarios\NET-01\B1\iteration-01\template.json' NET-01 --framework arm

# Salvar como JSON
python -m network_simulation.validation.checkov_validator 'results\live\<run-id>\scenarios\NET-01\B1\iteration-01\template.json' NET-01 --framework arm > validation_report.json
```

## Current Limitations and Next Steps

1. Install and pin the Bicep CLI and Conftest; the installed Checkov Python package can run without its console launcher, but verify its report has no parser errors.
2. Install Conftest, execute the initial Rego rules, and expand policy coverage to scenario-specific requirements.
3. Implement deterministic scenario-acceptance assertions; free-text criteria are currently not scored by the live runner.
4. Generate, validate, and evaluate outputs for each selected scenario before claiming coverage; no pre-authored Bicep solutions are required.
5. Run repeated live trials per model/specification and analyze the separate metrics.

## Referências

- Proposta: `papers/proposal-1-iac/proposta-tema-iac-azure.md`
- Benchmark Técnico: `papers/proposal-1-iac/benchmark-cenarios-azure-iac.md`
- Especificações de Cenários: `scenarios/scenario_specs.py`

## Status

🔄 Prototype in progress. Live model generation and trace capture are wired; full validation and scenario acceptance are not yet complete.

### Completo ✅
- Estrutura de diretórios
- Separation of prompt templates, generated Bicep artifacts, and external references
- Azure Responses client and selectable Azure models
- Markdown prompt loading
- Live B1/T1 runner with configurable trace output
- Separated metric implementation without a composite quality score
- Initial Rego policies for VNet structure, experiment tags, and public SSH/RDP exposure

### Em Progresso 🔄
- Validated experiment outputs across the selected scenarios
- Bicep CLI installation and compilation in the environment
- Conftest execution and broader OPA/Rego policy coverage
- Automated scenario acceptance and connectivity checks

### Futuro 📋
- Repeated experiment with live model outputs
- Análise estatística (testes de significância)
- Relatórios visuais (gráficos, tabelas)

---

**Autor**: Andrey Victor Justo  
**Data**: 2026-10-06  
**Versão**: 0.1.0
