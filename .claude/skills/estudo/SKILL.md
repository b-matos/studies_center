---
name: estudo
description: Produz um novo estudo exaustivo sobre Portugal e publica-o no site bilingue. Usar quando o utilizador escrever "/estudo <tema>". Orquestra 7 subagentes ao longo de 8 fases verificáveis por código, com commit a cada fase.
---

# /estudo <tema>

Recebeste um tema de estudo. Cria/retoma `estudos/<slug>/` e executa as 8 fases, por ordem,
sem avançar para a seguinte até a condição da fase atual passar em código (nunca por
julgamento próprio).

## 0. Preparação

1. Deriva o `slug` do tema (minúsculas, hífens, sem acentos — usa `python-slugify`).
2. Se `estudos/<slug>/` não existir, cria-a com:
   - `estudo.yml` (título PT/EN, data de início, `estado: em_curso`, `fase_atual: 1`)
   - `estado.json` (`{"fase_atual": 1, "fases_concluidas": []}`)
3. Se já existir, lê `estado.json` e retoma na primeira fase não concluída. Um estudo
   interrompido continua de onde ficou — não repetes fases já passadas.

## 1–7. As fases

Para cada fase `n` de 1 a 7, nesta ordem:

| Fase | Subagente(s) | Em paralelo? |
| --- | --- | --- |
| 1. Plano | `planeador` | não |
| 2. Fontes | `pesquisador-dados` (um por eixo de `plano.md`) | sim |
| 3. Extração | `extrator` (um por fonte ou grupo independente) | sim |
| 4. Análise | `analista` | não |
| 5. Eventos | `historiador` | não |
| 6. Redação | `redator` | não |
| 7. Verificação | `verificador`, depois `redator` (ciclo de correção) | não |

Passos:

1. Lança o(s) subagente(s) da fase via `Agent` (ou `Task`), com o caminho do estudo e o
   contexto relevante (perguntas do eixo, fontes a extrair, etc.).
2. Quando terminar(em), corre `uv run python -m comum.checks <slug> <n>`.
3. Se passar: escreve um parágrafo curto em `estudos/<slug>/progresso.md` — o que foi feito,
   o que falhou (se algo falhou e foi corrigido), o que precisa do utilizador — e faz
   `git add` + `git commit -m "fase <n> (<nome da fase>): <slug>"`.
4. Se falhar: lê os problemas que o `checks` imprime, volta a lançar o subagente da fase com
   esses problemas como contexto, e repete. **Máximo de 3 tentativas por fase.** Se continuar
   a falhar, escreve o impasse em `estudos/<slug>/pendente.md` e para — não inventes dados
   nem sources para forçar a fase a passar.
5. **Fase 7 em particular**: o `verificador` nunca corrige o relatório. Se encontrar
   afirmações falhadas, devolve-as ao `redator` (máximo 3 voltas); se mesmo assim não
   confirmarem, remove a afirmação do relatório em vez de a deixar sem fonte verificada.

### Decisões difíceis de reverter

Se, em qualquer fase, surgir uma decisão difícil de reverter (por exemplo: excluir um eixo
inteiro por falta de dados, mudar o âmbito geográfico ou temporal definido em `plano.md`,
publicar uma afirmação de grau A sem fonte 100% clara):

- Em **modo interativo**: pergunta directamente ao utilizador antes de continuar.
- Em **modo headless** (lançado pelo servidor): escreve a decisão em
  `estudos/<slug>/pendente.md`, marca `estado: pendente_decisao` em `estudo.yml`, e para a
  skill. O servidor mostra isto na vista de progresso.

## 8. Publicação

1. Corre `uv run python site/build.py`. Isto gera o índice, copia os relatórios, exporta
   `eventos.json` e os dados para download, e chama `quarto render` nos dois perfis (pt/en).
2. Corre `uv run python -m comum.checks <slug> 8`.
3. Se passar: muda `estudo.yml` para `estado: publicado` (ou mantém `estado: teste` se este
   for um estudo de teste da plataforma — nesse caso o `site/build.py` já o exclui do
   índice), faz commit `fase 8 (publicação): <slug>`, e informa o utilizador com um resumo
   final: o que foi publicado, nas duas línguas, e o link relativo da página.

## No final de cada fase

Dá ao utilizador um resumo curto, em português: o que foi feito, o que falhou (e como foi
resolvido ou não), e o que precisa dele. Nunca avances silenciosamente sobre um impasse.
