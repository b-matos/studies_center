"""Trend-break detection for a single time series.

Three detectors, matched to the three row-level `tipo` values in quebras.csv:
- `nivel`: a level shift, via ruptures PELT on the mean.
- `declive`: a change in slope, via ruptures PELT on a linear-trend cost model.
- `pico`: an isolated spike, via a robust (median/MAD) z-score.

Returns candidate breaks for the analista agent to record in quebras.csv; it is not
responsible for linking them to events (that is the historiador's job).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import ruptures as rpt

MIN_POINTS_FOR_BREAK_DETECTION = 8


@dataclass
class CandidateBreak:
    data: date
    tipo: str  # "nivel" | "declive" | "pico"
    magnitude: float
    metodo: str


def _as_series(dates: pd.Series, values: pd.Series) -> tuple[list[date], np.ndarray]:
    ordered = pd.DataFrame({"data": pd.to_datetime(dates), "valor": values}).sort_values("data")
    return list(ordered["data"].dt.date), ordered["valor"].to_numpy(dtype=float)


def detect_level_shifts(dates: pd.Series, values: pd.Series, *, penalty: float = 3.0) -> list[CandidateBreak]:
    ds, vs = _as_series(dates, values)
    if len(vs) < MIN_POINTS_FOR_BREAK_DETECTION:
        return []
    algo = rpt.Pelt(model="l2").fit(vs.reshape(-1, 1))
    bkps = algo.predict(pen=penalty)
    out = []
    for bkp in bkps[:-1]:  # last breakpoint from ruptures is always len(series)
        before, after = vs[:bkp], vs[bkp:]
        magnitude = float(np.mean(after) - np.mean(before))
        out.append(CandidateBreak(data=ds[bkp], tipo="nivel", magnitude=magnitude, metodo="ruptures.Pelt(l2)"))
    return out


def detect_slope_changes(dates: pd.Series, values: pd.Series, *, penalty: float = 3.0) -> list[CandidateBreak]:
    """A slope change shows up as a level shift in the first-differenced series, which is
    a more numerically stable detector than fitting ruptures' linear-cost model directly
    on a single short series."""
    ds, vs = _as_series(dates, values)
    if len(vs) < MIN_POINTS_FOR_BREAK_DETECTION:
        return []
    diffs = np.diff(vs)
    algo = rpt.Pelt(model="l2").fit(diffs.reshape(-1, 1))
    bkps = algo.predict(pen=penalty)
    out = []
    for bkp in bkps[:-1]:
        before_slope = _slope(np.arange(bkp + 1), vs[: bkp + 1])
        after_slope = _slope(np.arange(len(vs) - bkp), vs[bkp:])
        out.append(
            CandidateBreak(
                data=ds[bkp],
                tipo="declive",
                magnitude=float(after_slope - before_slope),
                metodo="ruptures.Pelt(l2) on first differences",
            )
        )
    return out


def detect_spikes(dates: pd.Series, values: pd.Series, *, z_threshold: float = 3.5) -> list[CandidateBreak]:
    ds, vs = _as_series(dates, values)
    if len(vs) < MIN_POINTS_FOR_BREAK_DETECTION:
        return []
    median = np.median(vs)
    mad = np.median(np.abs(vs - median)) or 1e-9
    robust_z = 0.6745 * (vs - median) / mad
    out = []
    for i, z in enumerate(robust_z):
        if abs(z) >= z_threshold:
            out.append(
                CandidateBreak(
                    data=ds[i],
                    tipo="pico",
                    magnitude=float(vs[i] - median),
                    metodo="robust_zscore(median/MAD)",
                )
            )
    return out


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2:
        return 0.0
    return float(np.polyfit(x, y, 1)[0])


def detect_all(dates: pd.Series, values: pd.Series) -> list[CandidateBreak]:
    return [
        *detect_level_shifts(dates, values),
        *detect_slope_changes(dates, values),
        *detect_spikes(dates, values),
    ]
