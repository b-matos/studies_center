"""common.trends: robust trends, differenced correlations, FDR correction, verifiable calculations."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from common import trends, verify
from common.schemas import Claim


def _frame(values, start=2000) -> pd.DataFrame:
    return pd.DataFrame({"date": [f"{start + i}-01-01" for i in range(len(values))], "value": values})


def test_slope_is_per_year_and_robust_to_an_outlier() -> None:
    values = [10 + 2 * i for i in range(12)]
    values[5] = 500  # outlier: Theil-Sen barely moves
    assert abs(trends.slope(_frame(values)) - 2.0) < 0.2


def test_corr_diff_ignores_a_shared_trend() -> None:
    rng = np.random.default_rng(1)
    a = np.cumsum(np.abs(rng.normal(1, 0.3, 30)))  # both rise steadily...
    b = np.cumsum(np.abs(rng.normal(1, 0.3, 30)))  # ...but their year-to-year changes are independent
    assert pd.Series(a).corr(pd.Series(b), method="spearman") > 0.95  # levels look perfectly related
    assert abs(trends.corr_diff(_frame(a), _frame(b))) < 0.6


def test_corr_diff_finds_real_comovement() -> None:
    rng = np.random.default_rng(2)
    steps = rng.normal(0, 1, 30)
    a, b = np.cumsum(steps), np.cumsum(steps * 2 + rng.normal(0, 0.1, 30))
    assert trends.corr_diff(_frame(a), _frame(b)) > 0.9


def test_corr_diff_needs_enough_common_points() -> None:
    assert np.isnan(trends.corr_diff(_frame(range(5)), _frame(range(5))))


def test_benjamini_hochberg_adjusts_and_keeps_order() -> None:
    q = trends.benjamini_hochberg(np.array([0.01, 0.04, 0.03, 0.5]))
    assert np.allclose(q, [0.04, 0.0533333, 0.0533333, 0.5], atol=1e-6)


def _study(tmp_path: Path) -> Path:
    study = tmp_path / "demo"
    (study / "analysis" / "out").mkdir(parents=True)
    (study / "data" / "clean").mkdir(parents=True)
    years = [f"{y}-01-01" for y in range(2000, 2015)]
    clean = pd.DataFrame({"date": years, "region": "Portugal", "sex": "T", "age": "", "indicator": "x",
                          "value": [1 + 0.5 * i for i in range(15)], "unit": "U", "source_id": "f01"})
    clean.to_parquet(study / "data" / "clean" / "f01.parquet")
    rows = [{"date": d, "region": "Portugal", "sex": "T", "age": "", "indicator": "x", "value": v, "unit": "U"}
            for d, v in zip(years, clean["value"], strict=True)]
    (study / "analysis" / "out" / "c1.json").write_text(json.dumps(rows), encoding="utf-8")
    (study / "analysis" / "charts.yml").write_text(yaml.safe_dump({"c1": {"data_file": "c1.json"}}), encoding="utf-8")
    return study


def test_trend_row_has_a_calculation_the_verifier_can_recompute(tmp_path: Path) -> None:
    study = _study(tmp_path)
    df = trends.compute_trends(study)
    row = df.iloc[0]
    assert row["direction"] == "increasing" and abs(row["slope_per_year"] - 0.5) < 1e-6
    claim = Claim(id="c001", type="data", text_pt="t", text_en="t", value=str(round(row["slope_per_year"], 6)), unit="U/yr",
                  source_id="f01", url="https://x", access_date="2026-11-11", excerpt="x", source_nature="primary",
                  location="Q1", clean_file="f01.parquet", calculation=row["calculation"])
    computed, ok, _ = verify.recompute_dado(study, claim)
    assert ok and abs(computed - 0.5) < 1e-6
