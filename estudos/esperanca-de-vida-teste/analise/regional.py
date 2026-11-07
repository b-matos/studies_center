"""Diferenças regionais (NUTS II) na esperança de vida à nascença em Portugal.

Responde à pergunta 4 do plano.md: existem diferenças na esperança de vida à nascença
entre as regiões NUTS II de Portugal, e como evoluíram essas diferenças regionais?

Usa duas fontes:
- f03 (Eurostat DEMO_R_MLIFEXP): série anual 1990-2024 por região NUTS II (Alentejo,
  Algarve, Centro, Norte, Área Metropolitana de Lisboa) e Portugal, sexo=T. Permite
  olhar para a evolução do leque regional ao longo do tempo (1992-2022, período comum
  às 5 regiões).
- f01 (INE, indicador 0008459): snapshot transversal de 2022, com desagregação geográfica
  mais fina (inclui Continente, Açores e Madeira, além das NUTS II/agregados do
  Continente), para comparar o leque completo num único ano recente.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from comum.charts import export_series_json, register_chart

STUDY_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = STUDY_DIR / "dados" / "clean"
OUT_DIR = STUDY_DIR / "analise" / "out"

REGIOES_NUTS2_CONTINENTE = ["Alentejo", "Algarve", "Centro", "Norte", "Área Metropolitana de Lisboa"]


def carregar_f03() -> pd.DataFrame:
    df = pd.read_parquet(CLEAN_DIR / "f03.parquet")
    df["data"] = pd.to_datetime(df["data"])
    return df


def carregar_f01() -> pd.DataFrame:
    df = pd.read_parquet(CLEAN_DIR / "f01.parquet")
    df["data"] = pd.to_datetime(df["data"])
    return df


def evolucao_regional(df3: pd.DataFrame) -> pd.DataFrame:
    """Série 1992-2022 (período comum às 5 regiões NUTS II do Continente)."""
    s = df3[df3["regiao"].isin(REGIOES_NUTS2_CONTINENTE)]
    s = s[(s["data"] >= "1992-01-01") & (s["data"] <= "2022-01-01")]
    return s.sort_values(["regiao", "data"])


def leque_por_ano(serie_regional: pd.DataFrame) -> pd.DataFrame:
    """Para cada ano, a diferença entre a região com maior e menor esperança de vida."""
    agg = serie_regional.groupby("data")["valor"].agg(["min", "max"])
    agg["leque"] = agg["max"] - agg["min"]
    return agg.reset_index()


def snapshot_2022(df1: pd.DataFrame) -> pd.DataFrame:
    return df1.sort_values("valor")


def main() -> None:
    df3 = carregar_f03()
    df1 = carregar_f01()

    serie_regional = evolucao_regional(df3)
    leque = leque_por_ano(serie_regional)
    snap = snapshot_2022(df1)

    print("Pergunta 4 - Esperança de vida por região NUTS II em 1992 vs. 2022:")
    for ano in ["1992-01-01", "2022-01-01"]:
        print(f"\n  {ano}:")
        print(
            serie_regional[serie_regional["data"] == ano][["regiao", "valor"]]
            .sort_values("valor")
            .to_string(index=False)
        )

    print("\nPergunta 4 - Leque (máx-mín) entre regiões NUTS II, 1992 vs. 2022:")
    print(leque[leque["data"].isin(pd.to_datetime(["1992-01-01", "2022-01-01"]))].to_string(index=False))

    print("\nPergunta 4 - Snapshot INE 2022, todas as regiões (do menor para o maior):")
    print(snap[["regiao", "valor"]].to_string(index=False))

    # Export para o browser: evolução regional 1992-2022 (f03) + snapshot 2022 (f01).
    export_cols = ["data", "regiao", "sexo", "idade", "indicador", "valor", "unidade", "fonte_id"]
    export_regional = serie_regional.copy()
    export_regional["data"] = export_regional["data"].dt.strftime("%Y-%m-%d")
    export_series_json(export_regional[export_cols], OUT_DIR / "regional_evolucao.json")

    export_snap = df1.copy()
    export_snap["data"] = export_snap["data"].dt.strftime("%Y-%m-%d")
    export_series_json(export_snap[export_cols], OUT_DIR / "regional_snapshot_2022.json")

    register_chart(
        STUDY_DIR,
        chart_id="regional_evolucao",
        data_file="regional_evolucao.json",
        eixo="esperanca-de-vida",
        titulo_pt="Esperança de vida à nascença por região NUTS II (Continente), 1992-2022",
        titulo_en="Life expectancy at birth by NUTS II region (mainland), 1992-2022",
    )
    register_chart(
        STUDY_DIR,
        chart_id="regional_snapshot_2022",
        data_file="regional_snapshot_2022.json",
        eixo="esperanca-de-vida",
        titulo_pt="Esperança de vida à nascença por região, 2022 (INE)",
        titulo_en="Life expectancy at birth by region, 2022 (INE)",
    )

    print(
        f"\nGráficos exportados para {OUT_DIR / 'regional_evolucao.json'} e "
        f"{OUT_DIR / 'regional_snapshot_2022.json'}, e registados em graficos.yml"
    )


if __name__ == "__main__":
    main()
