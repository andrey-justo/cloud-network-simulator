# 📚 Índice do Projeto: network-simulation

**Workspace**: `C:\Users\Andrey Victor Justo\workspace\network-simulation`  
**Criação**: 2026-09-05  
**Status**: ✅ POC Completa e Executada

---

## 🚀 Quick Start

```bash
# 1. Navegue para o workspace
cd "c:\Users\Andrey Victor Justo\workspace\network-simulation"

# 2. Crie um ambiente virtual (opcional)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Instale dependências
pip install -r requirements.txt

# 4. Execute a POC
python main.py

# 5. Verifique os relatórios
Get-ChildItem reports/
```

---

## 📖 Documentação (Comece Aqui)

| Documento | Propósito | Para Quem |
|-----------|-----------|----------|
| [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) | Resumo de 1 página | Gestores / Executivos |
| [docs/POC_GUIDE.md](docs/POC_GUIDE.md) | Como usar a POC | Desenvolvedores |
| [docs/POC_RESULTS.md](docs/POC_RESULTS.md) | Resultados da execução | Pesquisadores |
| [docs/INTEGRATION_MAP.md](docs/INTEGRATION_MAP.md) | Como integrar com projeto principal | Arquitetos |
| [docs/WORK_SESSION_SUMMARY.md](docs/WORK_SESSION_SUMMARY.md) | O que foi feito nesta sessão | Historiadores |
| [README.md](README.md) | Overview técnico | Todos |

---

## 🏗️ Estrutura de Diretórios

```
network-simulation/
│
├── 📄 EXECUTIVE_SUMMARY.md              ← Comece aqui (1 página)
├── 📄 README.md                         ← Overview técnico
├── 📄 main.py                           ← Orquestrador (3 stages)
├── 📁 src/network_simulation/configuration/ ← Configurações separadas por módulo
├── 📄 requirements.txt                  ← Dependências
├── 📄 pyproject.toml                    ← Config Poetry
│
├── 📁 docs/
│   ├── EXECUTIVE_SUMMARY.md            ← Resumo executivo
│   ├── POC_GUIDE.md                    ← Manual de uso
│   ├── POC_RESULTS.md                  ← Análise dos resultados
│   ├── INTEGRATION_MAP.md              ← Integração com projeto principal
│   ├── WORK_SESSION_SUMMARY.md         ← Resumo da sessão
│   └── INDEX.md                        ← Este arquivo
│
├── 📁 scenarios/
│   └── scenario_specs.py               ← 10 cenários (NET-01 a NET-10)
│
├── 📁 templates/
│   ├── bicep/                          ← Templates Azure Resource Manager
│   │   ├── net-01-basic-vnet.bicep    ✅ Virtual Network básica
│   │   ├── net-02-segmentation.bicep  ✅ 3-tier segmentation
│   │   └── net-03-nsg-security.bicep  ✅ Network Security Groups
│   └── terraform/                      ← (Para comparação futura)
│
├── 📁 validation/
│   ├── checkov_validator.py            ← Integração com Checkov
│   ├── checkov/                        ← Custom rules (futuro)
│   └── opa/                            ← Políticas OPA/Rego (futuro)
│
├── 📁 experiments/
│   └── experiment_runner.py            ← Orquestrador B1 vs T1
│
├── 📁 evaluation/
│   └── metric_analyzer.py              ← Análise de métricas
│
└── 📁 reports/                         ← Saída (gerado após main.py)
    ├── stage1_baseline_validation.json
    ├── experiment_*.json
    └── stage3_analysis.json
```

---

## 🔧 Módulos Python

### Core Modules

| Módulo | Linha | Responsabilidade |
|--------|-------|-----------------|
| [main.py](main.py) | ~250 | Orquestrador: 3 stages (validação → experimento → análise) |
| [configuration package](../src/network_simulation/configuration/__init__.py) | Modular | Configurações de experimento, LLM, prompts e validação |

### Framework de Cenários

