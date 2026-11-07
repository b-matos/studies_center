"""Normalize source data into the canonical long format used across dados/clean/.

Canonical columns: data, regiao, sexo, idade, indicador, valor, unidade, fonte_id.
`data` is an ISO date (annual series use YYYY-01-01); `regiao`/`sexo`/`idade` are
optional ('' when the series has no such dimension).
"""
from __future__ import annotations

import pandas as pd

CANONICAL_COLUMNS = ["data", "regiao", "sexo", "idade", "indicador", "valor", "unidade", "fonte_id"]


def to_long(
    df: pd.DataFrame,
    *,
    indicador: str,
    fonte_id: str,
    unidade: str,
    data_col: str,
    valor_col: str,
    regiao_col: str | None = None,
    sexo_col: str | None = None,
    idade_col: str | None = None,
) -> pd.DataFrame:
    """Reshape an arbitrary source DataFrame into the canonical long schema."""
    out = pd.DataFrame(
        {
            "data": pd.to_datetime(df[data_col]).dt.date.astype(str),
            "regiao": df[regiao_col] if regiao_col else "",
            "sexo": df[sexo_col] if sexo_col else "",
            "idade": df[idade_col] if idade_col else "",
            "indicador": indicador,
            "valor": pd.to_numeric(df[valor_col], errors="coerce"),
            "unidade": unidade,
            "fonte_id": fonte_id,
        }
    )
    return out[CANONICAL_COLUMNS]


def write_clean(df: pd.DataFrame, path) -> None:
    missing = set(CANONICAL_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame is missing canonical columns: {sorted(missing)}")
    df[CANONICAL_COLUMNS].to_parquet(path, index=False)
