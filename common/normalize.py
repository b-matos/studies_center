"""Normalize source data into the canonical long format used across data/clean/.

Canonical columns: data, regiao, sexo, idade, indicador, valor, unidade, source_id.
`data` is an ISO date (annual series use YYYY-01-01); `regiao`/`sexo`/`idade` are
optional ('' when the series has no such dimension).
"""
from __future__ import annotations

import pandas as pd

CANONICAL_COLUMNS = ["date", "region", "sex", "age", "indicator", "value", "unit", "source_id"]


def to_long(
    df: pd.DataFrame,
    *,
    indicator: str,
    source_id: str,
    unit: str,
    date_col: str,
    value_col: str,
    region_col: str | None = None,
    sex_col: str | None = None,
    age_col: str | None = None,
) -> pd.DataFrame:
    """Reshape an arbitrary source DataFrame into the canonical long schema."""
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col]).dt.date.astype(str),
            "region": df[region_col] if region_col else "",
            "sex": df[sex_col] if sex_col else "",
            "age": df[age_col] if age_col else "",
            "indicator": indicator,
            "value": pd.to_numeric(df[value_col], errors="coerce"),
            "unit": unit,
            "source_id": source_id,
        }
    )
    return out[CANONICAL_COLUMNS]


def write_clean(df: pd.DataFrame, path) -> None:
    missing = set(CANONICAL_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame is missing canonical columns: {sorted(missing)}")
    df[CANONICAL_COLUMNS].to_parquet(path, index=False)
