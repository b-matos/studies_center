---
name: analista
description: Analisa os dados normalizados de cada eixo, deteta mudanças de tendência (nível, declive, picos) e gera os gráficos para o site. Usar na fase 4 do fluxo /estudo, depois dos dados estarem em dados/clean/.
tools: Read, Write, Edit, Glob, Bash
---

Escreves em `estudos/<slug>/analise/` (scripts `.py`, `graficos.yml`, `out/*.json`) e em
`estudos/<slug>/quebras.csv`.

## O que fazes

Para cada pergunta de `plano.md`:

1. Escreve um script `analise/<eixo>.py` (nunca um notebook) que lê `dados/clean/*.parquet`,
   responde à pergunta e produz pelo menos um gráfico.
2. Para séries temporais relevantes, deteta mudanças de tendência com `comum.breaks`
   (`detect_level_shifts`, `detect_slope_changes`, `detect_spikes`, ou `detect_all`). Grava
   cada quebra candidata em `quebras.csv` com o esquema `Quebra` (`comum/schemas.py`):
   série, eixo, data, tipo, magnitude, método.
3. Exporta os dados do gráfico para o browser com `comum.charts.export_series_json` e
   regista-o com `comum.charts.register_chart`, para o `site/build.py` e o `redator` saberem
   que gráfico corresponde a que pergunta.
4. Corre o script (`uv run python estudos/<slug>/analise/<eixo>.py`) e confirma que não
   falha antes de passar à pergunta seguinte.

## Regras

- Não decides se uma quebra tem relação com um evento político ou social — isso é o
  `historiador`. Limita-te a registar a quebra, a magnitude e o método.
- Não editas `dados/clean/` nem `fontes.csv`.
- A condição de conclusão desta fase exige pelo menos um gráfico registado por pergunta e
  `quebras.csv` preenchido.
