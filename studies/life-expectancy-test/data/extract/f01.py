"""f01 (INE 0008459): nested JSON -> canonical long rows for the 2020-2022 triennium (dated 2022)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common.normalize import to_long

RAW_FILE = "f01_ine_0008459.json"
# NUTS II regions plus the mainland / autonomous-region aggregates (NUTS III is out of scope).
GEO_CODES = {"1", "11", "15", "16", "17", "18", "2", "3"}


def build(study_dir: Path) -> pd.DataFrame:
    payload = json.loads((study_dir / "data" / "raw" / RAW_FILE).read_text(encoding="utf-8"))[0]
    period, rows = next(iter(payload["Dados"].items()))
    df = pd.DataFrame(rows).query("geocod in @GEO_CODES").assign(date="2022-01-01")
    long = to_long(
        df, indicator="life_expectancy_at_birth", source_id="f01", unit="anos",
        date_col="date", value_col="valor", region_col="geodsg",
    )
    return long.sort_values("value").reset_index(drop=True)
