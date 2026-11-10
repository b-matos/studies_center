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
  reprodutibilidade (`uv run python studies/<slug>/analysis/<axis>.py`).
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
  `uv run python -m common.checks <slug> <fase>`.

## Estrutura

Ver `studies/`, `events/`, `common/`, `site/`, `server/`. O fluxo completo do `/study <tema>`
está em `.claude/skills/study/SKILL.md`.
