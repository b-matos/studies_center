import numpy as np
import pandas as pd

from common.breaks import detect_level_shifts, detect_slope_changes, detect_spikes


def _dates(n: int) -> pd.Series:
    return pd.Series(pd.date_range("2000-01-01", periods=n, freq="YS"))


def test_detects_known_level_shift() -> None:
    values = pd.Series([10.0] * 15 + [30.0] * 15)
    breaks = detect_level_shifts(_dates(30), values, penalty=2.0)
    assert len(breaks) >= 1
    # the detected break should land close to index 15 (year 2015)
    years = [b.date.year for b in breaks]
    assert any(abs(y - 2015) <= 2 for y in years)


def test_detects_known_slope_change() -> None:
    flat = np.full(15, 10.0)
    rising = 10.0 + np.arange(15) * 5.0
    values = pd.Series(np.concatenate([flat, rising]))
    breaks = detect_slope_changes(_dates(30), values, penalty=2.0)
    assert len(breaks) >= 1


def test_detects_spike() -> None:
    values = pd.Series([10.0] * 10 + [10.0] * 9 + [1000.0])
    breaks = detect_spikes(_dates(20), values)
    assert len(breaks) == 1
    assert breaks[0].type == "peak"


def test_short_series_returns_nothing() -> None:
    values = pd.Series([1.0, 2.0, 3.0])
    assert detect_level_shifts(_dates(3), values) == []
    assert detect_slope_changes(_dates(3), values) == []
    assert detect_spikes(_dates(3), values) == []
