"""Shared helper: Eurostat HLTH_SILC tables with extra dimensions folded into `indicator`."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from common.extract import load_raw
from common.normalize import to_long

GEO = {"PT": "Portugal", "EU27_2020": "European Union (27)"}


def build_multi(study_dir: Path, source_id: str, dataset: str, base: str, extra_dims: list[str],
                filename: str, unit_filter: str | None = "PC") -> pd.DataFrame:
    fetch = {
        "kind": "eurostat", "dataset": dataset, "key": {"geo": "PT+EU27_2020"},
        "url": f"https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/{dataset.upper()}",
        "filename": filename,
    }
    raw = load_raw(study_dir, fetch)
    if unit_filter and "unit" in raw.columns:
        raw = raw[raw["unit"] == unit_filter]
    raw = raw.copy()
    raw["geo"] = raw["geo"].map(GEO).fillna(raw["geo"])
    raw["time"] = raw["TIME_PERIOD"].astype(str).str.strip() + "-01-01"
    raw["indicator"] = base
    for dim in extra_dims:
        raw["indicator"] = raw["indicator"] + "|" + dim + "=" + raw[dim].astype(str)
    out = to_long(raw, indicator="x", source_id=source_id, unit="percent", date_col="time",
                  value_col="value", region_col="geo", sex_col="sex", age_col="age")
    out["indicator"] = raw["indicator"].to_numpy()
    return out.dropna(subset=["value"]).reset_index(drop=True)
