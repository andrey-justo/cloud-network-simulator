# Quick Reference Card

**Workspace**: `C:\Users\Andrey Victor Justo\workspace\network-simulation`  
**Print-friendly**: ✅ Salve como PDF para consulta rápida

---

## 🚀 Comandos Rápidos

### Executar a POC
```bash
cd "c:\Users\Andrey Victor Justo\workspace\network-simulation"
python main.py
```

### Ver Resultados
```bash
Get-ChildItem reports/*.json
cat reports/stage3_analysis.json
```

### Ver Cenários
```bash
python -c "from scenarios.scenario_specs import list_all_scenarios; print(list_all_scenarios())"
```

### Validar um Template
```bash
python -c "
from validation.checkov_validator import CheckovValidator
v = CheckovValidator()
r = v.validate_template('templates/bicep/net-01-basic-vnet.bicep', 'NET-01')
print(f'Acceptance: {r.acceptance_rate}%')
"
```

---

## 📁 Arquivos Importantes

### Documentação
| Arquivo | Propósito |
|---------|-----------|
| [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) | 1 página (gestores) |
| [docs/POC_GUIDE.md](docs/POC_GUIDE.md) | Como usar |
| [docs/POC_RESULTS.md](docs/POC_RESULTS.md) | Resultados pilot |
| [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md) | Roadmap Phase 1-5 |
| [docs/INTEGRATION_MAP.md](docs/INTEGRATION_MAP.md) | Integração projeto principal |

### Código Principal
| Arquivo | Linhas | Descrição |
|---------|--------|-----------|
| [main.py](../main.py) | 250 | Orquestrador 3 stages |
| [configuration package](../src/network_simulation/configuration/__init__.py) | Modular | Configurações |

### Módulos
| Arquivo | Linhas | Classes |
|---------|--------|---------|
| [scenarios/scenario_specs.py](../../scenarios/scenario_specs.py) | 450 | 10 cenários |
| [validation/checkov_validator.py](../../validation/checkov_validator.py) | 300 | CheckovValidator |
| [experiments/experiment_runner.py](../../experiments/experiment_runner.py) | 450 | ExperimentRunner |
| [evaluation/metric_analyzer.py](../../evaluation/metric_analyzer.py) | 350 | MetricAnalyzer |

### Templates
| Arquivo | Cenário | Status |
|---------|---------|--------|
| [net-01-basic-vnet.bicep](../../templates/bicep/net-01-basic-vnet.bicep) | NET-01 | ✅ |
| [net-02-segmentation.bicep](../../templates/bicep/net-02-segmentation.bicep) | NET-02 | ✅ |
| [net-03-nsg-security.bicep](../../templates/bicep/net-03-nsg-security.bicep) | NET-03 | ✅ |

---

## 📊 Dados Estrutura

### Cenário (scenario_specs.py)
```python
{
  "scenario_id": "NET-01",
  "name": "Basic Virtual Network",
  "objective": "...",
  "acceptance_criteria": [8-15 strings],
  "connectivity_requirements": [strings],
  "security_requirements": [strings],
  "architectural_requirements": [strings]
}
```

### Experimento (experiment_runner.py)
```python
IterationResult:
  - iteration_num: int
  - condition: "B1" | "T1"
  - template_content: str
  - validation_passed: bool
  - security_violations: int
  - checkov_score: float
  - execution_time_seconds: float

ScenarioExperimentResult:
  - scenario_id: str
  - b1_iterations: [IterationResult]
  - t1_iterations: [IterationResult]
  - b1_acceptance_rate: float
  - t1_acceptance_rate: float
  - improvement_acceptance_rate: float
  - improvement_violations: float
```

### Métricas (metric_analyzer.py)
```python
NetworkScenarioMetrics:
  - violation_rate: float (%)
  - acceptance_rate: float (%)
  - connectivity_correctness: float (%)
  - iterations_to_acceptance: int

Comparação B1 vs T1:
  - violation_rate_delta: float
  - acceptance_rate_delta: float
  - iterations_delta: int
```

---

## 🧪 3 Stages da POC

### Stage 1: Validação Baseline
```
Entrada: Templates Bicep (B0)
Processo: Checkov scan
Saída: stage1_baseline_validation.json
└── acceptance_rate, violations por template
```

### Stage 2: Experimento
```
Entrada: Configuração (num scenarios, max iterations)
Processo: Simula B1 vs T1 por cenário
Saída: experiment_*.json
└── b1_iterations[], t1_iterations[], métricas
```

### Stage 3: Análise
```
Entrada: Dados do Stage 2
Processo: Compara B1 vs T1, testa H1/H2/H3
Saída: stage3_analysis.json
└── hypothesis_support, deltas, agregação
```

---

## 🔢 Estatísticas Esperadas

