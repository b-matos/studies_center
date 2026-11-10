---
name: study
description: Produz um novo estudo exaustivo sobre Portugal e publica-o no site bilingue. Usar quando o utilizador escrever "/study <tema>". Orquestra 7 subagentes ao longo de 8 fases verificáveis por código, com estado retomável e commit a cada fase.
---

# /study <tema>

Recebeste um tema de estudo. Cria/retoma `studies/<slug>/` e executa as 8 fases, por ordem,
sem avançar para a seguinte até a condição da fase passar **em código** (nunca por
julgamento próprio).

**Os tokens podem acabar a qualquer momento.** Por isso o progresso vive em disco, não na
conversa: `studies/<slug>/state.json` (escrito só por `common.state`), os ficheiros de cada
fase e um commit por fase. Se a sessão morrer, o utilizador volta a correr `/study <tema>` e
o estudo continua de onde parou; só a unidade de trabalho em curso é refeita.

## Comandos Bash (obrigatório)

Em modo headless só são permitidos `uv run ...`, `git add ...`, `git commit ...` e
`quarto render ...`. **Um comando por chamada**: nada de `&&`, `;`, `|` para outros programas,
heredocs, `mkdir`, `cat`, `ls` ou redirecionamentos (a chamada inteira é recusada e o estudo
não arranca). Ficheiros criam-se com Write/Edit; o `git add` e o `git commit` são chamadas
separadas. Se uma chamada for recusada, para e diz porquê; não contornes.

## Disciplina de tokens (obrigatória)

- Tu és só o orquestrador: despachas, corres comandos e lês resultados curtos. Nunca leias
  `data/raw/`, parquet, JSON de gráficos nem relatórios inteiros; passa **caminhos** aos
  subagentes, não conteúdos.
- Cada subagente termina com um resumo de **no máximo 150 palavras** (o que fez, ficheiros,
  problemas). Se devolver mais, ignora o excesso.
- **No máximo 2 subagentes em simultâneo.** Agrupa trabalho do mesmo organismo (ex.: todos os
  eixos Eurostat num só `data-researcher`; até 4 fontes por `extractor`).
- Os subagentes correm em segundo plano. Depois de os lançar, espera pelas notificações de
  conclusão; não faças polling, `sleep` nem releituras de ficheiros à espera. Uma unidade só é
  dada como feita com `unit-done`, nunca porque o texto do subagente diz que acabou.
- Cálculo, normalização e verificação mecânica são scripts, não prompts: `common.probe`,
  `common.extract`, `common.breaks`, `common.verify`.
- Num reenvio por falha, dá ao subagente só a lista de problemas impressa por
  `common.state complete-phase`, não o contexto antigo.
- Modelos (definidos em `.claude/agents/*.md`): `planner` e `writer` em Opus (planeamento e
  redação); os restantes em Sonnet. Recomenda ao utilizador correr esta sessão em Sonnet
  (`/model sonnet`): o orquestrador não precisa de mais.

## 0. Preparação e retoma

1. Deriva o `slug` do tema **em inglês** (traduz o tema; minúsculas, hífens, sem acentos — `python-slugify`), porque os nomes de pastas são técnicos.
2. Se `studies/<slug>/` não existir, corre **um** comando que cria a pasta, o `study.yml` e o
   `state.json`: `uv run python -m common.state init <slug> --title-pt "..." --title-en "..."
   --summary-pt "..." --summary-en "..."`.
3. Corre **sempre** `uv run python -m common.state resume <slug>`. Imprime a próxima fase, as
   unidades feitas e por fazer, as tentativas gastas e os últimos problemas.
   - `BLOCKED`: lê `pending.md`, informa o utilizador e para.
   - Tudo concluído: diz isso e termina.
   - Caso contrário, continua **nessa fase**, só nas unidades por fazer. Não repitas fases
     concluídas nem unidades `done`.

## 1–7. As fases

