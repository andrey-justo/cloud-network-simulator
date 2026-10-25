# Integração: coding-tool-reasoning → network-simulation

**Data**: 2026-09-05  
**Objetivo**: Demonstrar como a POC de Network Simulation se integra com o projeto principal

---

## 🏗️ Arquitetura Geral

```
┌─────────────────────────────────────────────────────────────────┐
│                    PROPOSTA ORIGINAL (PDF)                      │
│   IA Assistida para IaC na Avaliação de Configurações de Rede  │
│                        no Azure                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────┴─────────┐
                    ↓                   ↓
         ┌──────────────────┐  ┌──────────────────┐
         │  Projeto Atual   │  │  POC Estrutura   │
         │  (coding-tool-   │  │ (network-sim-    │
         │   reasoning)     │  │  ulation)        │
         │                  │  │                  │
         │ ✅ MCP Server    │  │ ✅ Experimento   │
         │ ✅ Supervisor    │  │ ✅ Validação     │
         │ ✅ Code Quality  │  │ ✅ Métricas      │
         │ ✅ C# Focus      │  │ ✅ IaC Focus     │
         └──────────────────┘  └──────────────────┘
                    ↓                   ↓
         Refatoração C# Leg.   Geração Bicep
         com Supervisor Agent  com Validação
```

---

## 📂 Dois Workspaces Complementares

### **Workspace 1: coding-tool-reasoning** (Projeto Principal)

**Localização**: `C:\Users\Andrey Victor Justo\workspace\coding-tool-reasoning`

**Foco**: Supervisor Agent para modernização de código C# legado

**Componentes**:
- ✅ MCP Server (`src/mcp/swe_mcp_server.py`)
- ✅ Supervisor Agent com knowledge base (`src/business_logic/`)
- ✅ Métricas de qualidade de código (`src/evaluation/`)
- ✅ Framework de experimentos (`src/experiments/issue_mcp_experiment.py`)

**Pesquisa**: RQ1-RQ4 sobre refatoração assistida por IA com supervisão

### **Workspace 2: network-simulation** (POC - Nova)

**Localização**: `C:\Users\Andrey Victor Justo\workspace\network-simulation`

**Foco**: POC de validação automatizada em IaC de rede Azure

**Componentes**:
- ✅ Templates Bicep (NET-01 a NET-10)
- ✅ Integração Checkov
- ✅ Framework de experimentos B1 vs T1
- ✅ Análise de métricas

**Pesquisa**: Proposta IaC Azure - IA com validação automatizada

---

## 🔗 Pontos de Integração

### 1. **Reutilização de Padrões de Experimento**

**Do projeto principal** → **POC network-simulation**

| Padrão | coding-tool-reasoning | network-simulation |
|--------|----------------------|-------------------|
| Estrutura de experimento | `src/evaluation/experiment_metrics.py` | ✅ Adaptada para IaC |
| Métricas estruturadas | Dataclasses + JSON | ✅ Reutilizado |
| Teste de hipóteses | RQ2/RQ3/RQ4 | ✅ H1/H2/H3 |
| Comparação pareada | B0 manual vs supervisado | ✅ B1 vs T1 |
| Auditoria | Execution traces | ✅ Relatórios JSON |

### 2. **Componentes que Poderiam Ser Reutilizados**

#### A. **Supervisor Agent Core** (do projeto principal)
Potencialmente adaptável para IaC:
```python
# De: src/service/swe_knowledge_base_service.py
# Adaptar: Knowledge base de patterns IaC/Bicep/NSG/Conectividade
```

#### B. **MCP Server Extensão**
```python
# De: src/mcp/swe_mcp_server.py
# Adicionar: Tools para validação Bicep, geração templates, análise Checkov
```

#### C. **Metrics Framework**
```python
# De: src/evaluation/experiment_metrics.py
# Reutilizar: Estrutura de métricas, agregação, estatísticas
```

### 3. **Fluxo de Integração Potencial**

```
User Request (IaC Azure)
        ↓
MCP Server Extended
(+ IaC Tools)
        ↓
Supervisor Agent
(IaC Knowledge Base)
        ↓
   ┌────┴────┐
   ↓         ↓
LLM → Validate
   ↓         ↓
Generate ← Feedback
Template   (Checkov)
   ↓
Export Metrics
& Results
```

---

## 🎯 Roadmap de Integração

### **Phase 1: POC Completa** (Atual - Semanas 1-2)
- ✅ Estrutura e templates básicos
- ✅ Validação Checkov
- ✅ Framework de experimentos
- ⏳ Execução pilot (simulated)

### **Phase 2: Integração com LLM** (Semanas 2-4)
- 📋 Conectar com OpenAI/Anthropic/Azure
- 📋 Implementar geração B1 (sem validação)
- 📋 Implementar geração T1 (com validação iterativa)
- 📋 Prompt engineering dedicado

