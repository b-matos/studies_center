# Verificação — esperanca-de-vida-teste

## Método

1. Corrida determinística: `uv run python -m comum.verify estudos/esperanca-de-vida-teste`.
   Primeira ronda: 33 afirmações, 30 "FALHOU" — mas quase todas as falhas eram por um único
   motivo estrutural, não por erro de conteúdo: as páginas do Eurostat Data Browser
   (`https://ec.europa.eu/eurostat/databrowser/view/...`) usadas como `url` em c001-c013,
   c016-c019, c028-c033 são aplicações só-JavaScript. O fetch estático (httpx + BeautifulSoup)
   devolve apenas `"Skip to Content"` (15 caracteres), sem qualquer texto ou número. O script
   não tem forma de encontrar o excerto nessa página estática, por isso marca "FALHOU" mesmo
   quando o `calculo` recalculado a partir de `dados/clean/` bate certo com o `valor`
   registado (confirmado nos próprios logs: `computed=X, recorded=X` para todas estas linhas).
2. Para resolver isto, verifiquei à mão os valores de `dado` interrogando diretamente a API
   REST pública do Eurostat (`.../api/dissemination/statistics/1.0/data/<dataset>?format=JSON...`),
   que devolve os mesmos dados que alimentam o Data Browser mas em JSON estático, sem JS. Também
   usei WebFetch e fetch estático direto (httpx) para as páginas que não são do Eurostat Data
   Browser (OMS, ECDC, Eurostat Statistics Explained, INE).
3. Investiguei em detalhe c020-c023, incluindo o aviso do redator sobre c022/c023, e depois
   reconfirmei em duas voltas sucessivas de correção c020-c023 e, por fim, c021.

## Afirmações `dado` (c001-c019, c028-c033) — todas confirmadas

Consultei em direto a API Eurostat (`demo_mlexpec` para Portugal e UE-27; `demo_r_mlifexp`
para as regiões NUTS II) e a API JSON do INE (`varcd=0008459`) e os valores devolvidos
coincidem exatamente com os registados em `afirmacoes.csv` e com o valor recalculado por
`comum.verify` a partir de `dados/clean/`:

- c001-c009: PT e UE-27, 1960/2024/2002, total/mulheres/homens — confirmado via
  `demo_mlexpec` (ex.: PT 1960 T=64.0, PT 2024 T=82.5, PT 1960 F/M=66.7/61.1, PT 2024
  F/M=85.2/79.7, UE-27 2002=77.6, UE-27 2024=81.5).
- c010-c013: regiões NUTS II do Continente em 1992 e 2022 — confirmado via
  `demo_r_mlifexp` (1992: Norte=74.5 mínimo, Alentejo=75.3 máximo; 2022: Norte=82.3
  máximo, Alentejo=80.3 mínimo).
- c014-c015: já confirmadas automaticamente pelo script (API JSON do INE, `fuzzy match`).
- c016-c019: PT e UE-27, 2019 vs. 2020 — confirmado via `demo_mlexpec` (PT 2019=82.0,
  2020=81.4; UE-27 2019=81.1, 2020=80.3).
- c028-c029: diferenças mulheres−homens em PT (1960: 66.7−61.1=5.6; 2024: 85.2−79.7=5.5) —
  consistentes com os valores já confirmados em c003-c006.
- c030-c031: amplitude entre regiões NUTS II (1992: 75.3−74.5=0.8; 2022: 82.3−80.3=2.0) —
  consistentes com c010-c013.
- c032-c033: PT vs. média UE-27 (2002: 77.4−77.6=−0.2; 2024: 82.5−81.5=1.0) — consistentes
  com c007-c009.

Nenhuma destas afirmações tem erro de valor; a falha do script automático foi apenas por a
página de origem citada ser renderizada em JavaScript, não por o número estar errado.
`estado_verificacao = confirmada` para todas (c001-c019, c028-c033).

## c020 — confirmada (corrigida pelo redator)

O texto original dizia "17 mudanças candidatas... 7 ligadas a um evento concreto e 10 sem
evento identificado". Contei diretamente `quebras.csv` (17 linhas: 10 para PT, 7 para UE-27
— correto) e `ligacoes_eventos.csv` (`grep -c ",ligado," ligacoes_eventos.csv` = 6;
`grep -c "quebra_sem_evento"` = 11). Os números reais são 6 ligadas / 11 sem evento. O
redator corrigiu o texto (PT e EN) e `afirmacoes.csv` para "6... 11...", que agora corresponde
exatamente à contagem real. `estado_verificacao = confirmada`.

## c021 — confirmada (corrigida pelo redator em duas voltas)

Histórico das três versões verificadas:

1. **Original**: `url` apontava para a versão portuguesa do discurso da OMS, mas o
   `excerto` registado estava em inglês ("a global pandemic on 11 March 2020"), frase
   inexistente nessa página — falhou.
2. **1.ª correção**: o redator trocou o `url` para
   `https://www.who.int/director-general/speeches/detail/who-director-general-s-opening-remarks-at-the-media-briefing-on-covid-19---11-march-2020`,
   que devolvia **HTTP 404** (confirmei por fetch direto com `httpx` e por WebFetch) — falhou
   de novo, por um motivo diferente.
