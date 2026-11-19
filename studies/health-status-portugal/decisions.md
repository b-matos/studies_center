# Decisões do utilizador

## 2026-11-10T17:00:00Z

Pergunta (resumo): pergunta 5 (excesso de mortalidade semanal) ficou sem fonte Eurostat testada (`eac14` expirou, `eac15` deu HTTP 405).

Resposta do utilizador: seguir a recomendação do orquestrador (opção 2). Procurar uma fonte alternativa para a mortalidade semanal (por exemplo `demo_r_mwk_ts` ou a mortalidade diária da DGS), com **uma só tentativa** e o probe leve (`common.probe eurostat:<código>`). Se não resultar, retirar `eac14` e `eac15` e seguir em frente: o relatório declara nas limitações que o excesso de mortalidade semanal não foi coberto. Não parar por isto. Antes de decidir, voltar a correr `complete-phase 2`: com a regra atual (timeout só bloqueia eixos sem fonte testada) a verificação já passa.

## Revisão: alterações pedidas (2026-11-19T16:36:53Z)

Retirado do site para refazer a análise. O detetor de quebras tinha um erro (pontos de quebra só em múltiplos de 5 anos desde o início da série, penalidades dependentes da escala, degraus de tendência lidos como quebras): com o detetor corrigido, só 12 das 51 quebras publicadas se confirmam (6 deslocadas 2 a 3 anos, 33 não encontradas, 13 novas). Refazer a fase 4 com o detetor corrigido e tudo o que depende dela: eventos (fase 5), redação (6), verificação (7) e revisão. As ligações a eventos e o texto sobre mudanças de tendência têm de ser reescritos a partir das quebras novas. Atenção às séries de inquérito com degrau provável em 2014 (ih01), 2018 e 2019 (ih03, eac16): confirmar se são quebras reais antes de as descartar.
