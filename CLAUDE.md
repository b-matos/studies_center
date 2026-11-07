# studies_center

Plataforma local para produzir e publicar estudos exaustivos, com dados, sobre Portugal.
Cada estudo nasce do comando `/estudo <tema>` e acrescenta uma página bilingue (PT/EN) a um
site Quarto estático. Tudo corre localmente, em Python, orquestrado pelo Claude Code.

## Princípios que nunca podem ser quebrados

1. **Nenhuma afirmação sem fonte.** Todo número, facto ou evento num relatório tem uma linha
   correspondente em `estudos/<slug>/afirmacoes.csv`, com URL, data de acesso e um excerto
   curto (menos de 15 palavras) que a sustente.
2. **Fontes primárias primeiro.** Dados: INE, Eurostat, OCDE, OMS, DGS, SNS e organismos
   oficiais. Eventos: Diário da República, parlamento.pt, EUR-Lex, CNE, sites do Governo.
   Notícias de órgãos credíveis só servem para contexto ou na ausência de fonte primária, e
   ficam marcadas como `natureza_fonte = noticia`.
3. **Coincidência não é causalidade.** Um evento só é apresentado como causa de uma mudança de
   tendência se uma fonte o afirmar (grau A). Sem isso, é "coincide temporalmente com" (grau C),
   ou "pode ter contribuído" quando há um mecanismo plausível documentado (grau B).
4. **Verificação independente.** Quem escreve o relatório (`redator`) não verifica. O
   `verificador` abre cada URL e confirma excerto, data e valor; nunca edita o relatório.
5. **Direitos de autor.** Paráfrase sempre. No máximo uma citação literal curta por fonte,
   sempre atribuída.
6. **Reprodutibilidade.** Todo gráfico nasce de dados guardados no repositório (`dados/clean/`),
   gerado por código, nunca à mão.

## Convenções

- **Línguas:** código, nomes de ficheiros técnicos e comentários em inglês. Relatórios,
  `plano.md`, `progresso.md` e a comunicação comigo em português.
- **Sem notebooks.** Análise em scripts `.py` executáveis por CLI, para diffs limpos e
  reprodutibilidade (`uv run python estudos/<slug>/analise/<eixo>.py`).
- **Formato longo** em todo o `dados/clean/`: uma observação por linha, colunas
  `data, regiao, sexo, idade, indicador, valor, unidade, fonte_id`, onde aplicável.
- **Gestão de dependências:** `uv` para Python (`uv sync`, `uv run ...`); nada de pip global
  nem conda. `uv add <pacote>` para adicionar; nunca editar `uv.lock` à mão.
- **Raw fora do git.** `estudos/<slug>/dados/raw/` está no `.gitignore`. O que fica commitado é
  `dados/raw_manifest.csv` (url, ficheiro, data_download, sha256, bytes) e `dados/clean/`. Para
  recriar o raw, usar `comum/download.py` com o manifesto.
- **Afirmações marcadas no texto:** em `relatorio.*.qmd`, cada afirmação usa
  `[texto]{.claim id="c042"}`, correspondendo a uma linha em `afirmacoes.csv`. Números sem essa
  marca são um erro de fase (ver `comum/checks.py`).
- **Linguagem por grau de evidência:** A → "contribuiu para" / "contributed to"; B → "pode ter
  contribuído" / "may have contributed to"; C → "coincidiu com" / "coincided with".
- **Commits:** um por fase de estudo concluída, mensagem `fase <n> (<nome>): <slug>`. Nunca
  `--amend`, nunca `--no-verify`.
- **Subagentes só escrevem nos seus ficheiros.** Ver a tabela em `.claude/agents/`; o hook
  `.claude/hooks/guard_writes.py` impõe isto.
- **Condições de fase são verificadas por código**, não por julgamento do agente:
  `uv run python -m comum.checks <slug> <fase>`.

## Estrutura

Ver `estudos/`, `eventos/`, `comum/`, `site/`, `servidor/`. O fluxo completo do `/estudo <tema>`
está em `.claude/skills/estudo/SKILL.md`.
