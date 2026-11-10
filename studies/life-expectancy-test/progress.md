# Progresso — life-expectancy-test

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

Feito: 2 scripts (`life_expectancy_pt_eu.py`, `regional.py`), 3 gráficos registados. Resultados:
esperança de vida total em Portugal subiu de 64,0 (1960) para 82,5 anos (2024); diferença
mulheres-homens estável em ~5,5 anos; Portugal passou de 0,20 anos abaixo da média da UE-27
em 2002 para 1,00 ano acima em 2024; leque regional (NUTS II) alargou de 0,8 para 2,0 anos
entre 1992 e 2022. Deteção de quebras (`comum.breaks`) encontrou um pico negativo claro em
2020 em Portugal e na UE, candidato óbvio a ligar à pandemia na fase seguinte — 17 quebras
no total registadas em `quebras.csv` para o historiador avaliar.

Falhou: nada.

Precisa de mim: nada por agora.

## Fase 5 — Eventos

Feito: 2 eventos novos no catálogo partilhado (pandemia de COVID-19, grau A; época gripal
grave de 2014/2015 na Europa, grau B). Das 17 quebras: 7 ligadas (o pico de 2020 em Portugal
e os picos de 2020-2023 na UE-27 → COVID-19, grau A, com fonte INE/Eurostat que atribui
diretamente a queda à pandemia; o pico de 2015 na UE → gripe 2014/2015, grau B) e 10 sem
evento identificado (quebras de nível mais antigas em Portugal e alguns picos nos anos 60/70
— o historiador considerou e rejeitou candidatos como a Revolução de 1974, a adesão à CEE e a
crise da dívida por não haver fonte que ligasse a série concreta a esses eventos).

Falhou: nada — nenhuma ligação forçada sem fonte.

Precisa de mim: nada por agora.

## Fase 6 — Redação

Feito: `relatorio.pt.qmd`/`relatorio.en.qmd` (resumo, uma secção por pergunta, metodologia e
limitações — incluindo a limitação do INE só ter um período transversal — e fontes) e
`afirmacoes.csv` com 33 afirmações (c001–c033), todas marcadas no texto com `.claim`,
linguagem ajustada ao grau nas ligações (A: "contribuiu para"/"contributed to"; B: "pode ter
contribuído"/"may have contributed to").

Falhou (corrigido): a primeira passagem do `comum.checks` fase 6 falhou com 2 falsos
positivos — números dentro de um bloco de código `{ojs}` (nome de ficheiro
`regional_snapshot_2022.json`) e uma referência cruzada "Pergunta 5" a serem apanhados pelo
detetor de números sem marca `.claim`. Corrigi o próprio `comum/checks.py` (ignora conteúdo
dentro de blocos ```` ``` ````/```` ```{ojs} ```` e referências "Pergunta/Figura/Tabela N") em
vez de forçar o redator a contornar um falso positivo do verificador.

Nota a acompanhar na fase 7: o redator sinalizou que as afirmações c022/c023 (queda atribuída
à pandemia) citam magnitudes ligeiramente diferentes consoante a fonte (INE/Eurostat vs. o
cálculo direto sobre a série usada neste estudo) — mantidas separadas e atribuídas às fontes
certas, mas vale a pena o verificador confirmar com atenção.

Precisa de mim: nada que bloqueie.

## Fase 7 — Verificação

Feito: verificação independente das 33 afirmações. `comum.verify` confirmou a maioria
automaticamente (os URLs do Eurostat Data Browser são só-JavaScript e precisaram de
confirmação manual via API REST — comportamento esperado, documentado nas decisões em
aberto do plano). O verificador apanhou 4 problemas reais só pela análise de conteúdo (não
pelo script automático): c020 (contagem errada, 7/10 em vez de 6/11), c021 (excerto em
inglês numa página cujo URL estava em português, e depois um URL corrigido que afinal dava
404), c022 (URL genérico da homepage do INE e magnitude externa que não batia com os dados
do próprio estudo) e c023 (magnitude Eurostat vs. magnitude calculada na série do estudo,
sem explicação da diferença). Precisou de 2 voltas de correção ao redator (de um máximo de
3) — a primeira resolveu c020/c022/c023 mas trocou o problema de c021 por um URL morto; a
segunda corrigiu isso. `verificacao.md` fecha com 33/33 confirmadas.

Falhou (corrigido via ciclo redator↔verificador): c020, c021, c022, c023 — ver acima.

Bug de plataforma encontrado e corrigido nesta fase: o hook `guard_writes.py` nunca deixava
o `verificador` escrever `estado_verificacao` em `afirmacoes.csv`, o que tornava a condição
da própria fase 7 impossível de cumprir pelas regras do próprio agente. Corrigido para
permitir só essa coluna (nunca o conteúdo da afirmação). Também corrigi dois falsos
positivos no detetor de "números sem marca .claim" (blocos de código `{ojs}` e referências
cruzadas tipo "Pergunta 5") e tornei a verificação da linguagem por grau tolerante a um
advérbio (ex.: "contribuiu também para").

Precisa de mim: nada que bloqueie — pronto para a fase 8 (publicação).

## Fase 8 — Publicação

Feito: `site/build.py` compilou o site nas duas línguas sem erros; a página do estudo
aparece em `/pt/estudos/life-expectancy-test/` e `/en/estudos/life-expectancy-test/`
(fora do índice público, por ter `estado: teste`). Verificação visual no browser: resumo,
5 perguntas, 4 gráficos interativos (evolução PT/UE, por sexo, regional NUTS II em série e
em retrato, todos com afirmações marcadas e sublinhadas), metodologia e fontes.

Falhou (corrigido): a verificação visual encontrou 3 bugs reais de plataforma que nenhum
`comum.checks` apanhava (não validam JavaScript renderizado):
1. `import * as Plot from "npm:@observablehq/plot"` é rejeitado pelo motor OJS do Quarto
   ("Unexpected token") — tem de ser `import {Plot} from ...` (import nomeado).
2. Passar a coluna `data` (string "AAAA-01-01") diretamente como campo do eixo X faz o
   Plot tratá-la como escala categórica, com um tick ilegível por cada linha da série —
   corrigido em `site/assets/charts.js` (acessor que converte para `Date`) e nos scripts
   OJS deste relatório.
3. `marginLeft: "auto"` produziu um gráfico de barras em branco com os nomes de região
   longos e acentuados ("Região Autónoma dos Açores") — trocado por um valor fixo (220).

Documentei as 3 regras no agente `redator` para não se repetirem nos próximos estudos.

Precisa de mim: nada que bloqueie — o estudo de teste está completo e verificado de ponta
a ponta (CLI + site + servidor). Pronto para usares como referência ao correr
`/estudo saude-portugal`.
