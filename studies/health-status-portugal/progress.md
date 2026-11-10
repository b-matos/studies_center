# Progresso

## Fase 1 (plano)
Plano escrito pelo `planner` com 10 perguntas de investigação e 6 eixos (esperança de vida, mortalidade, morbilidade, fatores de risco, saúde mental, acesso e recursos). Verificação por código (`common.checks`) passou à primeira tentativa. Decisões em aberto para fases seguintes: NUTS 2013 vs 2024, quebras de método (INS/EHIS), transição CID-9/CID-10, esperança de vida por escolaridade.

## Fase 2 (fontes)
Três unidades (`ine-life-mortality`, `ine-health`, `eurostat-access`) registadas em `sources.d/` e fundidas em `sources.csv`. Duas tentativas falharam porque os probes Eurostat `eac13`/`eac14` excederam o tempo (falha transitória, não indisponibilidade). Seguindo a decisão do utilizador (`decisions.md`), voltou-se a correr `complete-phase 2`, que passou com a regra atual. Limitação a declarar no relatório: o excesso de mortalidade semanal (pergunta 5) pode não ficar coberto por fonte Eurostat testada.
