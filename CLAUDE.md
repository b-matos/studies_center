# studies_center

Plataforma local para produzir e publicar estudos exaustivos, com dados, sobre Portugal.
Cada estudo nasce do comando `/study <tema>` e acrescenta uma página bilingue (PT/EN) a um
site Quarto estático. Tudo corre localmente, em Python, orquestrado pelo Claude Code.

## Princípios que nunca podem ser quebrados

1. **Nenhuma afirmação sem fonte.** Todo número, facto ou evento num relatório tem uma linha
   correspondente em `studies/<slug>/claims.csv`, com URL, data de acesso e um excerto
   curto (menos de 15 palavras) que a sustente.
2. **Fontes primárias primeiro.** Dados: INE, Eurostat, OCDE, OMS, DGS, SNS e organismos
   oficiais. Eventos: Diário da República, parlamento.pt, EUR-Lex, CNE, sites do Governo.
   Notícias de órgãos credíveis só servem para contexto ou na ausência de fonte primária, e
   ficam marcadas como `source_nature = news`.
3. **Coincidência não é causalidade.** Um evento só é apresentado como causa de uma mudança de
   tendência se uma fonte o afirmar (grau A). Sem isso, é "coincide temporalmente com" (grau C),
   ou "pode ter contribuído" quando há um mecanismo plausível documentado (grau B).
4. **Verificação independente.** Quem escreve o relatório (`writer`) não verifica. O
   `verifier` abre cada URL e confirma excerto, data e valor; nunca edita o relatório.
5. **Direitos de autor.** Paráfrase sempre. No máximo uma citação literal curta por fonte,
   sempre atribuída.
6. **Reprodutibilidade.** Todo gráfico nasce de dados guardados no repositório (`data/clean/`),
   gerado por código, nunca à mão.

## Convenções

- **Línguas:** código, nomes de ficheiros técnicos e comentários em inglês. Relatórios,
  `plan.md`, `progress.md` e a comunicação comigo em português.
- **Sem notebooks.** Análise em scripts `.py` executáveis por CLI, para diffs limpos e
  reprodutibilidade (`uv run python studies/<slug>/analysis/<axis>.py`; `.claude/settings.json` define `PYTHONPATH=.`, fora do Claude Code usar `PYTHONPATH=. uv run ...`).
- **Formato longo** em todo o `data/clean/`: uma observação por linha, colunas
  `date, region, sex, age, indicator, value, unit, source_id`, onde aplicável.
- **Gestão de dependências:** `uv` para Python (`uv sync`, `uv run ...`); nada de pip global
  nem conda. `uv add <pacote>` para adicionar; nunca editar `uv.lock` à mão.
- **Raw fora do git.** `studies/<slug>/data/raw/` está no `.gitignore`. O que fica commitado é
  `data/raw_manifest.csv` (url, file, download_date, sha256, bytes) e `data/clean/`. Para
  recriar o raw, usar `common/download.py` com o manifesto.
- **Afirmações marcadas no texto:** em `report.*.qmd`, cada afirmação usa
  `[texto]{.claim id="c042"}`, correspondendo a uma linha em `claims.csv`. Números sem essa
  marca são um erro de fase (ver `common/checks.py`).
- **Linguagem por grau de evidência:** A → "contribuiu para" / "contributed to"; B → "pode ter
  contribuído" / "may have contributed to"; C → "coincidiu com" / "coincided with".
- **Commits:** um por fase de estudo concluída, mensagem `fase <n> (<nome>): <slug>`. Nunca
  `--amend`, nunca `--no-verify`.
- **Subagentes só escrevem nos seus ficheiros.** Ver a tabela em `.claude/agents/`; o hook
  `.claude/hooks/guard_writes.py` impõe isto.
- **Condições de fase são verificadas por código**, não por julgamento do agente:
  `uv run python -m common.checks <slug> <fase>` (o orquestrador usa
  `uv run python -m common.state complete-phase <slug> <fase>`, que também regista o estado).
- **Nomes técnicos em inglês** (pastas, ficheiros, colunas, enums, variáveis, funções,
  subagentes, skill). Em português ficam só o conteúdo dos relatórios, `plan.md`,
  `progress.md`, `pending.md`, `verification.md` e a comunicação comigo.

## Tokens e retoma

Os tokens são limitados e podem acabar a meio de um estudo. O pipeline foi desenhado para
isso:

- **Estado em disco.** `studies/<slug>/state.json` (schema v2) guarda fase, tentativas e
  progresso por unidade (eixo, fonte, língua, afirmação). Só `common/state.py` o escreve, de
  forma atómica; os subagentes não podem (hook). `/study <tema>` começa sempre por
  `uv run python -m common.state resume <slug>` e continua onde parou; a unidade que estava
  em curso é refeita do zero. Um commit por fase, sem trabalho por commitar entre fases.
- **Unidade concluída = validada por código** (`unit-done` recusa saídas em falta ou inválidas).
- **Máximo 3 tentativas por fase**, contadas em `state.json`; à terceira a fase fica
  `blocked` e o impasse vai para `pending.md`.
- **Modelos por agente** (`model:` em `.claude/agents/*.md`): Opus no `planner` e `writer`;
  Sonnet nos restantes. Correr a sessão orquestradora em Sonnet (`/model sonnet`).
- **Scripts em vez de prompts** para o que é mecânico: `common.probe` (testar fontes),
  `common.extract` (download + normalização a partir de uma especificação em
  `data/extract/`), `common.breaks` (candidatos a quebras), `common.verify --apply`
  (verificação de excertos e valores).
- **Contexto curto:** subagentes devolvem resumos de ≤150 palavras; o orquestrador passa
  caminhos, não conteúdos; no máximo 2 subagentes em simultâneo.
- O servidor regista tokens por execução em `logs/runs.csv` e marca como
  `interrompido_por_limite` as execuções cortadas pelo limite do plano.

## Estrutura

Ver `studies/`, `events/`, `common/`, `site/`, `server/`. O fluxo completo do `/study <tema>`
está em `.claude/skills/study/SKILL.md`.