### Depois de `python main.py` (Pilot)
```
Total Scenarios: 3
Total Runs: 6 (3 scenarios × 2 conditions)

NET-01:
  B1 Iterations: 3 | T1 Iterations: 1
  B1 Violations: 1.7 | T1 Violations: 0.0
  Improvement: 50pp violação reduction

NET-02:
  B1 Iterations: 4 | T1 Iterations: 2
  B1 Violations: 2.5 | T1 Violations: 1.0
  Improvement: 80pp violação reduction

NET-03:
  B1 Iterations: 5 | T1 Iterations: 1
  B1 Violations: 3.2 | T1 Violations: 2.0
  Improvement: 140pp violação reduction

HIPÓTESES:
  H1 (B1 > T1 violations): 100% suportado ✅
  H2 (T1 melhor aceitação): Requer dados reais ⚠️
  H3 (T1 mais eficiente): 2.7x menos iterações ✅
```

---

## 🎯 Próximos Passos Curtos

### Esta Semana
- [ ] Decidir qual LLM (OpenAI, Anthropic, Azure)
- [ ] Preparar API keys

### Próxima Semana (Phase 1)
- [ ] Instalar Checkov
- [ ] Implementar templates NET-04 a NET-10
- [ ] OPA/Rego policies
- [ ] Refinar prompts

### Semana 3-5 (Phase 2)
- [ ] LLM integration
- [ ] llm_generator.py
- [ ] Experimento com dados reais

### Semana 6-12 (Phase 3-5)
- [ ] Pilot experiment
- [ ] Main experiment (10 cenários)
- [ ] Integração com projeto principal

---

## 🐛 Troubleshooting

### Erro: "Checkov not found"
```
Solução: pip install checkov==3.2.0
```

### Erro: "Template not found"
```
Solução: Templates devem estar em templates/bicep/*.bicep
```

### POC não gera relatórios
```
Solução: Verificar que reports/ diretório existe
         Verificar permissões de escrita
```

### Métricas zeradas
```
Solução: Stage 2 simulação = mock data
         Use dados reais: Phase 2 LLM integration
```

---

## 🔗 Links de Referência

### Workspace Atual
- `C:\Users\Andrey Victor Justo\workspace\network-simulation`

### Projeto Principal
- `C:\Users\Andrey Victor Justo\workspace\coding-tool-reasoning`

### Documentação
- [Índice Completo](INDEX.md)
- [Roadmap Detalhado](NEXT_STEPS.md)
- [Integração](INTEGRATION_MAP.md)

---

## 💡 Dicas Rápidas

### Para Entender um Cenário
```bash
python -c "
from scenarios.scenario_specs import get_scenario_spec
spec = get_scenario_spec('NET-03')
print('Acceptance Criteria:')
for i, c in enumerate(spec.acceptance_criteria, 1):
  print(f'  {i}. {c}')
"
```

### Para Ver Violações de um Template
```bash
python -c "
from validation.checkov_validator import CheckovValidator
v = CheckovValidator()
r = v.validate_template('templates/bicep/net-03-nsg-security.bicep', 'NET-03')
print('Security Violations:', r.security_violations)
print('Policy Violations:', r.policy_violations)
"
```

### Para Modificar Configuração
```python
# src/network_simulation/configuration/
ExperimentConfig:
  - phase: "pilot" | "main"
  - scenarios: ["NET-01", "NET-02", ...]
  - max_iterations: 10

LLMConfig:
  - provider: "openai" | "anthropic" | "azure"
  - model_name: "gpt-4"
  - temperature: 0.3  # Para determinismo
```

---

## 📱 Comandos Úteis

```bash
# Listar templates
Get-ChildItem templates/bicep/*.bicep

# Contar linhas de código
Get-Content main.py, src/network_simulation/configuration/*.py | Measure-Object -Line

# Ver tamanho dos relatórios
Get-ChildItem reports/*.json | Format-Table Name, @{Name="Size(KB)"; Expression={[math]::Round($_.Length/1KB, 2)}}

# Extrair estatísticas do JSON
Get-Content reports/stage3_analysis.json | ConvertFrom-Json | Select-Object -ExpandProperty hypothesis_support

# Buscar um cenário na documentação
Get-ChildItem docs/ | Select-String -Pattern "NET-05"
```

---

## 🏆 Checklist de Verificação

### Após Clonar/Preparar
- [ ] Python 3.10+ instalado
- [ ] `cd network-simulation`
- [ ] `requirements.txt` disponível
- [ ] `main.py` presente

### Antes de Executar
- [ ] Checkov instalado (próxima iteração)
- [ ] LLM config preparada (próxima iteração)
- [ ] `reports/` diretório pronto
- [ ] Permissões de escrita OK

### Depois de `python main.py`
- [ ] stage1_baseline_validation.json gerado
- [ ] experiment_*.json gerado
- [ ] stage3_analysis.json gerado
- [ ] Nenhum erro fatal nos logs

---

## 📞 Contatos

| Papel | Responsável |
|-------|------------|
| Arquitetura POC | Andrey Victor Justo |
| Pesquisa | Andrey Victor Justo |
| LLM Integration | TBD |
| DevOps/Infra | TBD |

---

**Última Atualização**: 2026-09-05  
**Versão**: 0.1.0  
**Impresso**: [Data]
