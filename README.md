# studies_center

Plataforma local para produzir e publicar **estudos exaustivos, com dados, sobre Portugal**.
Cada estudo nasce de um comando (`/study <tema>`) e acrescenta uma página bilingue (PT/EN) a um
site estático Quarto, em que cada número tem fonte, excerto e data de acesso.

> **EN, in short:** a local, Claude Code–orchestrated pipeline that turns a topic into a
> bilingual, fully-sourced data study about Portugal. Seven specialised subagents run through
> eight phases, each gated by code (not by the model's judgement), with resumable on-disk state.
> The public site shows only the finished studies.

- **Site público:** publicado por GitHub Pages (ver [Publicação](#publicação))
- **Línguas:** código e nomes técnicos em inglês; relatórios e documentação de estudos em português

## Índice

1. [Princípios](#princípios)
2. [Arquitetura](#arquitetura)
3. [Stack](#stack)
4. [Orquestração: o fluxo `/study`](#orquestração-o-fluxo-study)
5. [Agentes](#agentes)
6. [Estado, retoma e limites](#estado-retoma-e-limites)
7. [Modelo de dados](#modelo-de-dados)
8. [Estrutura do repositório](#estrutura-do-repositório)
9. [Instalação e uso](#instalação-e-uso)
10. [Servidor local e fila](#servidor-local-e-fila)
11. [Publicação](#publicação)
12. [Testes](#testes)
13. [Segurança e privacidade](#segurança-e-privacidade)
14. [Licenças e atribuição de dados](#licenças-e-atribuição-de-dados)
15. [Limitações conhecidas](#limitações-conhecidas)
16. [Pontos de melhoria](#pontos-de-melhoria)

## Princípios

Nunca podem ser quebrados (detalhe em [`CLAUDE.md`](CLAUDE.md)):

1. **Nenhuma afirmação sem fonte.** Todo número, facto ou evento tem uma linha em
   `studies/<slug>/claims.csv` (URL, data de acesso, excerto com menos de 15 palavras).
2. **Fontes primárias primeiro.** INE, Eurostat, OCDE, OMS, DGS, SNS; Diário da República,
   parlamento.pt, EUR-Lex, CNE. Notícias só para contexto e marcadas `source_nature = news`.
3. **Coincidência não é causalidade.** Grau A (uma fonte afirma a causa) → "contribuiu para";
   B (mecanismo plausível documentado) → "pode ter contribuído"; C (só coincidência temporal) →
   "coincidiu com".
4. **Verificação independente.** Quem escreve (`writer`) não verifica; o `verifier` abre cada
   URL e confirma excerto, data e valor, e nunca edita o relatório.
5. **Direitos de autor.** Paráfrase sempre; no máximo uma citação literal curta por fonte.
6. **Reprodutibilidade.** Todo gráfico nasce de dados em `data/clean/`, gerado por código.

## Arquitetura

```
                    /study <tema>   (sessão Claude Code ou servidor local)
                                │
                     ┌──────────▼──────────┐
                     │  Orquestrador       │  skill .claude/skills/study
                     │  (Sonnet)           │  só despacha e lê resumos
                     └──┬────────┬─────────┘
        estado/gates    │        │  lança (máx. 2 em simultâneo)
   ┌────────────────────▼─┐   ┌──▼───────────────────────────────────┐
   │ common/state.py      │   │ Subagentes (.claude/agents/*.md)     │
   │ common/checks.py     │   │ planner · data-researcher ·          │
   │ state.json (atómico) │   │ extractor · analyst · historian ·    │
   └──────────────────────┘   │ writer · verifier                    │
                              └──┬───────────────────────────────────┘
        scripts determinísticos  │ escrevem só nos seus ficheiros
   ┌─────────────────────────────▼───────────────────────────────────┐
   │ common/: probe · extract · breaks · charts · verify · download  │
   │ common/sources/: ine · eurostat · oecd · who · sns              │
   └─────────────────────────────┬───────────────────────────────────┘
                                 ▼
   studies/<slug>/  (raw → data/clean → breaks → event_links → claims → report.*.qmd)
                                 │
                       site/build.py  →  Quarto  →  site/_site (local) · _site_public (Pages)
```

Ideias centrais:

- **O LLM decide pouco; o código decide quase tudo.** Sondagem de fontes, extração,
  normalização, deteção de quebras, verificação de excertos e as condições de fim de fase são
  scripts Python. Os agentes descrevem *o quê* (especificações JSON, scripts de análise, texto).
- **Estado em disco, não na conversa.** O progresso vive em `state.json`, nos ficheiros de cada
  fase e num commit por fase, por isso um corte de tokens a meio perde, no máximo, uma unidade.
- **Permissões por agente impostas por hook.** `.claude/hooks/guard_writes.py` bloqueia que um
  subagente escreva fora da sua lista (tabela abaixo) ou toque em `state.json`.
- **Dados de eventos partilhados.** `events/events.csv` é um catálogo comum a todos os estudos.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Orquestração | [Claude Code](https://claude.com/claude-code) (skills, subagentes, hooks), modo headless `claude -p` no servidor |
| Dados e análise | Python ≥ 3.12, pandas, pyarrow (Parquet), numpy, scipy, statsmodels, [ruptures](https://github.com/deepcharles/ruptures) (quebras) |
| Fontes | `sdmx1` (Eurostat, OCDE), API JSON do INE, API OData da OMS, exportações SNS, httpx, pypdf, BeautifulSoup, rapidfuzz |
| Validação | pydantic (schemas de todos os CSV) |
| Site | [Quarto](https://quarto.org) (website bilingue, OJS + Plotly para gráficos interativos) |
| Servidor local | FastAPI, uvicorn, SSE (sse-starlette) |
| Gestão do projeto | `uv` (dependências e ambiente), pytest, ruff |
| CI/CD | GitHub Actions + GitHub Pages |

## Orquestração: o fluxo `/study`

Definido em [`.claude/skills/study/SKILL.md`](.claude/skills/study/SKILL.md). Oito fases, por
ordem; só se avança quando a condição da fase passa **em código**
(`uv run python -m common.state complete-phase <slug> <fase>`, que corre `common.checks`).

| # | Fase | Agente | Unidade de trabalho | Saída principal |
| --- | --- | --- | --- | --- |
| 1 | Plano | `planner` | — | `plan.md` |
| 2 | Fontes | `data-researcher` | eixo (ou eixos do mesmo organismo) | `sources.d/*.csv` → `sources.csv` |
| 3 | Extração | `extractor` | fonte testada | `data/extract/<id>.json`, `data/clean/*.parquet`, `data/raw_manifest.csv` |
| 4 | Análise | `analyst` | — | `analysis/*.py`, `analysis/out/*.json`, `breaks.csv` |
| 5 | Eventos | `historian` | — | `events/events.csv`, `event_links.csv` (com grau A/B/C) |
| 6 | Redação | `writer` | língua (`pt`, depois `en`) | `report.pt.qmd`, `report.en.qmd`, `claims.csv` |
| 7 | Verificação | script + `verifier` | afirmação | `verification.md`, `verification_status` em `claims.csv` |
| 8 | Publicação | script | — | `status: published` + build do site |

Regras de orquestração:

- Um comando `common.state init|resume|start-phase|plan-units|unit-start|unit-done|complete-phase`
  por passo; `unit-done` recusa saídas em falta ou inválidas.
- Máximo de **2 subagentes em simultâneo**; resumos dos subagentes com ≤150 palavras; o
  orquestrador passa *caminhos*, não conteúdos.
- **Decisões difíceis de reverter** (excluir um eixo, mudar o âmbito, publicar um grau A pouco
  claro) não são tomadas pelo agente: escreve-se `pending.md`, o estudo pára, e a resposta fica
  em `decisions.md` (a página Fila local mostra as opções com botões).
- **Máximo de 3 tentativas por fase**, contadas em `state.json`; à terceira a fase fica
  `blocked` e o impasse vai para `pending.md`.
- Um commit por fase concluída: `fase <n> (<nome>): <slug>`.

### Verificação (fase 7)

1. `common.verify --apply` confirma por código o que consegue: procura o excerto no texto
   normalizado da página/PDF (correspondência aproximada) e recalcula o valor a partir de
   `data/clean/`.
2. Só as afirmações por confirmar vão ao `verifier`, em lotes de até 15, para análise manual.
3. O que não confirmar volta ao `writer`, até 3 voltas; se continuar sem confirmação, a
   afirmação é **removida**, nunca deixada sem fonte verificada.

## Agentes

Definidos em [`.claude/agents/`](.claude/agents). O hook impõe a coluna "Escreve em".

| Agente | Modelo | Ferramentas | Escreve em |
| --- | --- | --- | --- |
| `planner` | Opus | Read, Write, Edit, Glob, WebSearch, WebFetch | `plan.md` |
| `data-researcher` | Sonnet | Read, Write, Edit, WebSearch, WebFetch, Bash | `sources.d/<unidade>.csv` |
| `extractor` | Sonnet | Read, Write, Edit, Bash | `data/raw/`, `data/extract/`, `data/clean/*.parquet`, `raw_manifest.csv` |
| `analyst` | Sonnet | Read, Write, Edit, Glob, Bash | `analysis/**`, `breaks.csv` |
| `historian` | Sonnet | Read, Write, Edit, WebSearch, WebFetch | `events/events.csv`, `event_links.csv` |
| `writer` | Opus | Read, Write, Edit, Glob, Grep (**sem internet**, de propósito) | `report.{pt,en}.qmd`, `claims.csv`, `study.yml` |
| `verifier` | Sonnet | Read, Glob, Grep, WebFetch, Bash, Write | `verification.md`; só a coluna `verification_status` de `claims.csv` |

## Estado, retoma e limites

- `studies/<slug>/state.json` (schema v2): fase atual, fases concluídas, tentativas e progresso
  por unidade. Só `common/state.py` o escreve, de forma atómica (ficheiro temporário +
  `os.replace`); os subagentes não podem.
- `/study <tema>` começa sempre por `common.state resume <slug>` e continua onde parou; a unidade
  que estava em curso é refeita do zero.
- Os tokens são limitados: o servidor deteta o corte por limite do plano, marca o item como
  `interrompido` com a hora de renovação e retoma de `state.json` quando for relançado.
- Consumo e custo por fase/modelo são gravados em `studies/<slug>/usage.csv` (informação
  interna; **não** aparece no site público).

## Modelo de dados

Formato longo em `studies/<slug>/data/clean/*.parquet`, uma observação por linha:

`date, region, sex, age, indicator, value, unit, source_id`

Ficheiros CSV rastreados (schemas pydantic em `common/schemas.py`):

| Ficheiro | Conteúdo |
| --- | --- |
| `sources.csv` | Catálogo de fontes: URL, organismo, licença, cobertura, estado de teste |
| `data/raw_manifest.csv` | url, file, download_date, sha256, bytes (o raw em si não vai para o git) |
| `breaks.csv` | Quebras detetadas: nível, declive ou pico |
| `event_links.csv` | Quebra ↔ evento, com grau de evidência A/B/C |
| `claims.csv` | Cada afirmação: URL, data de acesso, excerto, valor, cálculo, estado de verificação |
| `events/events.csv` | Catálogo de eventos partilhado (fonte primária, âmbito, tema) |

## Estrutura do repositório

```
.claude/             agentes, skill /study, hook guard_writes.py, settings.json
common/              pipeline determinístico (state, checks, probe, extract, breaks, verify, charts, usage)
common/sources/      clientes INE, Eurostat, OCDE, OMS, SNS
events/              catálogo de eventos partilhado + fontes de eventos
studies/<slug>/      um estudo (plano, fontes, dados limpos, análise, relatórios, claims)
site/                projeto Quarto (pt/en), build.py, assets
server/              FastAPI local: fila de estudos, progresso em tempo real
tests/               pytest
.github/workflows/   Pages e testes
```

## Instalação e uso

Requisitos: [uv](https://docs.astral.sh/uv/), [Quarto](https://quarto.org/docs/get-started/)
(≥ 1.6) e, para gerar estudos novos, o [Claude Code](https://claude.com/claude-code) autenticado.

```bash
uv sync                                  # ambiente e dependências
PYTHONPATH=. uv run pytest -q            # testes (dentro do Claude Code o PYTHONPATH já está definido)
```

Gerar um estudo (numa sessão Claude Code, de preferência com `/model sonnet`):

```
/study Estado da saúde em Portugal
```

Comandos úteis:

```bash
uv run python -m common.state resume <slug>        # onde ficou o estudo
uv run python -m common.checks <slug> <fase>       # condição de uma fase, em código
uv run python -m common.probe eurostat:DEMO_MLEXPEC  # testar uma fonte
uv run python -m common.verify studies/<slug> --apply  # verificação mecânica de afirmações
uv run python -m common.usage [<slug>]             # tokens e custo
uv run python site/build.py                        # site local completo (inclui Fila)
```

Para recriar o `data/raw/` de um estudo (não está no git), usar `common/download.py` com o
`data/raw_manifest.csv`; o hash SHA-256 deteta fontes que mudaram desde o download.

## Servidor local e fila

```bash
uv run python -m server.app        # http://127.0.0.1:8765  (apenas localhost)
```

Serve o site compilado e uma API para a **fila de estudos**: acrescentas temas, escolhes o que
corre (um de cada vez), vês o progresso por fase em tempo real, respondes a decisões pendentes
e consultas o custo. O servidor lança `claude -p` com lista de argumentos (nunca uma string de
shell) e valida o tema com um conjunto de caracteres estrito. `queue.json` e `logs/` são locais
e estão no `.gitignore`.

## Publicação

O site público é uma versão **só de leitura**, gerada com:

```bash
uv run python site/build.py --public      # escreve site/_site_public/
```

Diferenças face ao build local: só estudos com `status: published`, sem a página Fila nem
`queue.js`, sem custos nem progresso. Mantém-se a página de Eventos. Os estudos de teste
(`status: test`) e em curso (`in_progress`) nunca aparecem. Para pré-visualizar um estudo de
teste: `--include-status test`.

O workflow [`pages.yml`](.github/workflows/pages.yml) faz o build e o deploy a cada push para
`main` que toque em estudos, eventos, site ou dependências. Para ativar: **Settings → Pages →
Source: GitHub Actions**. Os caminhos funcionam tanto na raiz de um domínio como em
`/<repo>/` (o Quarto converte os links absolutos em relativos e `lang-switch.js` lê o prefixo
do URL).

Publicar um estudo = fase 8 do `/study` (`status: published` em `study.yml`) + push.

## Testes

`tests/` cobre o estado e a retoma, as verificações de fase, a extração, a normalização, os
schemas, o hook de escrita, o build do site, a verificação de afirmações, a resiliência a falhas
das fontes (INE) e o servidor. Correm em CI ([`tests.yml`](.github/workflows/tests.yml)). Não
há testes de qualidade dos *agentes*, ver [Pontos de melhoria](#pontos-de-melhoria).

## Segurança e privacidade

- Nenhum segredo no repositório: não há chaves de API (a autenticação é a do Claude Code).
- `queue.json`, `logs/` e `data/raw/` não são versionados.
- A página Fila só mostra o tipo de plano (nunca email nem organização); não é publicada.
- O servidor escuta apenas em `127.0.0.1`.
- `.claude/settings.json` nega `rm`, `git push`, `git reset`, `curl` e `sudo` ao agente.
- Os subagentes só escrevem nos seus ficheiros (hook `guard_writes.py`).

## Licenças e atribuição de dados

Os dados limpos derivam de fontes oficiais (INE, Eurostat, OCDE, OMS, SNS…), cada uma com a sua
licença registada em `sources.csv`. O site só exporta para download (`open_data.csv`) as fontes
cuja licença **não** é não-comercial. Cite sempre a fonte original. A licença do código e dos
textos do repositório está por definir (adicionar um ficheiro `LICENSE`).

## Limitações conhecidas

- Apenas Portugal; cobertura limitada pelo que cada organismo publica de forma acessível.
- SNS Transparência não tem API estável: depende de exportações descobertas caso a caso.
- A deteção de quebras é um *candidato*; a ligação a eventos exige fonte (grau A) ou fica como
  coincidência (grau C).
- A verificação por correspondência de texto falha em páginas dinâmicas (JavaScript) ou PDFs
  digitalizados; essas afirmações passam à verificação manual.
- Sessões interativas não registam consumo; só as execuções lançadas pelo servidor.

## Pontos de melhoria

Ordenados por impacto na robustez:

1. **Avaliação (evals) dos agentes.** Hoje só o código determinístico tem testes. Criar `evals/`
   com fixtures congeladas (um commit por fase serve de ponto de partida) e avaliadores em
   código: injetar erros num relatório já verificado para medir o recall e os falsos positivos
   do `verifier`; casos de "só coincidência" que o `historian` tem de classificar como grau C;
   números fora de `claims.csv` que o `writer` não pode escrever. Repetir 3× por caso e comparar
   antes/depois de mudar prompts ou modelos.
2. **Orquestrador em código.** Mover o ciclo de fases do prompt para um script Python (por
   exemplo com o Claude Agent SDK), mantendo agentes e hooks. Retira o LLM do papel de
   coordenador, reduz tokens e torna a retoma totalmente determinística.
3. **Congelar as fontes.** O raw fica fora do git e o INE/Eurostat revêem séries. Guardar
   *snapshots* (por exemplo em release assets ou num bucket) com o mesmo SHA-256 do manifesto, e
   registar a data de vintage de cada série, para que um relatório antigo continue verificável.
4. **Verificação em duas camadas mais forte.** Arquivar a página usada (Wayback Machine ou cópia
   local do excerto) para sobreviver a *link rot*; reverificar periodicamente os URLs dos
   estudos publicados e abrir um alerta quando algo mudar.
5. **Garantir a regra "sem número sem marca".** Tornar `common.checks` bloqueante em CI para
   estudos `published` (números sem `{.claim}`, graus de evidência coerentes com a linguagem,
   paridade PT/EN, citações <15 palavras) e correr a verificação mecânica também no pipeline de
   publicação.
6. **Aplicar a restrição do `verifier` por código.** O hook só filtra por caminho; a limitação
   a uma coluna de `claims.csv` depende do prompt. Validar por diff (só `verification_status`
   mudou) antes de aceitar a escrita.
7. **Qualidade e reprodutibilidade do ambiente.** Corrigir os avisos pendentes do `ruff`
   (há alguns em `tests/`) e passar a lint a bloquear em CI; fixar versões do Quarto e das
   *actions* por SHA; adicionar `pre-commit`.
8. **Privacidade do histórico.** Usar o email `noreply` do GitHub nos commits e rever o
   histórico antes de publicar (ver abaixo); manter `usage.csv` fora do repositório público se o
   custo for considerado sensível.
9. **Observabilidade.** Painel de métricas por agente (tentativas, taxa de falha por fase, custo
   por ponto de qualidade) alimentado por `usage.csv` e `state.json`, para escolher o modelo de
   cada agente com dados.
10. **Experiência de leitura.** Página de metodologia pública (graus de evidência, como se
    verifica), registo de alterações por estudo (versão e data de revisão), RSS e metadados
    Open Graph para partilha.
11. **Limpeza.** `prompt_claude_code_estudos.md` é o prompt inicial de bootstrap, com nomes
    antigos (`/estudo`); mover para `docs/` ou remover. `scripts/migrate_v1_names.py` é uma
    migração única já aplicada.
12. **Licença.** Escolher e adicionar `LICENSE` (por exemplo MIT para código e CC BY 4.0 para
    textos), respeitando as licenças dos dados de origem.
