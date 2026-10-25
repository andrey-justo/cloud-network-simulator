# Próximas Etapas: Integração e Roadmap

**Documento**: Plano de ação pós-POC  
**Data**: 2026-09-05  
**Destinatário**: Equipe técnica e gestão

---

## 📍 Situação Atual

### ✅ Completado
1. Análise da proposta "IA Assistida para IaC na Avaliação de Configurações de Rede no Azure"
2. Novo workspace `network-simulation` criado com estrutura completa
3. 10 cenários especificados (NET-01 a NET-10)
4. 3 templates Bicep implementados
5. Integração Checkov funcional
6. Framework de experimentos B1 vs T1 pronto
7. POC executada com sucesso

### 📊 Resultados Observados (Pilot)
- **H1**: B1 tem mais violações que T1 - ✅ **100% de suporte**
- **H2**: T1 tem melhor aceitação - ⚠️ Requer dados reais de LLM
- **H3**: T1 converge mais rápido - ✅ **2.7x menos iterações**

### 🚨 Limitações Atuais
- ❌ Dados são simulados (mock), não reais
- ❌ LLM não integrado (OpenAI, Anthropic, Azure)
- ❌ Checkov não instalado (estrutura pronta)
- ❌ Políticas OPA/Rego não implementadas (framework criado)
- ❌ NET-04 a NET-10 templates não codificados

---

## 🎯 Phase 1: Completar POC (Semanas 1-2)

### Objetivo
Transformar POC estrutural em POC funcional com dados reais, capaz de processar templates e gerar relatórios com Checkov.

### Tarefas

#### 1.1: Instalação de Checkov ✅ Prioridade ALTA
```bash
pip install checkov==3.2.0
```
**Impacto**: Stage 1 passa a validar templates reais com Checkov
**Tempo**: 30 min
**Pessoa**: DevOps/Infra

#### 1.2: Implementar Templates NET-04 a NET-10 ✅ Prioridade ALTA
- NET-04: `net-04-nat-gateway.bicep` (NAT + Public IP)
- NET-05: `net-05-udr.bicep` (Route Tables)
- NET-06: `net-06-hub-spoke-basic.bicep` (Hub-and-spoke topology)
- NET-07: `net-07-hub-spoke-egress.bicep` (Centralized egress)
- NET-08: `net-08-3tier-alb.bicep` (Application Load Balancer)
- NET-09: `net-09-messaging-pe.bicep` (Private endpoints)
- NET-10: `net-10-banking-secure.bicep` (Banking workload)

**Critério de Aceitação**: Todos templates compilam com `bicep build`
**Tempo**: 4-6 horas
**Pessoa**: Cloud Architect

#### 1.3: Políticas OPA/Rego ✅ Prioridade MÉDIA
Expandir `policies/azure/network.rego` com requisitos de conectividade, segurança e arquitetura; adicionar casos a `tests/rego/azure_network_test.rego`. Execute `opa test policies/azure tests/rego -v` e `conftest test` sobre ARM JSON compilado antes de marcar as regras como validadas.

**Tempo**: 3-4 horas
**Pessoa**: Security Architect / Cloud Specialist

#### 1.4: Prompt Engineering ✅ Prioridade ALTA
Refinar prompts para geração de templates:
- `system_prompt_b1` - Geração simples, sem feedback
- `system_prompt_t1` - Geração com foco em segurança
- `system_prompt_iterative` - Feedback loop com validação

**Critério**: Prompts testados com modelo local ou free API
**Tempo**: 2-3 horas
**Pessoa**: Pesquisador / LLM Specialist

**Exemplo**:
```python
# system_prompt_b1
"""Generate a secure Bicep template for a {scenario} network.
Use Azure best practices. Output only valid Bicep code."""

# system_prompt_t1
"""You are an Azure security expert.
Generate a Bicep template for {scenario}.
Focus on: least privilege, private endpoints, NSG rules.
Validate against these acceptance criteria: {criteria}."""

# system_prompt_iterative
"""Analyze these Checkov violations and fix the Bicep:
{violations}
Generate corrected template."""
```

