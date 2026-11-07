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

## Fase 4 — Análise

Feito: 2 scripts (`evolucao_pt_ue.py`, `regional.py`), 3 gráficos registados. Resultados:
esperança de vida total em Portugal subiu de 64,0 (1960) para 82,5 anos (2024); diferença
mulheres-homens estável em ~5,5 anos; Portugal passou de 0,20 anos abaixo da média da UE-27
em 2002 para 1,00 ano acima em 2024; leque regional (NUTS II) alargou de 0,8 para 2,0 anos
entre 1992 e 2022. Deteção de quebras (`comum.breaks`) encontrou um pico negativo claro em
2020 em Portugal e na UE, candidato óbvio a ligar à pandemia na fase seguinte — 17 quebras
no total registadas em `quebras.csv` para o historiador avaliar.

Falhou: nada.

Precisa de mim: nada por agora.
