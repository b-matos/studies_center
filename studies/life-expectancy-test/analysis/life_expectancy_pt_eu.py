"""Evolução da esperança de vida à nascença em Portugal (total e por sexo) e
comparação com a média da UE-27, a partir de f02 (Eurostat DEMO_MLEXPEC).

Responde às perguntas 1, 2, 3 e 5 do plan.md:
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

from common.breaks import detect_level_shifts, detect_slope_changes, detect_spikes
from common.charts import export_series_json, register_chart
from common.csv_io import write_csv
from common.schemas import Break

STUDY_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = STUDY_DIR / "data" / "clean"
OUT_DIR = STUDY_DIR / "analysis" / "out"
QUEBRAS_PATH = STUDY_DIR / "breaks.csv"


def load_f02() -> pd.DataFrame:
    df = pd.read_parquet(CLEAN_DIR / "f02.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df


def series_pt_total(df: pd.DataFrame) -> pd.DataFrame:
    """Pergunta 1: Portugal, sexo=T, toda a série disponível (1960-2024)."""
    s = df[(df["region"] == "Portugal") & (df["sex"] == "T")].sort_values("date")
    return s


def series_pt_por_sex(df: pd.DataFrame) -> pd.DataFrame:
    """Pergunta 2: Portugal, M e F, para calcular a diferença (gap) ao longo do tempo."""
    s = df[(df["region"] == "Portugal") & (df["sex"].isin(["M", "F"]))].sort_values("date")
    return s


def series_pt_vs_ue(df: pd.DataFrame) -> pd.DataFrame:
    """Pergunta 3: Portugal vs. UE-27, sexo=T, no período em que ambas existem (2002-2024)."""
    s = df[(df["sex"] == "T") & (df["region"].isin(["Portugal", "União Europeia (27 países, 2020)"]))]
    s = s.sort_values(["region", "date"])
    return s


def calcular_gap_sex(df_sex: pd.DataFrame) -> pd.DataFrame:
    pivot = df_sex.pivot(index="date", columns="sex", values="value").reset_index()
    pivot["gap_F_minus_M"] = pivot["F"] - pivot["M"]
    return pivot


def detect_breaks_series(series: pd.DataFrame, *, series_id: str, source_note: str) -> list[Break]:
    """Pergunta 5: deteta quebras/desacelerações numa série anual (PT ou UE-27, sexo=T).

    Usa três detetores de common.breaks:
    - detect_level_shifts (penalty mais alto, 20, para não sobre-segmentar uma série
      monotonamente crescente em dezenas de "quebras" de 5 em 5 anos).
    - detect_slope_changes com a penalidade por defeito (3.0), para desacelerações de
      tendência mais sustentadas.
    - detect_spikes aplicado à série das diferenças ano-a-ano (variação anual), que é a
      forma mais sensível de apanhar um choque pontual como a queda de 2020 (COVID-19),
      que na série em nível não é extrema o suficiente para passar no limiar robusto de
      z-score, mas é claramente anómala na variação ano-a-ano.
    """
    dates = series["date"]
    values = series["value"]

    breaks: list[Break] = []
    seq = 0

    for c in detect_level_shifts(dates, values, penalty=20.0):
        seq += 1
        breaks.append(
            Break(
                id=f"q_{series_id}_{seq:02d}",
                series=series_id,
                axis="life-expectancy",
                date=c.date,
                type=c.type,
                magnitude=round(c.magnitude, 4),
                method=f"{c.method}, penalty=20.0",
                note=source_note,
            )
        )

    for c in detect_slope_changes(dates, values):
        seq += 1
        breaks.append(
            Break(
                id=f"q_{series_id}_{seq:02d}",
                series=series_id,
                axis="life-expectancy",
                date=c.date,
                type=c.type,
                magnitude=round(c.magnitude, 4),
                method=c.method,
                note=source_note,
            )
        )

    diffs = values.diff().iloc[1:]
    diff_dates = dates.iloc[1:]
    for c in detect_spikes(diff_dates, diffs, z_threshold=2.0):
        seq += 1
        breaks.append(
            Break(
                id=f"q_{series_id}_{seq:02d}",
                series=series_id,
                axis="life-expectancy",
                date=c.date,
                type=c.type,
                magnitude=round(c.magnitude, 4),
                method=f"{c.method} on year-over-year differences, z_threshold=2.0",
                note=(
                    f"{source_note} Pico na variação ano-a-ano (não no nível); magnitude é o "
                    "desvio da variação anual face à mediana."
                ),
            )
        )

    return breaks


def main() -> None:
    df = load_f02()

    pt_total = series_pt_total(df)
    pt_sex = series_pt_por_sex(df)
    pt_vs_ue = series_pt_vs_ue(df)
    gap = calcular_gap_sex(pt_sex)

    print("Pergunta 1 - Portugal, total, início e fim da série:")
    print(pt_total[["date", "value"]].iloc[[0, -1]].to_string(index=False))

    print("\nPergunta 2 - Gap F-M (primeiro e último ano disponível):")
    print(gap[["date", "F", "M", "gap_F_minus_M"]].iloc[[0, -1]].to_string(index=False))

    dates_pt = set(pt_vs_ue[pt_vs_ue["region"] == "Portugal"]["date"])
    dates_ue = set(pt_vs_ue[pt_vs_ue["region"] != "Portugal"]["date"])
    dates_common = dates_pt & dates_ue
    first_year_common, last_year_common = min(dates_common), max(dates_common)
    pt_start = pt_vs_ue[(pt_vs_ue["region"] == "Portugal") & (pt_vs_ue["date"] == first_year_common)]["value"].iloc[0]
    ue_start = pt_vs_ue[(pt_vs_ue["region"] != "Portugal") & (pt_vs_ue["date"] == first_year_common)]["value"].iloc[0]
    pt_end = pt_vs_ue[(pt_vs_ue["region"] == "Portugal") & (pt_vs_ue["date"] == last_year_common)]["value"].iloc[0]
    ue_end = pt_vs_ue[(pt_vs_ue["region"] != "Portugal") & (pt_vs_ue["date"] == last_year_common)]["value"].iloc[0]
    print(f"\nPergunta 3 - Diferença PT-UE em {first_year_common.date()}: {pt_start - ue_start:.2f} anos")
    print(f"Pergunta 3 - Diferença PT-UE em {last_year_common.date()}: {pt_end - ue_end:.2f} anos")

    ue_total = pt_vs_ue[pt_vs_ue["region"] != "Portugal"].sort_values("date")
    breaks_pt = detect_breaks_series(
        pt_total,
        series_id="esperanca_vida_PT_total",
        source_note="Detetado em f02 (Eurostat DEMO_MLEXPEC), Portugal, sexo=T, 1960-2024.",
    )
    breaks_ue = detect_breaks_series(
        ue_total,
        series_id="esperanca_vida_UE27_total",
        source_note="Detetado em f02 (Eurostat DEMO_MLEXPEC), União Europeia (27 países, 2020), sexo=T, 2002-2024.",
    )
    breaks = breaks_pt + breaks_ue
    print(f"\nPergunta 5 - {len(breaks)} quebra(s)/mudança(s) candidata(s) detetada(s) (PT + UE):")
    for q in breaks:
        print(f"  [{q.series}] {q.date} type={q.type} magnitude={q.magnitude} method={q.method}")
    write_csv(QUEBRAS_PATH, Break, breaks)

    # Export dos dados do gráfico principal (PT total + por sexo + UE) para o browser.
    export_df = pd.concat(
        [
            pt_total.assign(indicator="life_expectancy_at_birth"),
            pt_sex.assign(indicator="life_expectancy_at_birth"),
            pt_vs_ue[pt_vs_ue["region"] != "Portugal"].assign(indicator="life_expectancy_at_birth"),
        ],
        ignore_index=True,
    )
    export_df["date"] = export_df["date"].dt.strftime("%Y-%m-%d")
    export_df = export_df[["date", "region", "sex", "age", "indicator", "value", "unit", "source_id"]]
    export_series_json(export_df, OUT_DIR / "life_expectancy_pt_eu.json")

    register_chart(
        STUDY_DIR,
        chart_id="life_expectancy_pt_eu",
        data_file="life_expectancy_pt_eu.json",
        axis="life-expectancy",
        title_pt="Esperança de vida à nascença em Portugal (total e por sexo) e na UE-27, 1960-2024",
        title_en="Life expectancy at birth in Portugal (total and by sex) and the EU-27, 1960-2024",
    )

    print(f"\nGráfico exportado para {OUT_DIR / 'life_expectancy_pt_eu.json'} e registado em charts.yml")


if __name__ == "__main__":
    main()