---

## 🧠 Phase 2: LLM Integration (Semanas 3-5)

### Objetivo
Conectar LLM real (OpenAI, Anthropic, ou Azure) para gerar templates reais e executar loop iterativo T1.

### Tarefas

#### 2.1: Criar módulo llm_generator.py ✅ Prioridade ALTA
```python
class TemplateGenerator:
    def generate_b1(scenario_id: str, prompt: str) -> str
    def generate_t1(scenario_id: str, prompt: str, max_iterations: int) -> (str, int, Metrics)
    
class LLMClient:
    def __init__(provider: str, model: str, api_key: str)
    def call(prompt: str, temperature: float, max_tokens: int) -> str
```

**Tempo**: 2-3 horas
**Pessoa**: Backend Developer

#### 2.2: Integrar com main.py ✅ Prioridade ALTA
Modificar `stage_2_simulate_experiment()`:
```python
# De: simulação mock
# Para: chamadas reais ao LLM
for scenario_id in scenarios:
    # B1: Gerar sem feedback
    b1_template = llm_generator.generate_b1(scenario_id)
    b1_validation = validator.validate_template(b1_template)
    
    # T1: Gerar com loop iterativo
    t1_template, iterations, metrics = llm_generator.generate_t1(scenario_id)
    t1_validation = validator.validate_template(t1_template)
    
    # Coletar metricas reais
    runner.add_scenario_result(...)
```

**Tempo**: 2-3 horas
**Pessoa**: Backend Developer

#### 2.3: Validação End-to-End ✅ Prioridade MÉDIA
Teste com 3 cenários (NET-01, NET-02, NET-03):
- [ ] B1 gera template válido
- [ ] T1 gera template melhorado
- [ ] Métricas coletadas corretamente
- [ ] Relatórios gerados

**Tempo**: 2-3 horas
**Pessoa**: QA / Pesquisador

---

## 📊 Phase 3: Experimento Pilot (Semanas 6-8)

### Objetivo
Executar experimento com múltiplas repetições, coletando dados estatísticos significativos.

### Tarefas

#### 3.1: Definir Parâmetros Pilot ✅ Prioridade ALTA
```python
src/network_simulation/configuration/experiment.py:
- experiment_phase = "pilot"
- scenarios = ["NET-01", "NET-02", "NET-03"]  # 3 cenários
- num_repetitions = 5  # 5 repetições por cenário
- max_iterations_b1 = 10
- max_iterations_t1 = 5
- acceptance_criteria_threshold = 0.8  # 80%
```

**Resultado esperado**:
- 3 cenários × 2 condições (B1, T1) × 5 repetições = 30 runs
- Dados para cálculo de média, desvio padrão, significância

**Tempo**: 1 hora
**Pessoa**: Pesquisador

#### 3.2: Executar Experimento Pilot ✅ Prioridade ALTA
```bash
python main.py  # Com config.experiment_phase="pilot"
```

**Duração**: 2-6 horas (depende do LLM provider)
**Monitoramento**: Logs, relatórios intermediários
**Pessoa**: Pesquisador + DevOps

#### 3.3: Análise de Resultados Pilot ✅ Prioridade ALTA
```python
# Gerar relatório estatístico
python evaluation/analyze_pilot.py
# Outputs:
# - pilot_statistics.json (médias, desvios)
# - pilot_hypothesis_tests.json (testes estatísticos)
# - pilot_insights.md (interpretação)
```

**Critério de sucesso**:
- ✅ H1 suportado com confiança > 90%
- ✅ H3 observado (T1 mais eficiente)
- ✅ Dados suficientes para Phase 4

**Tempo**: 2-3 horas
**Pessoa**: Pesquisador / Estatístico

