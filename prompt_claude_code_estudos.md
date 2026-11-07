# Prompt para o Claude Code: plataforma de estudos exaustivos

> Cola tudo o que está abaixo da linha numa sessão nova do Claude Code, numa pasta vazia.
> Recomendo começar em modo de planeamento e só passar a execução depois de aprovares o plano.

---

## Objetivo

Constrói, nesta pasta, uma plataforma local para produzir e publicar uma série de estudos exaustivos com dados sobre Portugal. Cada estudo nasce de um comando `/estudo <tema>` e acrescenta uma página bilingue (PT e EN) a um site estático e interativo. O primeiro estudo será "A saúde em Portugal".

Trabalho sozinho, em Python, num MacBook. Tudo corre localmente. Antes de escrever código, apresenta-me um plano com a estrutura de pastas, as dependências e as decisões em aberto, e espera pela minha aprovação.

## Princípios que nunca podem ser quebrados

1. **Nenhuma afirmação sem fonte.** Cada número, facto ou evento no relatório tem de existir em `afirmacoes.csv`, com URL, data de acesso e um excerto curto (menos de 15 palavras) que o sustente.
2. **Fontes primárias primeiro.** Dados: INE, Eurostat, OCDE, OMS, DGS, SNS e organismos oficiais. Eventos: Diário da República, parlamento.pt, EUR-Lex, CNE e sites do Governo. Notícias de órgãos credíveis (Lusa, Público, Expresso, Observador, RTP, Reuters, por exemplo) só servem para contexto ou quando não há fonte primária, e ficam marcadas como tal.
3. **Coincidência não é causalidade.** Um evento só pode ser apresentado como causa de uma mudança de tendência se uma fonte (estudo, relatório oficial ou análise credível) o afirmar. Caso contrário, é apresentado como "coincide temporalmente com" e o grau de evidência fica explícito.
4. **Verificação independente.** Quem escreve não verifica. Um agente verificador separado abre cada URL e confirma que o excerto e a data existem na página.
5. **Direitos de autor.** Paráfrase sempre. Citações literais só curtas, no máximo uma por fonte, sempre atribuídas.
6. **Reprodutibilidade.** Todo o gráfico é gerado a partir de dados guardados no repositório, por código, nunca à mão.

## Estrutura do repositório

Propõe e cria algo próximo disto:

```
estudos/
├── CLAUDE.md                     # regras acima + convenções do projeto
├── .claude/
│   ├── agents/                   # subagentes (ver abaixo)
│   └── skills/estudo/SKILL.md    # o fluxo do /estudo <tema>
├── eventos/
│   ├── eventos.csv               # catálogo partilhado entre todos os estudos
│   └── fontes_eventos.md         # que fontes primárias usar por tipo de evento
├── estudos/
│   └── <slug-do-tema>/
│       ├── plano.md              # perguntas, eixos, âmbito, decisões
│       ├── fontes.csv            # catálogo de fontes de dados, com estado de verificação
│       ├── dados/raw/            # ficheiros originais, intactos, com data
│       ├── dados/clean/          # formato longo normalizado (parquet)
│       ├── analise/              # notebooks ou scripts por eixo
│       ├── quebras.csv           # mudanças de tendência detetadas
│       ├── ligacoes_eventos.csv  # quebras ↔ eventos, com grau de evidência
│       ├── afirmacoes.csv        # todas as afirmações do relatório e a sua fonte
│       ├── verificacao.md        # relatório do verificador
│       └── relatorio.pt.qmd / relatorio.en.qmd
├── site/                         # projeto Quarto (website bilingue)
├── servidor/                     # FastAPI local que lança o Claude Code
└── comum/                        # funções partilhadas: geografia, normalização, gráficos
```

## Subagentes (`.claude/agents/`)

Cria estes subagentes, cada um com ferramentas limitadas ao que precisa e uma descrição clara de quando é usado:

| Subagente | Faz | Escreve em |
| --- | --- | --- |
| `planeador` | Define perguntas de investigação, eixos, âmbito temporal e geográfico | `plano.md` |
| `pesquisador-dados` | Procura datasets, confirma acesso, formato, licença e cobertura | `fontes.csv` |
| `extrator` | Descarrega, guarda o original e normaliza para formato longo | `dados/` |
| `analista` | Analisa cada eixo, deteta mudanças de tendência, gera gráficos | `analise/`, `quebras.csv` |
| `historiador` | Procura eventos sociais e políticos que coincidam com cada quebra | `eventos/eventos.csv`, `ligacoes_eventos.csv` |
| `redator` | Escreve o relatório PT e EN apenas a partir de `afirmacoes.csv` e dos gráficos | `relatorio.*.qmd`, `afirmacoes.csv` |
| `verificador` | Abre cada URL, confirma excertos, datas e números; nunca edita o relatório | `verificacao.md` |

Corre em paralelo só a pesquisa e a extração. Os agentes comunicam através dos ficheiros, não da conversa.

## Eventos sociais e políticos como explicação de tendências

Esta é uma parte central dos estudos.

**Catálogo partilhado** `eventos/eventos.csv`, reutilizado e enriquecido por todos os estudos, com as colunas:

`id, data_inicio, data_fim, ambito (PT|UE|Mundo), tipo, titulo_pt, titulo_en, descricao_pt, descricao_en, fonte_primaria_url, fonte_secundaria_url, data_acesso, temas (lista), verificado (sim|não)`

