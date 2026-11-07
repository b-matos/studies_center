# Progresso — esperanca-de-vida-teste

## Fase 1 — Plano

Feito: `plano.md` com 5 perguntas sobre esperança de vida à nascença (evolução em Portugal,
diferença homens/mulheres, comparação com a UE, diferenças regionais NUTS II, quebra em
torno de 2020), todas com eixo e fonte candidata (INE/Eurostat). Condição da fase confirmada
por `comum.checks`.

Falhou: nada.

Precisa de mim: nada por agora.

## Fase 2 — Fontes

Feito: `fontes.csv` com 4 fontes candidatas, testadas com pedidos reais às APIs. 3 testadas:
INE (indicador 0008459, esperança de vida por NUTS, sem desagregação por sexo), Eurostat
`DEMO_MLEXPEC` (série PT 1960–2024 e UE desde 2002, por sexo — cobre a maior parte das
perguntas) e Eurostat `DEMO_R_MLIFEXP` (regional NUTS II). Uma excluída: não há indicador
confirmado na API do INE para esperança de vida por sexo a nível nacional (só em PDF/XLS);
coberto em alternativa pelo Eurostat.

Falhou: a tentativa de encontrar um indicador INE por sexo (f04) — documentado como
excluída, não forçada.

Nota técnica para a extração: `comum.sources.eurostat.fetch_dataset` precisa do
`dataset_code` em maiúsculas (`"DEMO_MLEXPEC"`), não em minúsculas.

Precisa de mim: nada por agora.