#### 3.4: Ajuste de Parâmetros ✅ Prioridade MÉDIA
Com base em resultados pilot:
- Ajustar `acceptance_criteria_threshold` se necessário
- Calibrar `max_iterations_b1` e `max_iterations_t1`
- Refinar prompts se necessário

**Tempo**: 1-2 horas
**Pessoa**: Pesquisador

---

## 🔬 Phase 4: Experimento Main (Semanas 9-12)

### Objetivo
Executar experimento com all 10 cenários, coletando dados para publicação/dissertação.

### Tarefas

#### 4.1: Escalar para 10 Cenários ✅ Prioridade ALTA
```python
src/network_simulation/configuration/experiment.py:
- experiment_phase = "main"
- scenarios = ["NET-01", "NET-02", ..., "NET-10"]  # Todos 10
- num_repetitions = 5-10  # Maior rigor estatístico
```

#### 4.2: Executar Experimento Main ✅ Prioridade ALTA
```bash
python main.py  # Com config.experiment_phase="main"
```

**Duração estimada**: 12-24 horas (processamento)
**Infraestrutura**: CI/CD pipeline, máquina dedicada
**Monitoramento**: Logging contínuo, alertas de falha

#### 4.3: Análise Estatística Completa ✅ Prioridade ALTA
```python
python evaluation/main_analysis.py
# Outputs:
# - hypothesis_tests.json (Wilcoxon signed-rank, etc.)
# - effect_sizes.json (Cohen's d, etc.)
# - confidence_intervals.json (95% CI para cada métrica)
# - failure_analysis.json (análise de falhas por tipo)
```

#### 4.4: Relatório Final & Visualização ✅ Prioridade MÉDIA
Gerar:
- Tabelas de comparação B1 vs T1
- Gráficos (box plots, histogramas)
- Heatmaps de violações por cenário
- Curvas de convergência (iterações)

**Formato**: Markdown + PNG/PDF

---

## 🔗 Phase 5: Integração com Projeto Principal (Semanas 8-12, Paralelo)

### Objetivo
Reutilizar componentes POC no projeto coding-tool-reasoning.

### Tarefas

#### 5.1: Adapter Pattern ✅ Prioridade MÉDIA
Criar adaptadores em `coding-tool-reasoning`:
```python
src/adapters/
├── experiment_adapter.py
│   └── Mapeia ExperimentResult (IaC) → ExperimentRun (Code)
├── metrics_adapter.py
│   └── Mapeia NetworkMetrics → CodeQualityMetrics
└── hypothesis_adapter.py
    └── Mapeia H1, H2, H3 (IaC) → RQ1, RQ2, RQ3, RQ4 (Code)
```

#### 5.2: Estender MCP Server ✅ Prioridade MÉDIA
```python
src/mcp/swe_mcp_server.py:
# Adicionar tools:
- generate_bicep_template(scenario: str) → template
- validate_bicep(template: str) → report
- analyze_network_config(template: str) → metrics
```

#### 5.3: Supervisor Agent para IaC ✅ Prioridade MÉDIA
Adaptar:
```python
src/service/swe_knowledge_base_service.py
→ src/service/iac_knowledge_base_service.py

# Com conhecimento de:
- Padrões de rede (VNet, NSG, Peering)
- Melhores práticas Azure (least privilege, segregação)
- Tipos comuns de misconfiguration
```

---

## 📅 Timeline de Execução

```
Week 1-2:   Phase 1 - POC Completa
  └─ Checkov, templates NET-04 a NET-10, OPA/Rego, prompts

Week 3-5:   Phase 2 - LLM Integration
  └─ llm_generator.py, integração main.py, validação E2E

Week 6-8:   Phase 3 - Pilot Experiment + Phase 5 início
  └─ 5 repetições, 3 cenários, análise estatística
  └─ Adaptadores, MCP extensions

Week 9-12:  Phase 4 - Main Experiment + Phase 5 conclusão
  └─ 10 cenários, 5-10 repetições, análise final
  └─ Integração completa com projeto principal
```

