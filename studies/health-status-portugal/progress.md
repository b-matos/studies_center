# Progresso

## Fase 1 (plano)
Plano escrito pelo `planner` com 10 perguntas de investigação e 6 eixos (esperança de vida, mortalidade, morbilidade, fatores de risco, saúde mental, acesso e recursos). Verificação por código (`common.checks`) passou à primeira tentativa. Decisões em aberto para fases seguintes: NUTS 2013 vs 2024, quebras de método (INS/EHIS), transição CID-9/CID-10, esperança de vida por escolaridade.

## Fase 2 (fontes)
Três unidades (`ine-life-mortality`, `ine-health`, `eurostat-access`) registadas em `sources.d/` e fundidas em `sources.csv`. Duas tentativas falharam porque os probes Eurostat `eac13`/`eac14` excederam o tempo (falha transitória, não indisponibilidade). Seguindo a decisão do utilizador (`decisions.md`), voltou-se a correr `complete-phase 2`, que passou com a regra atual. Limitação a declarar no relatório: o excesso de mortalidade semanal (pergunta 5) pode não ficar coberto por fonte Eurostat testada.

## Fase 3 (extração)
33 fontes extraídas (Eurostat e INE) para `data/clean/`, todas validadas por `unit-done`; `complete-phase 3` passou à primeira. Nenhum valor foi comparado com a página de origem na extração (fica para a fase 7). Pontos para a análise: `unit` mistura unidades nas tabelas Eurostat de recursos; `ilm02` só tem 2024; `ilm01` trienal com data no primeiro ano; `ilm06` quinquenal com data no último ano; regiões sobrepostas (Total/Portugal/Continente) em `ih05`, `ih07`, `ih09` a `ih12`; contagens em vez de percentagens em `ih05` a `ih08`; valor 0 a confirmar em `eac12` (PT, 2023). `eac08`/`eac09` só têm PT e 7 NUTS 2 (sem UE27). Ficheiro obsoleto `data/extract/eac01.json` por apagar.

## Fase 4 (análise)
28 gráficos (`charts.yml`) e 51 quebras (`breaks.csv`) em seis eixos; `complete-phase 4` passou. Sem quebras em fatores de risco (séries com menos de 8 pontos) nem em suicídio. Pergunta 5 (mortalidade semanal) sem análise: limitação. O valor 0 de `eac12` (PT, 2023) é real (taxa Y70-Y82 arredondada). Cautelas: tratável 2021 = 2022 (74,53) possivelmente provisório; queda circulatória em 2021 em `ilm08` pode ser alteração de codificação; série de suicídio junta duas tabelas INE. Sem dados: escolaridade, antidepressivos, comparação UE em fatores de risco, médicos/enfermeiros UE-27.

## Fase 5 (eventos)
`event_links.csv` com 53 linhas (20 `linked`, todas grau C; 32 `break_without_event`; 1 `event_without_effect`) e 5 eventos novos em `events/events.csv`, todos `verified = no` (páginas do Diário da República não carregaram; o verifier/fase 7 deve confirmá-los). Nenhum grau A ou B: nenhuma fonte encontrada afirma o efeito. Várias quebras (2021 em `ilm08`, 2014/2019 em morbilidade, médicos/enfermeiros, camas) parecem artefactos de método, não confirmado. `complete-phase 5` passou.

## Fase 6 (redação)
`report.pt.qmd` (209 afirmações em `claims.csv`) e `report.en.qmd` escritos; `complete-phase 6` passou à primeira tentativa. Todas as ligações a eventos em grau C ("coincidiu com"). Limitação declarada: excesso de mortalidade semanal não coberto (decisão do utilizador). Para a fase 7: filtros de séries do `summary.md` apontam por vezes para ficheiros `clean` errados (o writer usou os scripts de análise); rótulos do Inquérito Nacional de Saúde deduzidos; excertos de eventos e Eurostat não confirmados online; a EN tem 215 marcas contra 209 ids (ids repetidos, a confirmar na verificação).
