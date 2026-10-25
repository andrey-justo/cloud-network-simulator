# Network Simulation

Repositorio-base para uma proposta de pesquisa em Infra + LLM e Infrastructure as Code (IaC), com foco em geracao, validacao e refinamento de configuracoes em cenarios parametrizados.

## Objetivo inicial

Este repositorio comeca pela camada de orquestracao experimental:

- definicao versionada de cenarios;
- manifestos de execucao;
- coleta padronizada de resultados;
- suporte a comparacao entre geracao manual, assistida por LLM e validacao automatizada.

A decisao e proposital: a emulacao de rede nao e o foco principal da proposta, mas pode ser usada como apoio metodologico em etapas especificas. Primeiro estruturamos o pipeline de geracao e validacao; depois conectamos, quando necessario, um backend de execucao ou de experimentacao.

## Estrutura

- `configs/`: configuracoes do experimento.
- `scenarios/`: cenarios de rede em YAML.
- `results/`: saida das execucoes.
- `scripts/`: automacoes de setup e execucao.
- `src/network_simulation/`: pacote Python de orquestracao.
- `tests/`: testes iniciais.

## Quick Start

### 1. Criar e ativar o ambiente virtual

Use sempre o ambiente local `.venv` para manter a configuração reproduzível e consistente com o restante do projeto.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

> Se o ambiente já existir, basta ativá-lo com ` .\.venv\Scripts\Activate.ps1 `.

### 2. Listar cenarios disponiveis

```powershell
python -m network_simulation.main --list-scenarios
```

### 3. Gerar um manifesto de execucao

```powershell
python -m network_simulation.main --config configs/experiment.example.yaml --dry-run
```

### 4. Validar templates com Checkov

O CLI do Checkov é instalado como executável no ambiente virtual, então use o comando direto:

```powershell
checkov -d templates/bicep --framework bicep --quiet
```

Se o comando falhar, confirme que o ambiente virtual foi ativado e que o pacote foi instalado com `python -m pip install -r requirements.txt`.

## Proximo passo tecnico recomendado

1. Definir 3 cenarios-base em `scenarios/`.
2. Estruturar validacao explicita de IaC e configuracoes geradas.
3. Adicionar comparacao entre geracao manual, LLM e iteracao com feedback.
4. Usar emulacao ou simulacao apenas quando ela ajudar a avaliar conectividade, isolamento ou deployability.

## Observacao sobre Windows

Para emulacao real com Mininet/Containernet, o caminho mais seguro e usar:

- WSL2 com Ubuntu; ou
- container Linux dedicado.

Mesmo sem essa camada, este repositorio ja permite organizar cenarios, validacoes e metricas sem travar a pesquisa no ambiente local.
