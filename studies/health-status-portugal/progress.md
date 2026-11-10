# Progresso

## Fase 1 (plano)
Plano escrito pelo `planner` com 10 perguntas de investigação e 6 eixos (esperança de vida, mortalidade, morbilidade, fatores de risco, saúde mental, acesso e recursos). Verificação por código (`common.checks`) passou à primeira tentativa. Decisões em aberto para fases seguintes: NUTS 2013 vs 2024, quebras de método (INS/EHIS), transição CID-9/CID-10, esperança de vida por escolaridade.

## Fase 2 (fontes)
Três unidades (`ine-life-mortality`, `ine-health`, `eurostat-access`) registadas em `sources.d/` e fundidas em `sources.csv`. Duas tentativas falharam porque os probes Eurostat `eac13`/`eac14` excederam o tempo (falha transitória, não indisponibilidade). Seguindo a decisão do utilizador (`decisions.md`), voltou-se a correr `complete-phase 2`, que passou com a regra atual. Limitação a declarar no relatório: o excesso de mortalidade semanal (pergunta 5) pode não ficar coberto por fonte Eurostat testada.

## Fase 3 (extração)
33 fontes extraídas (Eurostat e INE) para `data/clean/`, todas validadas por `unit-done`; `complete-phase 3` passou à primeira. Nenhum valor foi comparado com a página de origem na extração (fica para a fase 7). Pontos para a análise: `unit` mistura unidades nas tabelas Eurostat de recursos; `ilm02` só tem 2024; `ilm01` trienal com data no primeiro ano; `ilm06` quinquenal com data no último ano; regiões sobrepostas (Total/Portugal/Continente) em `ih05`, `ih07`, `ih09` a `ih12`; contagens em vez de percentagens em `ih05` a `ih08`; valor 0 a confirmar em `eac12` (PT, 2023). `eac08`/`eac09` só têm PT e 7 NUTS 2 (sem UE27). Ficheiro obsoleto `data/extract/eac01.json` por apagar.