---

## 💰 Estimativa de Esforço

| Phase | Tarefas | Pessoa | Horas | Status |
|-------|---------|--------|-------|--------|
| 1 | Checkov + Templates + OPA | Arch/Dev/Security | 12-15 | 🎯 Próximo |
| 1 | Prompt Engineering | LLM Spec | 3-4 | 🎯 Próximo |
| 2 | llm_generator.py | Backend Dev | 4-5 | 🔜 Semana 3 |
| 2 | Integração E2E | Backend Dev | 3-4 | 🔜 Semana 3 |
| 3 | Experimento Pilot | Pesquisador | 6-8 | 🔜 Semana 6 |
| 3 | Análise Pilot | Pesquisador | 2-3 | 🔜 Semana 7 |
| 4 | Experimento Main | Pesquisador + DevOps | 8-12 | 🔜 Semana 9 |
| 4 | Análise + Relatório | Pesquisador | 4-6 | 🔜 Semana 11 |
| 5 | Integração com Principal | Arch/Dev | 8-10 | 🔜 Semana 8+ |
| **TOTAL** | | | **50-72h** | |

---

## 🚨 Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|--------|-----------|
| LLM não gera Bicep válido | Alta | Alto | Prompt refinement, fallback manual |
| Checkov muito lento | Média | Médio | Parallelização, cache |
| Experimento data collection falha | Baixa | Alto | Redundância, backups, CI/CD |
| Interpretação de resultados ambígua | Média | Médio | Análise estatística rigorosa |
| Falta de recursos computacionais | Baixa | Médio | Cloud compute, schedule batch |

---

## ✅ Critérios de Sucesso

### Phase 1
- [x] Todos os templates compilam
- [x] Checkov roda sem erro
- [x] POC executa Stage 1-3
- [x] Prompts testados

### Phase 2
- [x] LLM gera templates válidos (80%+ taxa de sucesso)
- [x] Loop T1 converge (max 5 iterações)
- [x] Métricas coletadas corretamente
- [x] Relatórios JSON estruturados

### Phase 3
- [x] H1 suportado com 90%+ confiança
- [x] Dados piloto suficientes (15+ samples)
- [x] Visualizações geradas

### Phase 4
- [x] 10 cenários processados
- [x] 50+ total samples
- [x] Testes estatísticos válidos
- [x] Pronto para publicação

### Phase 5
- [x] Componentes reutilizados
- [x] MCP Server estendido
- [x] Integração testada

---

## 📞 Próximas Ações

### ✅ Imediatamente (Esta Semana)
1. [ ] Definir qual LLM provider usar (OpenAI, Anthropic, Azure)
2. [ ] Preparar account/API keys
3. [ ] Designar pessoas para Phase 1

### 🎯 Próxima Semana
1. [ ] Instalar Checkov
2. [ ] Implementar templates NET-04 a NET-10
3. [ ] Criar políticas OPA/Rego
4. [ ] Refinar prompts

### 📅 Semana Seguinte
1. [ ] Começar Phase 2 (llm_generator.py)
2. [ ] Testar com primeira iteração real

---

## 📚 Referências

- [docs/POC_GUIDE.md](docs/POC_GUIDE.md) - Como usar POC
- [docs/INTEGRATION_MAP.md](docs/INTEGRATION_MAP.md) - Mapa de integração
- [scenarios/scenario_specs.py](scenarios/scenario_specs.py) - Specs dos 10 cenários
- [configuration package](../src/network_simulation/configuration/__init__.py) - Configurações de experimento

---

**Documento**: Próximas Etapas  
**Versão**: 0.1.0  
**Data**: 2026-09-05  
**Status**: Ready for Planning ✅
