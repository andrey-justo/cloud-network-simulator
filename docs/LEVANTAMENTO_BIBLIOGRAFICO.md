# Levantamento bibliográfico

## Título

Levantamento bibliográfico sobre Infrastructure as Code, segurança em nuvem e geração, validação e refinamento com modelos de linguagem

## Autor

Andrey Victor Justo

## Introdução

O problema original deste trabalho está relacionado à geração, validação e refinamento de configurações de infraestrutura em cenários complexos, com especial atenção a critérios de segurança, consistência, deployability e reprodutibilidade experimental. A proposta parte da necessidade de comparar estratégias de geração manual e assistida por modelos de linguagem, bem como de avaliar em que medida mecanismos automáticos de validação e correção reduzem erros e tornam a infraestrutura mais confiável.

A revisão bibliográfica apresentada a seguir não tem o objetivo de constituir uma revisão sistemática da literatura, mas de sustentar conceitualmente a proposta e delimitar o problema de pesquisa. Ela funciona como base de fundamentação para posicionar a contribuição do trabalho em relação ao estado da arte, sem deslocar o foco principal para uma análise exaustiva da literatura.

Por isso, os trabalhos foram organizados em três eixos temáticos: (i) validação e segurança de infraestrutura em nuvem; (ii) geração, reparo e benchmark de IaC com LLMs; e (iii) apoio metodológico de redes programáveis e emulação apenas quando necessário para testar conectividade, isolamento ou comportamento de implantação. Essa estrutura permite compreender os fundamentos conceituais da proposta sem superestimar a importância da emulação de redes como eixo principal.

## 1. Apoio metodológico em redes programáveis e emulação experimental

Uma parte da literatura de redes programáveis e emulação experimental pode ser usada como apoio metodológico, especialmente quando o experimento exigir avaliação de conectividade, isolamento ou comportamento de implantação em um ambiente controlado. Essa literatura não constitui o foco central da proposta, mas ajuda a fundamentar o uso de cenários parametrizados e de validações reproduzíveis.

Os trabalhos clássicos de McKeown et al. (2008), Lantz, Heller e McKeown (2010), Kreutz et al. (2015) e Bosshart et al. (2014) continuam úteis para justificar a importância de controlar topologias, políticas e comportamento da rede em um ambiente experimental. Contudo, nesta proposta, eles devem ser lidos como suporte ao pipeline de geração e validação de IaC, e não como o tema principal da pesquisa.

## 2. Segurança, virtualização e infraestrutura em nuvem

A segunda categoria de trabalhos preocupa-se com a segurança de infraestrutura em ambientes cloud, incluindo virtualização, isolamento de recursos, políticas de acesso e conformidade. Essa linha é central para o projeto porque ele não se limita à criação de topologias, mas também considera se a configuração gerada atende a requisitos de segurança, segmentação e governança operacional. Em cenários complexos, falhas de isolamento e regras inadequadas podem comprometer tanto a conectividade quanto a segurança da solução.

Subashini e Kavitha (2011), Fernandes et al. (2014), Hashizume et al. (2013) e Takabi et al. (2011) são referências centrais para a análise de ameaças, vulnerabilidades e desafios de segurança em modelos de computação em nuvem. Adicionalmente, Chowdhury e Boutaba (2013), Fischer et al. (2013) e Mijumbi et al. (2016) reforçam o papel da virtualização e da orquestração em redes e infraestruturas compartilhadas. Esses estudos são particularmente relevantes para o presente trabalho, pois a geração automática de configurações de rede precisa ser avaliada não apenas em termos de sintaxe e conectividade, mas também em termos de isolamento, conformidade e segurança de implantação.

## 3. Geração, reparo e validação de IaC com LLM

A terceira categoria de referências é a mais diretamente relacionada ao problema proposto e reflete a literatura emergente sobre geração e validação de infraestrutura como código (IaC) mediada por grandes modelos de linguagem. Essa linha aborda a questão de como modelos de linguagem podem produzir, corrigir e validar templates de infraestrutura, de modo a reduzir erros de configuração e melhorar a segurança e a implantabilidade.

