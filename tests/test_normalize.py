import pandas as pd

from comum.normalize import to_long, write_clean


def test_to_long_basic_reshape() -> None:
    source = pd.DataFrame(
        {
            "ano": ["2020-01-01", "2021-01-01"],
            "regiao_nuts2": ["PT11", "PT17"],
            "obitos": [1000, 1100],
        }
    )
    long_df = to_long(
        source,
        indicador="obitos_totais",
        fonte_id="f1",
        unidade="numero",
        data_col="ano",
        valor_col="obitos",
        regiao_col="regiao_nuts2",
    )
    assert list(long_df.columns) == ["data", "regiao", "sexo", "idade", "indicador", "valor", "unidade", "fonte_id"]
    assert long_df.loc[0, "valor"] == 1000
    assert long_df.loc[0, "regiao"] == "PT11"
    assert long_df.loc[0, "sexo"] == ""


def test_write_clean_requires_canonical_columns(tmp_path) -> None:
    import pytest

    bad_df = pd.DataFrame({"data": ["2020-01-01"], "valor": [1]})
    with pytest.raises(ValueError):
        write_clean(bad_df, tmp_path / "out.parquet")


def test_write_clean_round_trip(tmp_path) -> None:
    df = pd.DataFrame(
        {
            "data": ["2020-01-01"],
            "regiao": [""],
            "sexo": [""],
            "idade": [""],
            "indicador": ["obitos_totais"],
            "valor": [1000.0],
            "unidade": ["numero"],
            "fonte_id": ["f1"],
        }
    )
    out_path = tmp_path / "out.parquet"
    write_clean(df, out_path)
    reloaded = pd.read_parquet(out_path)
    assert reloaded.loc[0, "valor"] == 1000.0
