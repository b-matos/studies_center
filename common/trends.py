"""Trend statistics per series and exploratory correlations between series, all computed by code.

The writer has no shell, so it cannot compute a trend or a correlation. This module does it once,
deterministically, from the chart series (matched to `data/clean/` by `common.summarize`), and writes:

- `analysis/trends.csv`: per series, a Theil-Sen slope per year with its 95% interval, a
  Mann-Kendall test (Kendall's tau of value against time), the total change and a direction
  (`increasing` / `decreasing` / `no_clear_trend` / `insufficient_data`). p-values are corrected over
  every series tested (Benjamini-Hochberg), because testing hundreds of series finds "trends" by chance.
- `analysis/correlations.csv`: Spearman correlations between Portugal total series from *different*
  charts, computed on first differences. Two series that merely both rise would correlate strongly in
  levels; differences remove that, so what is left is co-movement year to year. Also BH-corrected.
  These are associations, never causes (principle 3); mechanical links (a share and its total) can
  still show up and the writer must say so.

Each row has a `calculation` the verifier can recompute from `data/clean/` (see `slope`, `corr_diff`
and `clean` in `common.verify`); series that the analysis derived (no clean file) get none.

    uv run python -m common.trends <slug>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from common.summarize import SERIES_KEYS, TOTAL_SEX, iter_chart_frames

MIN_TREND_POINTS = 6
MIN_COMMON_POINTS = 9  # 8 first differences
ALPHA = 0.05
MIN_ABS_RHO = 0.5
TRENDS_NAME = "trends.csv"
CORRELATIONS_NAME = "correlations.csv"


def _clean_series(d: pd.DataFrame) -> pd.DataFrame:
    out = d[["date", "value"]].dropna().copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out.drop_duplicates("date").sort_values("date")


def _years(dates: pd.Series) -> pd.Series:
    dt = pd.to_datetime(dates)
    return dt.dt.year + (dt.dt.day_of_year - 1) / 365.25


def slope(d: pd.DataFrame) -> float:
    """Theil-Sen slope of value per year (robust to outliers)."""
    s = _clean_series(d)
    return float(stats.theilslopes(s["value"].to_numpy(float), _years(s["date"]).to_numpy(float))[0])


def corr_diff(a: pd.DataFrame, b: pd.DataFrame) -> float:
    """Spearman rho between the first differences of two series on their common dates."""
    return _corr_diff(_clean_series(a).set_index("date")["value"], _clean_series(b).set_index("date")["value"])[0]


def _corr_diff(a: pd.Series, b: pd.Series) -> tuple[float, float, int]:
    joined = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(joined) < MIN_COMMON_POINTS:
        return float("nan"), float("nan"), 0
    diffs = joined.diff().dropna()
    if diffs.iloc[:, 0].nunique() < 2 or diffs.iloc[:, 1].nunique() < 2:
        return float("nan"), float("nan"), len(diffs)
    rho, p = stats.spearmanr(diffs.iloc[:, 0], diffs.iloc[:, 1])
    return float(rho), float(p), len(diffs)


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    """Adjusted p-values (q-values) controlling the false discovery rate."""
    n = len(p)
    if n == 0:
        return p
    order = np.argsort(p)
    ranked = p[order] * n / (np.arange(n) + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(adjusted, 0, 1)
    return out


def _query(region: str, sex: str, age: str, indicator: str) -> str | None:
    if any(ch in v for v in (region, sex, age, indicator) for ch in "'\"\\"):
        return None
    return f"region=='{region}' and sex=='{sex}' and age=='{age}' and indicator=='{indicator}'"


def _origin(group: pd.DataFrame) -> tuple[str, str, str, str] | None:
    """(clean file, sex, age, indicator) when every point of the series is in one clean file."""
    if (group["clean_file"] == "").any():
        return None
    combos = group[["clean_file", "c_sex", "c_age", "c_indicator"]].drop_duplicates()
    return tuple(combos.iloc[0]) if len(combos) == 1 else None  # type: ignore[return-value]


def _series_of(study_dir: Path):
    """Yield (chart_id, key, group, origin) for every series of every chart."""
    for chart_id, _entry, df in iter_chart_frames(study_dir):
        for key, group in df.groupby(SERIES_KEYS, sort=False):
            yield chart_id, key, group, _origin(group)


def compute_trends(study_dir: Path) -> pd.DataFrame:
    rows = []
    for chart_id, key, group, origin in _series_of(study_dir):
        region, sex, age, indicator, unit = key
        s = _clean_series(group)
        row = {"chart": chart_id, "region": region, "sex": sex, "age": age, "indicator": indicator, "unit": unit,
               "clean_file": origin[0] if origin else "", "n": len(s), "start": "", "end": "", "slope_per_year": "",
               "slope_ci_low": "", "slope_ci_high": "", "tau": "", "p_value": float("nan"), "total_change": "",
               "pct_change": "", "calculation": ""}
        if len(s) >= MIN_TREND_POINTS:
            y, x = s["value"].to_numpy(float), _years(s["date"]).to_numpy(float)
            sl, _, lo, hi = stats.theilslopes(y, x)
            tau, p = stats.kendalltau(x, y)
            row.update(start=s["date"].iloc[0], end=s["date"].iloc[-1], slope_per_year=sl, slope_ci_low=lo,
                       slope_ci_high=hi, tau=0.0 if np.isnan(tau) else tau, p_value=1.0 if np.isnan(p) else p,
                       total_change=y[-1] - y[0], pct_change=(y[-1] / y[0] - 1) * 100 if y[0] else "")
            if origin and (q := _query(region, origin[1], origin[2], origin[3])):
                row["calculation"] = f'slope(df.query("{q}"))'
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    tested = df["p_value"].notna()
    df["p_adj"] = float("nan")
    df.loc[tested, "p_adj"] = benjamini_hochberg(df.loc[tested, "p_value"].to_numpy(float))
    direction = np.where(~tested, "insufficient_data",
                         np.where(df["p_adj"] < ALPHA, np.where(df["slope_per_year"].replace("", 0).astype(float) >= 0,
                                                              "increasing", "decreasing"), "no_clear_trend"))
    df["direction"] = direction
    df.insert(0, "id", [f"t{i:04d}" for i in range(1, len(df) + 1)])
    return df


def compute_correlations(study_dir: Path) -> pd.DataFrame:
    """Pairs of Portugal total series from different charts, matched to a clean file (so verifiable)."""
    seen: set[tuple] = set()
    series = []
    for chart_id, key, group, origin in _series_of(study_dir):
        region, sex, age, indicator, unit = key
        if region != "Portugal" or sex not in TOTAL_SEX or age != "" or origin is None:
            continue
        if origin in seen or (q := _query(region, origin[1], origin[2], origin[3])) is None:
            continue
        seen.add(origin)
        s = _clean_series(group).set_index("date")["value"]
        series.append({"chart": chart_id, "label": f"{indicator} [{unit}]", "file": origin[0], "indicator": origin[3],
                       "query": q, "s": s})
    rows = []
    for i, a in enumerate(series):
        for b in series[i + 1:]:
            if a["chart"] == b["chart"] or (a["file"], a["indicator"]) == (b["file"], b["indicator"]):
                continue
            rho, p, n = _corr_diff(a["s"], b["s"])
            if np.isnan(p):
                continue
            rows.append({"chart_a": a["chart"], "label_a": a["label"], "file_a": a["file"],
                         "chart_b": b["chart"], "label_b": b["label"], "file_b": b["file"], "n_diff": n,
                         "rho": rho, "p_value": p,
                         "calculation": f"corr_diff(clean('{a['file']}').query(\"{a['query']}\"), "
                                        f"clean('{b['file']}').query(\"{b['query']}\"))"})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["q_value"] = benjamini_hochberg(df["p_value"].to_numpy(float))
    df["significant"] = np.where((df["q_value"] < ALPHA) & (df["rho"].abs() >= MIN_ABS_RHO), "yes", "no")
    df.insert(0, "id", [f"r{i:04d}" for i in range(1, len(df) + 1)])
    return df


def write_trends(study_dir: Path) -> tuple[int, int]:
    """Write trends.csv and correlations.csv; returns (series tested, pairs tested)."""
    analysis = study_dir / "analysis"
    trends, correlations = compute_trends(study_dir), compute_correlations(study_dir)
    trends.to_csv(analysis / TRENDS_NAME, index=False)
    correlations.to_csv(analysis / CORRELATIONS_NAME, index=False)
    return len(trends), len(correlations)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: uv run python -m common.trends <slug>", file=sys.stderr)
        return 2
    study_dir = Path(__file__).resolve().parent.parent / "studies" / args[0]
    if not (study_dir / "analysis" / "charts.yml").exists():
        print(f"no analysis/charts.yml for '{args[0]}'", file=sys.stderr)
        return 1
    n_trends, n_pairs = write_trends(study_dir)
    print(f"wrote analysis/{TRENDS_NAME} ({n_trends} series) and analysis/{CORRELATIONS_NAME} ({n_pairs} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