O material preliminar identifica IaC-Eval e TerraRepair como candidatos relevantes, mas seus dados bibliograficos e resultados precisam de verificacao nas fontes primarias antes de fundamentar a proposta. O trabalho verificado de Palavalli e Santolucito (2024), [Using a Feedback Loop for LLM-based Infrastructure as Code Generation](https://arxiv.org/abs/2411.19043), ja investiga geracao e reparo iterativo com diagnosticos de cfn-lint. Portanto, a existencia de um loop de feedback nao constitui novidade deste projeto.

Além desses, estudos como "Does Fixing Break Security? An Empirical Study of Security Degradation in Iterative LLM-Driven Infrastructure-as-Code Repair" (Agyekum e Santos, 2025), "Compared to What? A Human-Anchored Security Benchmark for LLM-Generated Infrastructure-as-Code" (Shaw, 2025), "Deployability-Centric Infrastructure-as-Code Generation" (Zhang et al., 2026), "AIaCGateGuard" (Vargas et al., 2026) e "LLM Agentic Workflow for Automated Vulnerability Detection and Remediation in Infrastructure-as-Code" (Toprani e Madisetti, 2025) mostram que a área está madura o bastante para tratar os problemas de segurança de forma quantitativa, com benchmarks, validação por ferramentas e loops de reparo. O artigo de "Repairing Infrastructure-as-Code using Large Language Models" (Low, Cheh e Chen, 2024) e "Evaluating Language Models on Infrastructure-as-Code Development" (Tarasova et al., 2026) complementam essa visão ao demonstrar que a geração de IaC com LLMs não é apenas uma questão de sintaxe, mas também de capacidade de adaptação, qualidade de revisão e robustez em cenários reais.

Esses trabalhos são especialmente importantes para o projeto porque ilustram a tendência de usar LLMs não apenas para geração inicial, mas para validação, reparo iterativo, benchmark e fiscalização de segurança em infraestrutura. Nesse sentido, a proposta do presente trabalho se encaixa como uma extensão experimental dessa linha, combinando especificação de cenários, geração automatizada e mecanismos de verificação estruturada.

## 4. Gap de pesquisa e contribuição do trabalho

A revisão bibliográfica revela que, embora haja literatura bem estabelecida em segurança de nuvem, validação de infraestrutura e geração de artefatos com LLM, ainda existe fragmentação entre geração, reparo, avaliação de segurança e deployability. A literatura clássica de redes só entra aqui como apoio metodológico quando a validação exigir um ambiente controlado de conectividade ou isolamento.

Nao se afirma ausencia geral de frameworks reprodutiveis de geracao, validacao e reparo. A contribuicao candidata e um benchmark de redes Azure/Bicep com criterios independentes, controles de orcamento e medicao separada de estrutura, politicas, deployability e conectividade. A novidade desse recorte ainda exige comparacao sistematica com fontes primarias. O [protocolo controlado](STUDY_PROTOCOL.md) define as condicoes, limites e analise exploratoria; a comparacao humana B0 e opcional, nao uma referencia presumida.

Em termos especificos, o projeto pretende medir o valor adicional dos diagnosticos contra refinamento cego partindo do mesmo candidato, usando criterios estruturais independentes e observacoes de implantacao e rede quando habilitadas. Testes de software e resultados sinteticos nao constituem evidencia empirica das hipoteses.

## 5. Direcionamento final da proposta

O recorte adotado e a avaliacao controlada do valor adicional de diagnosticos para redes Azure/Bicep, com orcamento comparavel, candidato inicial compartilhado e aceitacao independente. Um pipeline reprodutivel viabiliza o estudo, mas nao basta como alegacao de novidade. A bibliografia de redes permanece como suporte a observacoes de conectividade e isolamento; a contribuicao empirica depende de execucoes reais e de uma analise previamente definida.

## Referências

Lista de descoberta: salvo quando explicitamente marcado como verificado,
titulo, autoria, data, URL e resultados ainda precisam de verificacao em fonte
primaria. Estes registros nao sustentam, por si so, as alegacoes de maturidade,
ausencia de trabalhos anteriores ou confirmacao das hipoteses.

- AGYEKUM, Benjamin; SANTOS, Fabio. Does Fixing Break Security? An Empirical Study of Security Degradation in Iterative LLM-Driven Infrastructure-as-Code Repair. 2025.
- BOSSHART, Pat; DALY, Dan; GIBB, Glen; et al. P4: Programming Protocol-Independent Packet Processors. ACM SIGCOMM Computer Communication Review, v. 44, n. 3, p. 87-95, 2014.
- CHEN, Ang; CHOWDHURY, Mosharaf; et al. IaC-Eval: A Code Generation Benchmark for Cloud Infrastructure-as-Code Programs. 2025.
- CHOWDHURY, N. M. M. K.; BOUTABA, Raouf. Network virtualization: A survey. IEEE Communications Surveys & Tutorials, v. 15, n. 1, p. 1-47, 2013.
- FERNANDES, Dayse; SOARES, L. Fernando; GOMES, Juliano; FREIRE, M. M.; INÁCIO, P. R. M. Security issues in cloud environments: a survey. International Journal of Information Security, v. 13, n. 2, p. 113-170, 2014.
- FISCHER, Andreas; BOTERO, Juan Felipe; BECK, Michael Till; et al. Virtual network embedding: A survey. IEEE Communications Surveys & Tutorials, v. 15, n. 4, p. 1888-1906, 2013.
- HASHIZUME, K.; ROSADO, D. G.; FERNANDEZ-MEDINA, E.; FERNANDEZ, E. B. An analysis of security issues for cloud computing. Journal of Internet Services and Applications, v. 4, artigo 5, 2013.
- KREUTZ, Diego; RAMOS, Fernando M. V.; VERISSIMO, Paulo; et al. Software-Defined Networking: A Comprehensive Survey. Proceedings of the IEEE, v. 103, n. 1, p. 14-76, 2015.
- LANTZ, Bob; HELLER, Brandon; McKEOWN, Nick. A Network in a Laptop: Rapid Prototyping for Software-Defined Networks. In: Proceedings of the 9th ACM SIGCOMM Workshop on Hot Topics in Networks, 2010.
- LOW, En; CHEH, Carmen; CHEN, Binbin. Repairing Infrastructure-as-Code using Large Language Models. 2024.
- McKEOWN, Nick; ANDERSON, Tom; BALAKRISHNAN, Hari; et al. OpenFlow: Enabling Innovation in Campus Networks. ACM SIGCOMM Computer Communication Review, v. 38, n. 2, p. 69-74, 2008.
- MENGISTU, Minase Mekete; DI ROCCO, Juri; NGUYEN, Phuong T.; DI RUSCIO, Davide. TerraRepair: A Tool-Grounded LLM Agent for Infrastructure-as-Code Repair. 2024.
- MIJUMBI, Rashid; HASEGAWA, Joan; MATA, Ken; et al. Network function virtualization: State-of-the-art and research challenges. IEEE Communications Surveys & Tutorials, v. 18, n. 1, p. 236-262, 2016.
- PALAVALLI, Mayur Amarnath; SANTOLUCITO, Mark. Using a Feedback Loop for LLM-based Infrastructure as Code Generation. 2024. [Preprint verificado](https://arxiv.org/abs/2411.19043).
- SCOTT-HAYWARD, Sandra; NAIR, Guru; SEZER, Sakir; et al. SDN security: A survey. In: Proceedings of the IEEE, v. 103, n. 1, p. 1-25, 2015.
- SHAW, Animesh. Compared to What? A Human-Anchored Security Benchmark for LLM-Generated Infrastructure-as-Code. 2025.
- SUBASHINI, S.; KAVITHA, V. A survey on security issues in service delivery models of cloud computing. Journal of Network and Computer Applications, v. 34, n. 1, p. 1-11, 2011.
- TAKABI, Hassan; JOSHI, James B. D.; AHAMED, Nalini. Security and privacy in cloud computing: A survey. IEEE Communications Surveys & Tutorials, v. 13, n. 2, p. 1-23, 2011.
- TARASOVA, Natalia; et al. Evaluating Language Models on Infrastructure-as-Code Development. 2026.
- TOPRANI, Dheer; MADISETTI, Vijay K. LLM Agentic Workflow for Automated Vulnerability Detection and Remediation in Infrastructure-as-Code. IEEE Access, 2025.
- VARGAS, Francis Luis Santos; MANSILHA, Rodrigo Brandão; KREUTZ, Diego. AIaCGateGuard: A Security-First Pipeline for Benchmarking LLM- and SLM-Generated Infrastructure-as-Code. 2026.
- ZHANG, Tianyi; PAN, Shidong; ZHANG, Zejun; XING, Zhenchang; SUN, Xiaoyu. Deployability-Centric Infrastructure-as-Code Generation: Fail, Learn, Refine, and Succeed through LLM-Empowered DevOps Simulation. 2026.

## Tabela resumida

| Trabalho | Tipo | Ligação com o projeto | Relevância |
|---|---|---|---|
| OpenFlow (McKeown et al., 2008) | Redes programáveis | Estabelece o paradigma de controle programável e teste de topologias alternativas | Alta |
| Mininet / SDN emulação (Lantz et al., 2010) | Emulação de redes | Apoia a estrutura experimental e reprodutível do projeto | Alta |
| Software-Defined Networking: A Comprehensive Survey (Kreutz et al., 2015) | SDN | Fundamenta a separação entre plano de controle e dados, relevante para cenários configuráveis | Alta |
| P4: Programming Protocol-Independent Packet Processors (Bosshart et al., 2014) | Redes programáveis | Reforça a ideia de infraestrutura de dados configurável e observável | Alta |
| A survey on security issues in service delivery models of cloud computing (Subashini & Kavitha, 2011) | Segurança em nuvem | Explicita riscos de isolamento e segurança em infraestrutura compartilhada | Alta |
| Security issues in cloud environments: a survey (Fernandes et al., 2014) | Segurança em nuvem | Reforça a importância de validadores e critérios de conformidade antes da implantação | Alta |
| IaC-Eval (Chen et al.) | LLM + IaC | Base para benchmark de geração de IaC e comparação de qualidade de artefatos | Muito alta |
| Using a Feedback Loop for LLM-based Infrastructure as Code Generation (Palavalli & Santolucito, 2024) | LLM + IaC | Fonte primaria verificada; ja cobre reparo por feedback | Muito alta |
| TerraRepair (Mengistu et al., 2024) | LLM + IaC | Exemplifica reparo guiado por contexto e ferramentas para IaC | Muito alta |
| Does Fixing Break Security? (Agyekum & Santos, 2025) | LLM + IaC + segurança | Mostra a importância de monitorar regressão de segurança em iterações | Muito alta |
| Compared to What? (Shaw, 2025) | LLM + IaC + segurança | Oferece benchmark comparativo com linha de base humana | Muito alta |
| Deployability-Centric Infrastructure-as-Code Generation (Zhang et al., 2026) | LLM + IaC + DevOps | Alineia-se ao princípio de validar deployability e não apenas sintaxe | Muito alta |
| AIaCGateGuard (Vargas et al., 2026) | LLM + IaC + segurança | Fornece pipeline automático para avaliação de conformidade | Muito alta |
| LLM Agentic Workflow for Automated Vulnerability Detection and Remediation in Infrastructure-as-Code (Toprani & Madisetti, 2025) | LLM + IaC + segurança | Reforça o uso de agentes para detecção e correção de vulnerabilidades | Muito alta |

## Subtemas e agenda de pesquisa futura

### 1. SDN, emulação e redes programáveis
Subtema dedicado aos fundamentos conceituais e experimentais das redes programáveis, incluindo prototipagem, controle e avaliação de políticas em ambientes reproduzíveis. Esse eixo continua sendo relevante para as etapas de modelagem e avaliação de topologias e cenários de rede.

### 2. Segurança e virtualização em infraestruturas cloud
Subtema voltado para segurança, isolamento de recursos, composição de políticas e validação de conformidade em ambientes virtualizados. Esse eixo sustenta a ideia de que o sistema deve verificar a infraestrutura antes de sua execução e reduzir a ocorrência de erros arquiteturais e de segurança.

### 3. Geração, reparo e benchmark de IaC com LLM
Subtema mais recente e diretamente ligado ao projeto. Ele inclui geração de templates, propostas de reparo automatizado, loops de feedback, avaliação de vulnerabilidades, benchmark de segurança e análise de deployability. Esse é o eixo principal que conecta o projeto aos trabalhos mais atuais da literatura.

### 4. Trabalhos futuros
1. Ampliar a comparação entre geração manual, geração assistida por LLM e geração com loop de validação em cenários de maior complexidade.
2. Incorporar métricas de latência, perda de pacotes e throughput em um backend realista, como Mininet em Linux/WSL2, para avaliar desempenho além da conformidade.
3. Desenvolver e padronizar benchmarks de deployability e segurança para cenários de rede em nuvem e híbrida.
4. Estender a proposta para avaliação de regressão de segurança após múltiplas iterações de correção, com foco em preservar requisitos já atendidos.
5. Integrar métricas de orquestração, provisionamento e governança de políticas em um pipeline de execução end-to-end.
6. Explorar agentes LLM com contextos de ferramenta e recuperação de informação (RAG) para correção automatizada de IaC e políticas de rede.
7. Consolidar uma base pública de cenários, com anotação de critérios de aceitação, regras de segurança e resultados reprodutíveis para comparação entre pesquisas.

Esses próximos passos ampliam a contribuição do projeto de um protótipo experimental para uma metodologia de pesquisa mais robusta e comparável com a literatura em redes, segurança de infraestrutura e IA aplicada ao IaC.