Para a fase `n`: `common.state start-phase <slug> <n>`; regista as unidades com
`common.state plan-units <slug> <n> <u1> <u2> ...`; para cada unidade, `unit-start`, lança o
subagente, e `unit-done` (que **recusa** se a saída não existir ou for inválida); no fim
`common.state complete-phase <slug> <n>`, que funde ficheiros parciais, corre
`common.checks` e conta a tentativa se falhar.

| Fase | Subagente | Unidades | Notas |
| --- | --- | --- | --- |
| 1. Plano | `planner` | — (sem unidades) | |
| 2. Fontes | `data-researcher` | um eixo (ou grupo de eixos do mesmo organismo) | escreve `sources.d/<unidade>.csv`; `complete-phase 2` funde-os em `sources.csv` |
| 3. Extração | `extractor` | um `source_id` testado | escreve `data/extract/<id>.json` (ou `.py`) e corre `common.extract`; `unit-done` valida parquet + manifesto |
| 4. Análise | `analyst` | — | usa `common.breaks` para candidatos; regista só o que vale a pena |
| 5. Eventos | `historian` | — | |
| 6. Redação | `writer` | `pt`, depois `en` | `pt` escreve `report.pt.qmd` + `claims.csv`; `en` traduz com os mesmos ids |
| 7. Verificação | script, depois `verifier` | afirmações (estado em `claims.csv`) | ver abaixo |

Depois de `complete-phase` passar:
1. Acrescenta um parágrafo curto a `studies/<slug>/progress.md` (o que foi feito, o que
   falhou e foi corrigido, o que precisa do utilizador).
2. `git add studies/<slug> events` e `git commit -m "fase <n> (<nome>): <slug>"`.

Se `complete-phase` falhar: lê os problemas, relança o subagente da fase (só as unidades
afetadas) com esses problemas como contexto. **Máximo de 3 tentativas por fase**, contadas em
`state.json` (sobrevivem a interrupções). À terceira o estado passa a `blocked`: escreve o
impasse em `studies/<slug>/pending.md` e para — não inventes dados nem fontes.

### Fase 7 em particular

1. `uv run python -m common.verify studies/<slug> --apply` confirma por código o que consegue
   (excerto na página, valor recalculado) e grava `verification_status`; só reverifica o que
   não está confirmado, por isso retoma sem refazer trabalho.
2. Imprime `UNRESOLVED: c004,c010,...`. Lança o `verifier` só com esses ids (lotes de até 15),
   para os investigar à mão.
3. O `verifier` nunca corrige o relatório. As falhadas voltam ao `writer` (máximo 3 voltas);
   se mesmo assim não confirmarem, o `writer` remove a afirmação em vez de a deixar sem fonte
   verificada. Volta ao passo 1 até `complete-phase 7` passar.

### Decisões difíceis de reverter

Se, em qualquer fase, surgir uma decisão difícil de reverter (excluir um eixo inteiro por
falta de dados, mudar o âmbito definido em `plan.md`, publicar uma afirmação de grau A sem
fonte 100% clara):

- Em **modo interativo**: pergunta diretamente ao utilizador antes de continuar.
- Em **modo headless** (lançado pelo servidor): escreve a decisão em
  `studies/<slug>/pending.md`, põe `status: pending_decision` em `study.yml`, e para a skill.
  O servidor mostra isto na vista de progresso.

## 8. Publicação

1. `common.state start-phase <slug> 8`, depois `uv run python site/build.py` (gera o índice,
   copia os relatórios, exporta `events.json` e os dados para download, e chama
   `quarto render` nos dois perfis pt/en).
2. `uv run python -m common.state complete-phase <slug> 8`.
3. Se passar: `study.yml` → `status: published` (ou mantém `status: test` num estudo de teste
   — o `site/build.py` já o exclui do índice), commit `fase 8 (publicação): <slug>`, e resumo
   final ao utilizador: o que foi publicado, nas duas línguas, e o link relativo da página.

## No final de cada fase

Dá ao utilizador um resumo curto, em português: o que foi feito, o que falhou (e como foi
resolvido ou não), e o que precisa dele. Nunca avances silenciosamente sobre um impasse.