| Módulo | Linha | Classes |
|--------|-------|---------|
| [scenarios/scenario_specs.py](scenarios/scenario_specs.py) | ~450 | `NET_SCENARIO_SPECS` dict com 10 cenários |

### Validação

| Módulo | Linha | Classes |
|--------|-------|---------|
| [validation/checkov_validator.py](validation/checkov_validator.py) | ~300 | `CheckovValidator`, `ValidationReport` |

### Experimentos

| Módulo | Linha | Classes |
|--------|-------|---------|
| [experiments/experiment_runner.py](experiments/experiment_runner.py) | ~450 | `IterationResult`, `ScenarioExperimentResult`, `ExperimentRunner` |

### Análise

| Módulo | Linha | Classes |
|--------|-------|---------|
| [evaluation/metric_analyzer.py](evaluation/metric_analyzer.py) | ~350 | `ConnectivityMetric`, `NetworkScenarioMetrics`, `MetricAnalyzer` |

---

## 📊 Fluxo de Execução

```
main.py
  ↓
  Stage 1: Validação de Baseline
  ├── CheckovValidator.validate_template()
  ├── Para cada template: assess violations
  └── Output: stage1_baseline_validation.json
  ↓
  Stage 2: Simulação de Experimento
  ├── ExperimentRunner.add_scenario_result()
  ├── Simula B1 (múltiplas iterações)
  ├── Simula T1 (múltiplas iterações)
  └── Output: experiment_*.json
  ↓
  Stage 3: Análise de Resultados
  ├── MetricAnalyzer.compare_conditions()
  ├── MetricAnalyzer.aggregate_all_scenarios()
  ├── Teste de hipóteses H1, H2, H3
  └── Output: stage3_analysis.json
```

---

## 📋 Cenários (Especificações)

### Implementados (✅ com templates)
- **NET-01**: Basic Virtual Network
- **NET-02**: Network Segmentation (3-tier)
- **NET-03**: Secure Network with NSGs

### Especificados (📋 templates em pipeline)
- **NET-04**: Private Workload with NAT Gateway
- **NET-05**: Routed Network with User-Defined Routes
- **NET-06**: Hub-and-Spoke (Basic)
- **NET-07**: Hub-and-Spoke with Centralized Egress
- **NET-08**: Secure Three-Tier Application
- **NET-09**: Secure Hub-and-Spoke for Messaging
- **NET-10**: Secure Banking Workload

Todos têm:
- ✅ Acceptance criteria (8-15 por cenário)
- ✅ Connectivity requirements
- ✅ Security requirements
- ✅ Architectural requirements

---

## 🧪 Como Usar

### 1. **Visualizar Cenários**
```python
from scenarios.scenario_specs import get_scenario_spec, list_all_scenarios
print(list_all_scenarios())  # Lista todos
spec = get_scenario_spec("NET-01")
print(spec.acceptance_criteria)  # Ver critérios
```

### 2. **Validar Um Template**
```python
from validation.checkov_validator import CheckovValidator
validator = CheckovValidator()
report = validator.validate_template("templates/bicep/net-01-basic-vnet.bicep", "NET-01")
print(f"Acceptance Rate: {report.acceptance_rate}%")
print(f"Violations: {report.violation_count}")
```

### 3. **Executar Experimento**
```bash
python main.py
```

### 4. **Analisar Resultados**
```bash
Get-Content reports/stage3_analysis.json | ConvertFrom-Json | Format-Table
```

---

## 📊 Relatórios Gerados

Após executar `python main.py`, 3 arquivos JSON são criados em `reports/`:

### stage1_baseline_validation.json
```json
{
  "total_templates": 3,
  "templates": [
    {
      "template_id": "NET-01",
      "total_checks": 50,
      "passed": 42,
      "failed": 8,
      "acceptance_rate": 84.0,
      "violations": [...]
    }
  ]
}
```

