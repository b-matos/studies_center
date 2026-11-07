"""Evolução da esperança de vida à nascença em Portugal (total e por sexo) e
comparação com a média da UE-27, a partir de f02 (Eurostat DEMO_MLEXPEC).

Responde às perguntas 1, 2, 3 e 5 do plano.md:
1. Evolução da esperança de vida total em Portugal desde o início da série (1960) até ao
   ano mais recente (2024).
2. Diferença entre homens e mulheres em Portugal e a sua evolução.
3. Comparação de Portugal com a média da UE-27 ao longo do tempo (convergência/divergência).
5. Quebras, estagnações ou desacelerações na série portuguesa (ex.: em torno de 2020,
   COVID-19), e comparação com o que se observa na UE.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from comum.breaks import detect_level_shifts, detect_slope_changes, detect_spikes
from comum.charts import export_series_json, register_chart
from comum.csv_io import write_csv
from comum.schemas import Quebra

STUDY_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = STUDY_DIR / "dados" / "clean"
OUT_DIR = STUDY_DIR / "analise" / "out"
QUEBRAS_PATH = STUDY_DIR / "quebras.csv"


def carregar_f02() -> pd.DataFrame:
    df = pd.read_parquet(CLEAN_DIR / "f02.parquet")
    df["data"] = pd.to_datetime(df["data"])
    return df


def serie_pt_total(df: pd.DataFrame) -> pd.DataFrame:
    """Pergunta 1: Portugal, sexo=T, toda a série disponível (1960-2024)."""
    s = df[(df["regiao"] == "Portugal") & (df["sexo"] == "T")].sort_values("data")
    return s


def serie_pt_por_sexo(df: pd.DataFrame) -> pd.DataFrame:
    """Pergunta 2: Portugal, M e F, para calcular a diferença (gap) ao longo do tempo."""
    s = df[(df["regiao"] == "Portugal") & (df["sexo"].isin(["M", "F"]))].sort_values("data")
    return s


def serie_pt_vs_ue(df: pd.DataFrame) -> pd.DataFrame:
    """Pergunta 3: Portugal vs. UE-27, sexo=T, no período em que ambas existem (2002-2024)."""
    s = df[(df["sexo"] == "T") & (df["regiao"].isin(["Portugal", "União Europeia (27 países, 2020)"]))]
    s = s.sort_values(["regiao", "data"])
    return s


def calcular_gap_sexo(df_sexo: pd.DataFrame) -> pd.DataFrame:
    pivot = df_sexo.pivot(index="data", columns="sexo", values="valor").reset_index()
    pivot["gap_F_menos_M"] = pivot["F"] - pivot["M"]
    return pivot


def detetar_quebras_serie(serie: pd.DataFrame, *, serie_id: str, fonte_nota: str) -> list[Quebra]:
    """Pergunta 5: deteta quebras/desacelerações numa série anual (PT ou UE-27, sexo=T).

    Usa três detetores de comum.breaks:
    - detect_level_shifts (penalty mais alto, 20, para não sobre-segmentar uma série
      monotonamente crescente em dezenas de "quebras" de 5 em 5 anos).
    - detect_slope_changes com a penalidade por defeito (3.0), para desacelerações de
      tendência mais sustentadas.
    - detect_spikes aplicado à série das diferenças ano-a-ano (variação anual), que é a
      forma mais sensível de apanhar um choque pontual como a queda de 2020 (COVID-19),
      que na série em nível não é extrema o suficiente para passar no limiar robusto de
      z-score, mas é claramente anómala na variação ano-a-ano.
    """
    dates = serie["data"]
    values = serie["valor"]

    quebras: list[Quebra] = []
    seq = 0

    for c in detect_level_shifts(dates, values, penalty=20.0):
        seq += 1
        quebras.append(
            Quebra(
                id=f"q_{serie_id}_{seq:02d}",
                serie=serie_id,
                eixo="esperanca-de-vida",
                data=c.data,
                tipo=c.tipo,
                magnitude=round(c.magnitude, 4),
                metodo=f"{c.metodo}, penalty=20.0",
                nota=fonte_nota,
            )
        )

    for c in detect_slope_changes(dates, values):
        seq += 1
        quebras.append(
            Quebra(
                id=f"q_{serie_id}_{seq:02d}",
                serie=serie_id,
                eixo="esperanca-de-vida",
                data=c.data,
                tipo=c.tipo,
                magnitude=round(c.magnitude, 4),
                metodo=c.metodo,
                nota=fonte_nota,
            )
        )

    diffs = values.diff().iloc[1:]
    diff_dates = dates.iloc[1:]
    for c in detect_spikes(diff_dates, diffs, z_threshold=2.0):
        seq += 1
        quebras.append(
            Quebra(
                id=f"q_{serie_id}_{seq:02d}",
                serie=serie_id,
                eixo="esperanca-de-vida",
                data=c.data,
                tipo=c.tipo,
                magnitude=round(c.magnitude, 4),
                metodo=f"{c.metodo} on year-over-year differences, z_threshold=2.0",
                nota=(
                    f"{fonte_nota} Pico na variação ano-a-ano (não no nível); magnitude é o "
                    "desvio da variação anual face à mediana."
                ),
            )
        )

    return quebras


def main() -> None:
    df = carregar_f02()

    pt_total = serie_pt_total(df)
    pt_sexo = serie_pt_por_sexo(df)
    pt_vs_ue = serie_pt_vs_ue(df)
    gap = calcular_gap_sexo(pt_sexo)

    print("Pergunta 1 - Portugal, total, início e fim da série:")
    print(pt_total[["data", "valor"]].iloc[[0, -1]].to_string(index=False))

    print("\nPergunta 2 - Gap F-M (primeiro e último ano disponível):")
    print(gap[["data", "F", "M", "gap_F_menos_M"]].iloc[[0, -1]].to_string(index=False))

    datas_pt = set(pt_vs_ue[pt_vs_ue["regiao"] == "Portugal"]["data"])
    datas_ue = set(pt_vs_ue[pt_vs_ue["regiao"] != "Portugal"]["data"])
    datas_comuns = datas_pt & datas_ue
    primeiro_ano_comum, ultimo_ano_comum = min(datas_comuns), max(datas_comuns)
    pt_inicio = pt_vs_ue[(pt_vs_ue["regiao"] == "Portugal") & (pt_vs_ue["data"] == primeiro_ano_comum)]["valor"].iloc[0]
    ue_inicio = pt_vs_ue[(pt_vs_ue["regiao"] != "Portugal") & (pt_vs_ue["data"] == primeiro_ano_comum)]["valor"].iloc[0]
    pt_fim = pt_vs_ue[(pt_vs_ue["regiao"] == "Portugal") & (pt_vs_ue["data"] == ultimo_ano_comum)]["valor"].iloc[0]
    ue_fim = pt_vs_ue[(pt_vs_ue["regiao"] != "Portugal") & (pt_vs_ue["data"] == ultimo_ano_comum)]["valor"].iloc[0]
    print(f"\nPergunta 3 - Diferença PT-UE em {primeiro_ano_comum.date()}: {pt_inicio - ue_inicio:.2f} anos")
    print(f"Pergunta 3 - Diferença PT-UE em {ultimo_ano_comum.date()}: {pt_fim - ue_fim:.2f} anos")

    ue_total = pt_vs_ue[pt_vs_ue["regiao"] != "Portugal"].sort_values("data")
    quebras_pt = detetar_quebras_serie(
        pt_total,
        serie_id="esperanca_vida_PT_total",
        fonte_nota="Detetado em f02 (Eurostat DEMO_MLEXPEC), Portugal, sexo=T, 1960-2024.",
    )
    quebras_ue = detetar_quebras_serie(
        ue_total,
        serie_id="esperanca_vida_UE27_total",
        fonte_nota="Detetado em f02 (Eurostat DEMO_MLEXPEC), União Europeia (27 países, 2020), sexo=T, 2002-2024.",
    )
    quebras = quebras_pt + quebras_ue
    print(f"\nPergunta 5 - {len(quebras)} quebra(s)/mudança(s) candidata(s) detetada(s) (PT + UE):")
    for q in quebras:
        print(f"  [{q.serie}] {q.data} tipo={q.tipo} magnitude={q.magnitude} metodo={q.metodo}")
    write_csv(QUEBRAS_PATH, Quebra, quebras)

    # Export dos dados do gráfico principal (PT total + por sexo + UE) para o browser.
    export_df = pd.concat(
        [
            pt_total.assign(indicador="esperanca_vida_nascenca"),
            pt_sexo.assign(indicador="esperanca_vida_nascenca"),
            pt_vs_ue[pt_vs_ue["regiao"] != "Portugal"].assign(indicador="esperanca_vida_nascenca"),
        ],
        ignore_index=True,
    )
    export_df["data"] = export_df["data"].dt.strftime("%Y-%m-%d")
    export_df = export_df[["data", "regiao", "sexo", "idade", "indicador", "valor", "unidade", "fonte_id"]]
    export_series_json(export_df, OUT_DIR / "evolucao_pt_ue.json")

    register_chart(
        STUDY_DIR,
        chart_id="evolucao_pt_ue",
        data_file="evolucao_pt_ue.json",
        eixo="esperanca-de-vida",
        titulo_pt="Esperança de vida à nascença em Portugal (total e por sexo) e na UE-27, 1960-2024",
        titulo_en="Life expectancy at birth in Portugal (total and by sex) and the EU-27, 1960-2024",
    )

    print(f"\nGráfico exportado para {OUT_DIR / 'evolucao_pt_ue.json'} e registado em graficos.yml")


if __name__ == "__main__":
    main()