3. **2.ª correção (atual)**: `url` agora
   `https://www.who.int/news-room/speeches/item/who-director-general-s-opening-remarks-at-the-media-briefing-on-covid-19---11-march-2020`
   (a página certa, em inglês, sem o prefixo `/pt/`), `excerto` agora "characterized as a
   pandemic", e `texto_pt`/`texto_en` reescritos para "podia ser caracterizada como uma
   pandemia" / "could be characterized as a pandemic" (em vez de "declarou... pandemia
   global").

   Confirmei por fetch estático direto (httpx + BeautifulSoup, sem JS): a URL devolve
   **HTTP 200**, e o corpo do discurso contém literalmente a frase "We have therefore made
   the assessment that COVID-19 can be characterized as a pandemic", que inclui o excerto
   registado ("characterized as a pandemic") como substring exata. O texto da afirmação
   também ficou mais fiel à fonte: a OMS, nesse discurso de 11 de março de 2020, diz que a
   doença "pode ser caracterizada como pandemia", não usa literalmente a expressão "declarou
   pandemia global" — a nova redação em `texto_pt`/`texto_en` reflete isso com precisão.
   `estado_verificacao = confirmada`.

## c022 — confirmada (corrigida pelo redator)

Numa volta anterior tinha dois problemas: (1) `url` era apenas a homepage do INE, sem relação
com o excerto; (2) a magnitude "0,8 anos" atribuída ao Eurostat não correspondia à série
`demo_mlexpec` usada no resto do estudo (0,6 anos).

O redator reescreveu o texto para deixar de atribuir um número externo (0,8) a Portugal, e
em vez disso diz explicitamente que, **na série usada neste estudo**, a quebra em Portugal
foi de 82,0 para 81,4 (≈0,6 anos, remetendo para c016/c017), e liga essa quebra ao mesmo ano
em que o Eurostat documenta uma quebra na UE devida à pandemia. O `url` passou a ser o artigo
Eurostat Statistics Explained (partilhado com c023).

Confirmei por fetch estático direto (sem JS) da página Eurostat Statistics Explained citada
que o texto "With the outbreak of the COVID-19 pandemic in 2020, life expectancy at birth in
the EU decreased by 0.9 years to 80.4..." está lá, literalmente — o excerto registado
("fell by 0.9 years in 2020 (to 80.4 years)") é uma paráfrase fiel desse trecho. O valor
0,6 anos citado para Portugal já estava confirmado em c016/c017. Já não há números
inconsistentes dentro da própria afirmação. `estado_verificacao = confirmada`.

## c023 — confirmada (corrigida pelo redator)

O excerto já estava correto numa volta anterior (confirmei então, por fetch estático direto,
que a página Eurostat Statistics Explained contém literalmente "decreased by 0.9 years to
80.4 ... increase again in 2022 to 80.6 years ... surpassed the pre-pandemic level in 2023
with 81.4 years"). O problema era a falta de explicação da diferença face à série
`demo_mlexpec` usada no resto do relatório (0,8 anos / 80,3, não 0,9 / 80,4).

O redator manteve o excerto e o número do Eurostat (0,9/80,4) mas acrescentou ao texto uma
frase explícita a dizer que a série `demo_mlexpec` extraída para este estudo mostra uma
descida "de magnitude próxima mas não idêntica" (0,8 anos, 81,1→80,3, remetendo para
c018/c019), atribuindo a diferença a vintages/revisões de dados distintas entre a publicação
Statistics Explained e o extrato usado no estudo — e não a dois factos diferentes. Isto
resolve a ambiguidade: o leitor já não encontra dois números para "a mesma coisa" sem
explicação. `estado_verificacao = confirmada`.

## Restantes afirmações não-`dado`

- **c024 — confirmada.** O fetch direto da página Statistics Explained confirma
  literalmente "Life expectancy at birth started to increase again in 2022 to 80.6 years".
  O valor 80,6 coincide também com a série `demo_mlexpec` usada no estudo (UE-27 2022=80.6,
  confirmado via API Eurostat), pelo que aqui não há a discrepância de c022/c023.
- **c025 — confirmada.** A mesma página confirma "surpassed the pre-pandemic level in 2023
  with 81.4 years" — a afirmação não cita um valor numérico específico, apenas que 2023
  superou o nível de 2019, o que a fonte sustenta.
- **c026 — confirmada.** Confirmei por WebFetch o resumo do artigo do ECDC/Eurosurveillance
  citado: "the weekly number of excess deaths from all-causes among individuals ≥ 65 years
  of age in 14 European countries have been significantly higher than in the four previous
  winter seasons", associado a "influenza A(H3N2)". Corresponde ao texto da afirmação.
- **c027 — confirmada.** O mesmo resumo do ECDC não quantifica o efeito na esperança de vida
  agregada da UE-27, que é exatamente o que a afirmação diz (hedged como ligação de grau B,
  "pode ter contribuído", sem demonstração direta). Está corretamente cauteloso face à fonte.

## Resumo final

- **Confirmadas: 33 de 33** (c001-c033).
- Nenhuma afirmação por resolver; todas têm estado final.

`estado_verificacao` em `afirmacoes.csv` foi atualizado por mim (só essa coluna, exceção
explícita autorizada em `.claude/agents/verificador.md` e em `.claude/hooks/guard_writes.py`):
`confirmada` nas 33 linhas.

Confirmado com `uv run python -m comum.checks esperanca-de-vida-teste 7`:

```
[OK] fase 7 do estudo 'esperanca-de-vida-teste' está completa
```
