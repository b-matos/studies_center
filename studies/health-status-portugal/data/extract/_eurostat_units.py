"""Shared helper: Eurostat tables where `unit` varies; all other dimensions folded into `indicator`."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from common.extract import load_raw
from common.normalize import to_long

GEO = {"PT": "Portugal", "EU27_2020": "European Union (27)"}
SKIP = {"freq", "geo", "unit", "TIME_PERIOD", "value", "time", "OBS_FLAG", "obs_flag", "OBS_VALUE",
        "DATAFLOW", "LAST UPDATE", "sex", "age"}


def build_units(study_dir: Path, source_id: str, dataset: str, base: str, extra_dims: list[str],
                filename: str, geo_key: str = "PT+EU27_2020") -> pd.DataFrame:
    fetch = {
        "kind": "eurostat", "dataset": dataset, "key": {"geo": geo_key},
        "url": f"https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/{dataset.upper()}",
        "filename": filename,
    }
    raw = load_raw(study_dir, fetch).copy()
    raw["geo"] = raw["geo"].map(GEO).fillna(raw["geo"])
    raw["time"] = raw["TIME_PERIOD"].astype(str).str.strip().str[:4] + "-01-01"
    raw["indicator"] = base
    # Dimension names differ by table: auto-detect any column not in SKIP (extra_dims kept as hint only).
    dims = [c for c in raw.columns if c not in SKIP and c not in ("indicator",)]
    for dim in dims:
        raw["indicator"] = raw["indicator"] + "|" + dim + "=" + raw[dim].astype(str)
    raw["unit"] = raw["unit"].astype(str)
    out = to_long(raw, indicator="x", source_id=source_id, unit="x", date_col="time",
                  value_col="value", region_col="geo",
                  sex_col="sex" if "sex" in raw.columns else None,
                  age_col="age" if "age" in raw.columns else None)
    out["indicator"] = raw["indicator"].to_numpy()
    out["unit"] = raw["unit"].to_numpy()
    return out.dropna(subset=["value"]).reset_index(drop=True)
