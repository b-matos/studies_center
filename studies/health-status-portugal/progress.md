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

## Fase 7 (verificação)
`common.verify --apply` deixou 18 afirmações por resolver; o `verifier` falhou-as todas. Nove da OMS tinham o URL `/pt/` com excerto em inglês: o `writer` passou para o URL em inglês e `common.verify` confirmou-as. Nove do Diário da República (páginas JavaScript, sem texto estático; Lei 63/2017 e Portaria 430/2023 não correspondiam ao evento) não tinham fonte alternativa verificável: o `writer` removeu-as e acrescentou uma nota de omissão nos dois relatórios. Consequência: as ligações a esses eventos deixam de estar descritas no relatório. `complete-phase 7` passou à primeira volta.

## Fase 4 (refeita, 2026-11-19)
Análise refeita com o detetor corrigido (tendência+degrau, teste F). `breaks.csv` com 28 quebras curadas (as 51 antigas foram descartadas); gráficos e scripts regenerados; `complete-phase 4` passou. Séries de inquérito: ih01 tem degrau real mas em 2013 (rampa 2011–2015), ih03 desce em 2013 e recupera, eac10 cai em 2014; sem quebra em 2018/2019 (ih01, ih03, eac16). Atenção: voltar a correr os scripts reescreve `breaks.csv` e perde a curadoria. Seguem-se as fases 5 a 7, que dependem das quebras novas.

## Fase 5 (refeita, 2026-11-19)
`event_links.csv` refeito sobre as 29 quebras novas (35 linhas): 12 ligadas em grau C, 17 sem evento; nenhuma A/B. Quebras de inquérito (ih01, ih03, eac16) ligadas ao Memorando em C, com a nota de que o artefacto de método não está excluído. `common.verify events` confirmou 4 eventos; 3 por confirmar (gripe 2014/15, Lei do SNS, saúde oral), portanto não podem ser citados. `complete-phase 5` passou.

## Fase 6 (redação, 2026-11-20)
`report.pt.qmd` e `report.en.qmd` escritos sobre as 29 quebras novas (todas as ligações a eventos em grau C); degraus de ih01 (2013), ih03 (2011–2014) e eac16 (2011) confirmados, nenhum em 2018/2019. Removidas c221 e c231 (sem fonte). À 1.ª tentativa a porta recusou 10 gráficos em cada língua por tipo inadequado aos dados; trocados por smallMultiples, heatmap e tabelas; 2.ª tentativa passou. Para o autor: q02 e q03 ficaram em tabela e ficariam melhor em linhas; a nota de mortalidade-b001 em `breaks.csv`/`event_links.csv` fala de uma lacuna 2018–2021 na série de tumores que não existe (fases 4/5).