Tipos mínimos: lei ou decreto-lei, orçamento do Estado, mudança de governo, eleição, diretiva ou regulamento europeu, programa ou plano nacional, crise económica ou intervenção externa, pandemia ou crise sanitária, catástrofe natural ou climática, greve ou conflito laboral, evento internacional relevante.

**Como ligar eventos a tendências:**

1. O `analista` deteta mudanças de nível, de declive ou picos em cada série relevante (por exemplo com `ruptures` ou regressão segmentada) e regista-as em `quebras.csv`: série, data, tipo de mudança, magnitude e método.
2. Para cada quebra, o `historiador` procura eventos numa janela temporal plausível, que deve justificar (uma lei pode ter efeito anos depois; uma pandemia é imediata). Primeiro consulta o catálogo, depois pesquisa.
3. Cada ligação em `ligacoes_eventos.csv` tem um grau de evidência:
   - **A:** uma fonte credível estabelece a relação (avaliação de impacto, estudo, relatório oficial).
   - **B:** mecanismo plausível e explicado por uma fonte, sem demonstração do efeito.
   - **C:** apenas coincidência temporal.
4. Também regista quebras sem evento associado e eventos relevantes sem efeito visível. Ambos são resultados.
5. O relatório usa linguagem ajustada ao grau: A permite "contribuiu para", B "pode ter contribuído", C "coincidiu com".

## Fluxo do `/estudo <tema>` (skill)

A skill recebe o tema, cria `estudos/<slug>/` e executa as fases por ordem. Cada fase termina com uma condição verificável. Usa `/goal` com essa condição quando corres uma fase de forma autónoma.

| Fase | Condição de conclusão |
| --- | --- |
| 1. Plano | `plano.md` tem 5 a 10 perguntas, cada uma com eixo e fonte candidata |
| 2. Fontes | Cada linha de `fontes.csv` tem URL, licença, cobertura, formato e estado "testada" ou o motivo de exclusão |
| 3. Extração | Cada fonte testada tem original em `raw/` e versão normalizada em `clean/`; totais batem com os publicados |
| 4. Análise | Cada pergunta tem pelo menos um gráfico e `quebras.csv` está preenchido |
| 5. Eventos | Cada quebra tem pelo menos uma ligação ou a nota "sem evento identificado" |
| 6. Redação | Relatório PT e EN completos; cada afirmação está em `afirmacoes.csv` |
| 7. Verificação | `verificacao.md` sem falhas pendentes; afirmações falhadas foram corrigidas ou removidas |
| 8. Publicação | O site compila sem erros e a página nova aparece no índice, nas duas línguas |

No fim de cada fase, faz commit em git com uma mensagem que diga a fase e o tema.

## Site (Quarto, bilingue)

- Website Quarto com versões PT e EN e um seletor de língua em todas as páginas.
- Página inicial: lista de estudos, gerada automaticamente a partir das pastas em `estudos/`, com título, data, resumo e estado.
- Página de cada estudo:
  - Resumo com as principais conclusões no topo.
  - Gráficos interativos (Plotly ou Observable JS), com filtros por região, sexo, idade e período quando os dados o permitem.
  - **Linha temporal de eventos** sobreposta às séries, com marcadores por âmbito e grau de evidência; ao passar o rato aparece o evento e a fonte.
  - Secção de metodologia, limitações e lista completa de fontes com links.
  - Botão para descarregar os dados limpos.
- Uma página "Eventos" com o catálogo completo, filtrável por tipo, âmbito, tema e período.
- Design sóbrio e legível, adequado a um portfólio profissional. Acessível e a funcionar em telemóvel.

## Servidor local e comando no site

- Aplicação FastAPI que serve o site e expõe `POST /api/estudos` com `{ "tema": "..." }`.
- O endpoint lança o Claude Code em modo não interativo nesta pasta, com o prompt `/estudo <tema>`, e transmite o progresso para o browser (por exemplo com Server-Sent Events). Confirma as opções exatas com `claude --help` antes de as usar.
- No site, uma caixa de texto onde escrevo `/estudo <tema>` e uma vista de progresso por fase. Quando o estudo termina, o site é recompilado e a página nova fica disponível.
- Regras de segurança:
  - O servidor só escuta em `127.0.0.1`.
  - O tema é validado: texto simples, tamanho máximo, sem caracteres de shell; nunca é concatenado num comando de shell.
  - As ferramentas permitidas ao Claude Code são limitadas ao necessário.
  - Um só estudo a correr de cada vez; os seguintes ficam em fila.
  - Cada execução fica registada em `logs/` com o tema, a hora e o resultado.

## Primeira execução

Depois de a plataforma estar montada e testada com um tema curto de teste, corre `/estudo saude-portugal`. Usa como ponto de partida o plano que já fiz (eixos: mortalidade, cancro, fatores de risco, atividade do SNS, recursos, medicamento, financiamento, desigualdades e choques), mas verifica de novo todas as fontes.

## Como quero que trabalhes

- Começa pelo plano e espera pela minha aprovação.
- Pergunta-me antes de qualquer decisão difícil de reverter.
- Se uma fonte não estiver acessível, regista-o e continua; não inventes dados nem links.
- No fim de cada fase, dá-me um resumo curto: o que foi feito, o que falhou e o que precisa de mim.
- Código, nomes de ficheiros técnicos e comentários em inglês; relatórios e comunicação comigo em português.
