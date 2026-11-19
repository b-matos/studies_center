import numpy as np
import pandas as pd

from common.breaks import (
    detect_for_frame,
    detect_level_shifts,
    detect_slope_changes,
    detect_spikes,
)


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


def _trend_step_spike_frame() -> pd.DataFrame:
    years = list(range(2000, 2024))
    values = [520 - 4 * i - (60 if y >= 2012 else 0) - (45 if y == 2020 else 0) for i, y in enumerate(years)]
    return pd.DataFrame({"date": pd.to_datetime([f"{y}-01-01" for y in years]), "region": "Portugal", "sex": "T", "value": values})


def test_a_lasting_jump_on_a_trending_series_is_a_level_shift_and_a_reverting_one_a_peak() -> None:
    table = detect_for_frame(_trend_step_spike_frame(), group_by=["region", "sex"])
    by_year = {(pd.Timestamp(r.date).year, r.type) for r in table.itertuples()}
    assert (2012, "level") in by_year, table
    assert (2012, "peak") not in by_year
    assert (2020, "peak") in by_year  # reverts the next year
    step = table[(pd.to_datetime(table["date"]).dt.year == 2012) & (table["type"] == "level")].iloc[0]
    assert -75 < step["magnitude"] < -45  # the step, not a trend artefact


def test_a_steady_trend_alone_no_longer_produces_evenly_spaced_level_shifts() -> None:
    years = list(range(2000, 2024))
    df = pd.DataFrame({"date": pd.to_datetime([f"{y}-01-01" for y in years]), "region": "Portugal", "sex": "T", "value": [500 - 4 * i for i in range(len(years))]})
    assert detect_for_frame(df, group_by=["region", "sex"]).query("type == 'level'").empty


def _yearly(values) -> tuple[pd.Series, pd.Series]:
    dates = pd.Series(pd.to_datetime([f"{2000 + i}-01-01" for i in range(len(values))]))
    return dates, pd.Series(np.asarray(values, dtype=float))


def test_level_shift_regression_finds_a_step_on_a_trend_at_the_right_year() -> None:
    from common.breaks import detect_level_shifts_vs_trend

    rng = np.random.default_rng(1)
    steps = detect_level_shifts_vs_trend(*_yearly(520 - 4 * np.arange(24) - np.where(np.arange(24) >= 12, 60, 0) + rng.normal(0, 3, 24)))
    assert [c.date.year for c in steps] == [2012]
    assert steps[0].magnitude < 0


def test_level_shift_regression_finds_the_ramp_between_two_plateaus() -> None:
    from common.breaks import detect_level_shifts_vs_trend

    rng = np.random.default_rng(2)
    ramp = np.interp(np.arange(24), [0, 11, 15, 23], [33, 34, 43, 44]) + rng.normal(0, 0.8, 24)
    years = [c.date.year for c in detect_level_shifts_vs_trend(*_yearly(ramp))]
    assert years and all(2011 <= y <= 2015 for y in years)


def test_level_shift_regression_ignores_trends_curves_and_noise() -> None:
    from common.breaks import detect_level_shifts_vs_trend

    rng = np.random.default_rng(3)
    quiet = {
        "steep clean trend": 500 - 20.0 * np.arange(24),
        "noisy trend": 100 - 3 * np.arange(24) + rng.normal(0, 3, 24),
        "saturating curve": 70 + 12 * (1 - np.exp(-np.arange(24) / 8)) + rng.normal(0, 0.25, 24),
    }
    for name, values in quiet.items():
        assert detect_level_shifts_vs_trend(*_yearly(values)) == [], name
    false_alarms = sum(bool(detect_level_shifts_vs_trend(*_yearly(100 + rng.normal(0, 3, 24)))) for _ in range(200))
    assert false_alarms <= 8, f"{false_alarms}/200 pure-noise series got a level shift"


def test_the_break_years_are_not_quantised_to_the_pelt_grid() -> None:
    from common.breaks import detect_level_shifts_vs_trend

    for year in (2003, 2007, 2011, 2013, 2017):
        values = np.where(np.arange(24) >= year - 2000, 20.0, 10.0)
        assert [c.date.year for c in detect_level_shifts_vs_trend(*_yearly(values))] == [year]
