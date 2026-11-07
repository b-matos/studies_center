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
`dataset_code` em maiúsculas (`"DEMO_MLEXPEC"`), não em minúsculas (entretanto corrigido no
próprio cliente, para não repetir o erro noutros estudos).

Precisa de mim: nada por agora.

## Fase 3 — Extração

Feito: as 3 fontes testadas foram descarregadas (`dados/raw/`, com manifesto de proveniência)
e normalizadas para `dados/clean/` em formato longo: `f01.parquet` (INE, snapshot NUTS II
2020–2022, 8 linhas), `f02.parquet` (Eurostat DEMO_MLEXPEC, PT 1960–2024 / UE desde 2002,
por sexo, 264 linhas) e `f03.parquet` (Eurostat DEMO_R_MLIFEXP, regional NUTS II 1990–2024,
196 linhas). Valores conferidos contra os publicados (ex.: PT 2023 = 82.3 anos em f02 e f03,
consistente). `comum.download.verify_manifest` sem problemas.

Falhou/limitação: f01 (INE) só tem um período transversal (2020-2022), não uma série
temporal — a API `json_indicador` não devolveu histórico sem um código `Dim1` por triénio
que não foi possível confirmar nesta fase. Isto não bloqueia o estudo (a pergunta 1/2/5 do
plano ficam cobertas pelo Eurostat), mas limita a pergunta 4 (regional) a um único ano.

Precisa de mim: nada que bloqueie — é uma limitação de dados a mencionar no relatório, não
uma decisão a tomar agora.