### experiment_YYYYMMDD_HHMMSS.json
```json
{
  "metadata": {...},
  "results": {
    "NET-01": {
      "b1_iterations": [{...}, {...}, {...}],
      "t1_iterations": [{...}, {...}],
      "b1_acceptance_rate": 33.3,
      "t1_acceptance_rate": 50.0
    }
  }
}
```

### stage3_analysis.json
```json
{
  "total_scenarios": 3,
  "violation_rate": {
    "mean_delta": -90.0,
    "hypothesis_support": {
      "h1_supported": 1.0,
      "h2_supported": 0.0,
      "h3_supported": 0.0
    }
  }
}
```

---

## 🔗 Integração com Projeto Principal

**Workspace 1**: `coding-tool-reasoning` (Projeto existente)
- Foco: Refatoração C# com Supervisor Agent
- Status: Em desenvolvimento
- Localização: `C:\Users\Andrey Victor Justo\workspace\coding-tool-reasoning`

**Workspace 2**: `network-simulation` (POC Nova)
- Foco: Geração IaC Azure com Validação
- Status: POC Pronta
- Localização: `C:\Users\Andrey Victor Justo\workspace\network-simulation`

**Plano de Integração**:
1. Reutilizar padrões de experimento (dataclasses, métricas)
2. Adaptar Supervisor Agent para IaC
3. Estender MCP Server com tools Bicep
4. Unificar frameworks

Veja [docs/INTEGRATION_MAP.md](docs/INTEGRATION_MAP.md) para detalhes.

---

## 🚀 Próximas Fases

### Phase 1: POC Completa (1-2 semanas)
- [ ] Instalar Checkov e executar Stage 1 com dados reais
- [ ] Implementar templates NET-04 a NET-10
- [ ] Criar políticas OPA/Rego
- [ ] Prompt engineering para B1 vs T1

### Phase 2: LLM Integration (2-3 semanas)
- [ ] Conectar com OpenAI/Anthropic/Azure
- [ ] Implementar geração real de templates
- [ ] Loop iterativo automático
- [ ] Experimento pilot com dados reais

### Phase 3: Escala para Main Experiment (2-3 semanas)
- [ ] 6+ cenários com múltiplas repetições
- [ ] Análise estatística e significância
- [ ] Comparação B1 vs T1 completa

---

## 💾 Arquivos de Configuração

### requirements.txt
```
pydantic>=2.0
pyyaml>=6.0
```

### pyproject.toml
```toml
[tool.poetry]
name = "network-simulation"
version = "0.1.0"
```

### Configuration Package
```python
from network_simulation.configuration import LLMConfig, PromptConfig
```

---

## 📞 Contato & Suporte

- **Responsável**: Andrey Victor Justo
- **Data Criação**: 2026-09-05
- **Versão**: 0.1.0
- **Status**: Ready for Phase 1 ✅

---

## 📖 Leitura Recomendada

### Para Começar
1. [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) - 5 min
2. [README.md](README.md) - 10 min
3. [docs/POC_GUIDE.md](docs/POC_GUIDE.md) - 15 min

### Para Profundo
4. [scenarios/scenario_specs.py](scenarios/scenario_specs.py) - Specs
5. [experiments/experiment_runner.py](experiments/experiment_runner.py) - Framework
6. [docs/INTEGRATION_MAP.md](docs/INTEGRATION_MAP.md) - Roadmap

### Para Entender a Sessão
7. [docs/WORK_SESSION_SUMMARY.md](docs/WORK_SESSION_SUMMARY.md) - O que foi feito

---

## ✅ Checklist de Verificação

- ✅ Estrutura criada
- ✅ 10 cenários especificados
- ✅ 3 templates Bicep
- ✅ Validação Checkov integrada
- ✅ Framework de experimentos
- ✅ Sistema de métricas
- ✅ POC executada com sucesso
- ✅ Documentação completa
- ✅ Relatórios gerados

---

**Última Atualização**: 2026-09-05  
**Próxima Revisão**: Após Phase 1
