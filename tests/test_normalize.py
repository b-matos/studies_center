import pandas as pd

from common.normalize import to_long, write_clean


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
        indicator="obitos_totais",
        source_id="f1",
        unit="numero",
        date_col="ano",
        value_col="obitos",
        region_col="regiao_nuts2",
    )
    assert list(long_df.columns) == ["date", "region", "sex", "age", "indicator", "value", "unit", "source_id"]
    assert long_df.loc[0, "value"] == 1000
    assert long_df.loc[0, "region"] == "PT11"
    assert long_df.loc[0, "sex"] == ""


def test_write_clean_requires_canonical_columns(tmp_path) -> None:
    import pytest

    bad_df = pd.DataFrame({"date": ["2020-01-01"], "value": [1]})
    with pytest.raises(ValueError):
        write_clean(bad_df, tmp_path / "out.parquet")


def test_write_clean_round_trip(tmp_path) -> None:
    df = pd.DataFrame(
        {
            "date": ["2020-01-01"],
            "region": [""],
            "sex": [""],
            "age": [""],
            "indicator": ["obitos_totais"],
            "value": [1000.0],
            "unit": ["numero"],
            "source_id": ["f1"],
        }
    )
    out_path = tmp_path / "out.parquet"
    write_clean(df, out_path)
    reloaded = pd.read_parquet(out_path)
    assert reloaded.loc[0, "value"] == 1000.0
