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


def test_detect_for_frame_returns_one_table_for_all_series() -> None:
    import pandas as pd

    from common.breaks import detect_for_frame

    dates = pd.date_range("2000-01-01", periods=30, freq="YS")
    rising = [10.0 + 0.1 * i for i in range(30)]
    jump = [10.0] * 15 + [20.0] * 15
    frame = pd.concat([
        pd.DataFrame({"date": dates, "value": rising, "region": "A"}),
        pd.DataFrame({"date": dates, "value": jump, "region": "B"}),
    ])
    table = detect_for_frame(frame, group_by=["region"])
    assert set(table["region"]) == {"B"}  # only the real level shift is flagged
    assert table.iloc[0]["type"] == "level" and table.iloc[0]["date"] == "2015-01-01"