### **Phase 3: Reutilização de Código** (Semanas 4-6)
- 📋 Adaptar Supervisor Agent do projeto principal
- 📋 Estender MCP Server com tools IaC
- 📋 Unificar framework de métricas
- 📋 Sincronizar relatórios e auditoria

### **Phase 4: Experimento Pilot** (Semanas 6-8)
- 📋 Dados reais de geração LLM
- 📋 2-3 cenários pilot (NET-01, NET-02, NET-03)
- 📋 Análise estatística
- 📋 Relatório de resultados

### **Phase 5: Experimento Main** (Semanas 8-12)
- 📋 6+ cenários progressivos
- 📋 Comparação B1 vs T1 completa
- 📋 Análise de falhas por tipo
- 📋 Benchmark público

---

## 💾 Estrutura de Dados Unificada

Ambos os workspaces usam a mesma estrutura de dados para compatibilidade:

### **Experiment Metadata** (Unificado)
```python
@dataclass
class ExperimentRun:
    experiment_id: str           # ID único
    experiment_phase: str        # "pilot" | "main"
    research_domain: str         # "code-refactoring" | "iac-network"
    run_date: datetime
    llm_model: str              # "gpt-4", "claude-3", etc
    scenarios_tested: List[str]  # ["NET-01", "NET-02"] ou ["issue-123"]
    metrics: Dict               # Estrutura comum
    hypothesis_tests: Dict      # H1, H2, H3, RQ1, RQ2, etc
```

### **Metrics Structure** (Comum)
```
Violation Rate / Code Smell Rate
Acceptance Rate / Quality Rate
Iterations to Acceptance
Time to Completion
Hypothesis Support %
```

---

## 🔐 Considerações de Segurança & Conformidade

| Aspecto | coding-tool-reasoning | network-simulation |
|--------|----------------------|-------------------|
| API Keys | .env + Environment vars | Environment variables + configuration/llm.py |
| Logs | MCP server logs | JSON reports + logs |
| Auditoria | Execution traces | Templates + metrics |
| Privacy | No telemetry extra | Dados síntéticos para POC |

---

## 📊 Comparativo: Dois Projetos

| Aspecto | Projeto Principal | POC Network |
|--------|------------------|------------|
| **Domínio** | Modernização de código C# | Geração IaC Azure |
| **RQ** | RQ1-RQ4 code quality | H1-H3 validation impact |
| **Condições** | Baseline manual vs supervisado | B1 (sem validação) vs T1 (com) |
| **Métricas Primárias** | Estrutura SOLID / Complexity | Violações / Aceitação / Iterações |
| **Framework LLM** | MCP server + supervisor | Direct LLM calls + validator |
| **Estado** | Em desenvolvimento | POC executada ✅ |

---

## 🚀 Como Usar Esta POC

### 1. **Para Entender a Proposta**
```bash
cd network-simulation
cat docs/POC_GUIDE.md
cat scenarios/scenario_specs.py  # Ver 10 cenários + acceptance criteria
```

### 2. **Para Executar a POC**
```bash
# Terminal PowerShell
cd "c:\Users\Andrey Victor Justo\workspace\network-simulation"
python main.py
# Gera: reports/stage*.json
```

### 3. **Para Estender com Seu Próprio LLM**
```python
# Adaptar main.py stage_2_simulate_experiment()
# Substituir simulação por:
# - Chamar OpenAI/Anthropic API
# - Gerar template Bicep real
# - Validar com Checkov
# - Iterar até aceitar (T1)
```

### 4. **Para Integrar com coding-tool-reasoning**
```python
# Usar classes de experiment_runner.py
# Sincronizar com src/evaluation/experiment_metrics.py
# Reutilizar MCP server registration pattern
```

---

## 📋 Checklist de Verificação

- ✅ Estrutura de 2 workspaces clara
- ✅ POC executada e relatórios gerados
- ✅ Componentes principais implementados
- ✅ Documentação e guias criados
- ✅ Padrões reutilizáveis identificados
- ⏳ Próximo: Integração com LLM real

---

## 📞 Questões para Próximas Etapas

1. **LLM Selection**: Qual modelo preferir? (GPT-4, Claude-3, ou híbrido?)
2. **Prompt Strategy**: Como estruturar prompts para B1 vs T1?
3. **Checkov Customization**: Quais rules customizadas adicionar?
4. **OPA Integration**: Implementar políticas OPA/Rego agora ou depois?
5. **Timeline**: Quando iniciar experimento pilot com dados reais?

---

**Próximo Encontro**: Discutir Phase 2 (Integração com LLM real)
