"""Diferenças regionais (NUTS II) na esperança de vida à nascença em Portugal.

Responde à pergunta 4 do plan.md: existem diferenças na esperança de vida à nascença
entre as regiões NUTS II de Portugal, e como evoluíram essas diferenças regionais?

Usa duas fontes:
- f03 (Eurostat DEMO_R_MLIFEXP): série anual 1990-2024 por região NUTS II (Alentejo,
  Algarve, Centro, Norte, Área Metropolitana de Lisboa) e Portugal, sexo=T. Permite
  olhar para a evolução do leque regional ao longo do tempo (1992-2022, período common
  às 5 regiões).
- f01 (INE, indicador 0008459): snapshot transversal de 2022, com desagregação geográfica
  mais fina (inclui Continente, Açores e Madeira, além das NUTS II/agregados do
  Continente), para comparar o leque completo num único ano recente.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from common.charts import export_series_json, register_chart

STUDY_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = STUDY_DIR / "data" / "clean"
OUT_DIR = STUDY_DIR / "analysis" / "out"

REGIOES_NUTS2_CONTINENTE = ["Alentejo", "Algarve", "Centro", "Norte", "Área Metropolitana de Lisboa"]


def load_f03() -> pd.DataFrame:
    df = pd.read_parquet(CLEAN_DIR / "f03.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_f01() -> pd.DataFrame:
    df = pd.read_parquet(CLEAN_DIR / "f01.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df


def evolucao_regional(df3: pd.DataFrame) -> pd.DataFrame:
    """Série 1992-2022 (período common às 5 regiões NUTS II do Continente)."""
    s = df3[df3["region"].isin(REGIOES_NUTS2_CONTINENTE)]
    s = s[(s["date"] >= "1992-01-01") & (s["date"] <= "2022-01-01")]
    return s.sort_values(["region", "date"])


def spread_por_year(series_regional: pd.DataFrame) -> pd.DataFrame:
    """Para cada ano, a diferença entre a região com maior e menor esperança de vida."""
    agg = series_regional.groupby("date")["value"].agg(["min", "max"])
    agg["leque"] = agg["max"] - agg["min"]
    return agg.reset_index()


def snapshot_2022(df1: pd.DataFrame) -> pd.DataFrame:
    return df1.sort_values("value")


def main() -> None:
    df3 = load_f03()
    df1 = load_f01()

    series_regional = evolucao_regional(df3)
    spread = spread_por_year(series_regional)
    snap = snapshot_2022(df1)

    print("Pergunta 4 - Esperança de vida por região NUTS II em 1992 vs. 2022:")
    for year in ["1992-01-01", "2022-01-01"]:
        print(f"\n  {year}:")
        print(
            series_regional[series_regional["date"] == year][["region", "value"]]
            .sort_values("value")
            .to_string(index=False)
        )

    print("\nPergunta 4 - Leque (máx-mín) entre regiões NUTS II, 1992 vs. 2022:")
    print(spread[spread["date"].isin(pd.to_datetime(["1992-01-01", "2022-01-01"]))].to_string(index=False))

    print("\nPergunta 4 - Snapshot INE 2022, todas as regiões (do menor para o maior):")
    print(snap[["region", "value"]].to_string(index=False))

    # Export para o browser: evolução regional 1992-2022 (f03) + snapshot 2022 (f01).
    export_cols = ["date", "region", "sex", "age", "indicator", "value", "unit", "source_id"]
    export_regional = series_regional.copy()
    export_regional["date"] = export_regional["date"].dt.strftime("%Y-%m-%d")
    export_series_json(export_regional[export_cols], OUT_DIR / "regional_evolution.json")

    export_snap = df1.copy()
    export_snap["date"] = export_snap["date"].dt.strftime("%Y-%m-%d")
    export_series_json(export_snap[export_cols], OUT_DIR / "regional_snapshot_2022.json")

    register_chart(
        STUDY_DIR,
        chart_id="regional_evolution",
        data_file="regional_evolution.json",
        axis="life-expectancy",
        title_pt="Esperança de vida à nascença por região NUTS II (Continente), 1992-2022",
        title_en="Life expectancy at birth by NUTS II region (mainland), 1992-2022",
    )
    register_chart(
        STUDY_DIR,
        chart_id="regional_snapshot_2022",
        data_file="regional_snapshot_2022.json",
        axis="life-expectancy",
        title_pt="Esperança de vida à nascença por região, 2022 (INE)",
        title_en="Life expectancy at birth by region, 2022 (INE)",
    )

    print(
        f"\nGráficos exportados para {OUT_DIR / 'regional_evolution.json'} e "
        f"{OUT_DIR / 'regional_snapshot_2022.json'}, e registados em charts.yml"
    )


if __name__ == "__main__":
    main()
