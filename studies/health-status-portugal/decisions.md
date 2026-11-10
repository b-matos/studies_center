# Decisões do utilizador

## 2026-11-10T17:00:00Z

Pergunta (resumo): pergunta 5 (excesso de mortalidade semanal) ficou sem fonte Eurostat testada (`eac14` expirou, `eac15` deu HTTP 405).

Resposta do utilizador: seguir a recomendação do orquestrador (opção 2). Procurar uma fonte alternativa para a mortalidade semanal (por exemplo `demo_r_mwk_ts` ou a mortalidade diária da DGS), com **uma só tentativa** e o probe leve (`common.probe eurostat:<código>`). Se não resultar, retirar `eac14` e `eac15` e seguir em frente: o relatório declara nas limitações que o excesso de mortalidade semanal não foi coberto. Não parar por isto. Antes de decidir, voltar a correr `complete-phase 2`: com a regra atual (timeout só bloqueia eixos sem fonte testada) a verificação já passa.
