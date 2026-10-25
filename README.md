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
- `src/network_simulation/prompts/`: prompts de geracao incluidos no pacote.
- `scripts/`: automacoes de setup e execucao.
- `src/network_simulation/`: pacote Python de orquestracao.
- `tests/`: testes iniciais.

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
and `gpt-6.1-sol`, using Microsoft Entra authentication through the Azure CLI.
The pilot has five exploratory repetitions over all ten scenarios, capped at
900 physical model calls; it has not been executed. Install the optional
authentication SDK with `pip install -e '.[dev,azure-auth]'` and follow the
[readiness checklist](GOING_LIVE_CHECKLIST.md) before authorizing any paid call.

## Legacy quick start

### 1. Criar e ativar o ambiente virtual

Use sempre o ambiente local `.venv` para manter a configuração reproduzível e consistente com o restante do projeto.

```powershell
.\scripts\bootstrap.ps1
.\.venv\Scripts\Activate.ps1
```

> Se o ambiente já existir, basta ativá-lo com ` .\.venv\Scripts\Activate.ps1 `.

O script instala as dependencias e o pacote editavel em `.venv`, sem depender
da ativacao. Instale Python 3.11 antes de executa-lo:

```powershell
winget install -e --id Python.Python.3.11 --scope user --silent
```

Para outra instalacao, use `.\scripts\bootstrap.ps1 -PythonExecutable 'C:\caminho\python.exe'`.
Para testar sem ativar: `.\.venv\Scripts\python.exe -m pytest -q`.

### 2. Listar cenarios disponiveis

```powershell
python -m network_simulation.main --list-scenarios
```

### 3. Gerar um manifesto de execucao

```powershell
python -m network_simulation.main --config configs/experiment.example.yaml --dry-run
```

### 4. Gerar e validar artefatos de experimento

Configure o modelo e os validadores conforme o [guia da POC](docs/POC_GUIDE.md), depois execute:

```powershell
python main.py --mode live --scenario NET-01 --output-dir results/live
```

Cada iteracao preserva `response.txt`, `template.bicep`, ARM compilado e relatorios
sob `results/live/<run-id>/scenarios/<scenario>/<B1-ou-T1>/iteration-<numero>/`.
Trate os arquivos gerados como evidencias: nao os corrija manualmente; uma
correcao deve ser uma nova iteracao rastreavel. A validacao ocorre depois da
geracao, e seus resultados ficam disponiveis para extracao posterior de metricas.
O pipeline ainda nao automatiza a aceitacao completa dos cenarios.

As especificacoes com `extends` sao resolvidas antes da geracao. Cada cenario
preserva as fontes originais em `sources/`, seus hashes e o contexto resolvido
em `specification.yml`; todas as tentativas recebem esse contexto completo.
Um Checkov com erro de execucao, JSON invalido, erros de parsing ou nenhum
check executado nunca conta como validacao aprovada.

`python main.py --mode simulated` usa apenas dados sinteticos; nao gera Bicep
nem valida um baseline manual B0. Os antigos arquivos em `templates/bicep`
foram removidos por nao constituirem referencias verificadas.

## Configuracao e instalacao

`POCConfig.save_yaml()` e `POCConfig.load_yaml()` preservam as configuracoes
experimentais, do modelo, dos validadores e dos prompts. O carregamento aceita
as chaves antigas (`phase`, `scenarios`, `model`, `checkov`, `opa`) e rejeita
tipos ou configuracoes desconhecidas. As chaves de API nao sao salvas; obtenha
credenciais do ambiente antes de criar um cliente.

`max_tokens` e enviado como `max_output_tokens` (padrao: 2000).
`temperature` e `top_p` ficam desativados por padrao (`null`); este cliente
somente aceita esses controles de amostragem para `gpt-4o`. Configura-los para
os modelos de raciocinio gera um erro explicito. Respostas incompletas sao
registradas como falhas de geracao, nao como templates completos.

Prompts e o adaptador Checkov fazem parte do wheel. O caminho instalado e
`network_simulation.validation.checkov_validator`; o antigo modulo
`validation.checkov_validator` continua disponivel no checkout como wrapper.
Checkov e uma ferramenta opcional: instale as dependencias de `requirements.txt`
quando quiser executar esses checks. Uma configuracao com Checkov desabilitado
nao exige sua instalacao.

A estrategia CLI respeita `cwd` e `env`. Binarios nativos recebem argumentos
diretamente; comandos internos usam o quoting do shell selecionado. Um comando
com retorno nao zero nao e repetido em outro shell.

Os relatorios calculam H3 pelo tempo observado, nao pela quantidade de
iteracoes. Tentativas sem convergencia usam `null` para iteracoes ate aceitacao
e ficam fora da comparacao de eficiencia; se nao houver pares convergentes,
H3 e a reducao de iteracoes ficam indefinidos.

## Referencias externas de IaC

- [Azure Verified Modules](https://github.com/Azure/bicep-registry-modules):
  referencia principal para modulos Bicep, incluindo recursos de rede.
- [Azure Quickstart Templates](https://github.com/Azure/azure-quickstart-templates):
  exemplos de topologias e implantacoes; precisam de avaliacao por cenario.

Esses repositorios sao referencias de projeto, nao resultados do experimento
nem baselines aceitos automaticamente. Antes de adotar um exemplo como B0,
registre URL, commit ou versao, licenca, parametros e cenario; compile e valide
o artefato com o mesmo protocolo dos resultados gerados. Mantenha eventuais
referencias locais separadas dos prompts e das saidas, por exemplo em
`references/`, somente quando uma selecao for revisada. Nenhum exemplo externo
foi importado, e as referencias nao sao injetadas nos prompts B1/T1.

## Next research milestone

Review the [controlled protocol](docs/STUDY_PROTOCOL.md), run local catalog
validation, and prepare operator-owned external fixtures in a disposable Azure
subscription. After explicit budget approval, use a pilot to determine the
main-study replication and analysis plan. No empirical hypothesis is confirmed
by the synthetic reports or software regression tests.

## Observacao sobre Windows

Para emulacao real com Mininet/Containernet, o caminho mais seguro e usar:

- WSL2 com Ubuntu; ou
- container Linux dedicado.

Mesmo sem essa camada, este repositorio ja permite organizar cenarios, validacoes e metricas sem travar a pesquisa no ambiente local.
