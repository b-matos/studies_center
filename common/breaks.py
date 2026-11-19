"""Trend-break detection for a single time series.

Three detectors, matched to the three row-level `type` values in breaks.csv:
- `nivel`: a level shift, via ruptures PELT on the mean.
- `declive`: a change in slope, via ruptures PELT on a linear-trend cost model.
- `pico`: an isolated spike, via a robust (median/MAD) z-score.

Returns candidate breaks for the analyst agent to record in breaks.csv; it is not
responsible for linking them to events (that is the historian's job).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import ruptures as rpt

MIN_POINTS_FOR_BREAK_DETECTION = 8
LEVEL_PENALTY = 8.0  # on the standardised series (variance 1): a split must explain this much of the squared error
SLOPE_PENALTY = 8.0


def _standardised(x: np.ndarray) -> np.ndarray:
    sd = float(np.std(x))
    return x / sd if sd > 0 else x


@dataclass
class CandidateBreak:
    date: dt.date
    type: str  # "nivel" | "declive" | "pico"
    magnitude: float
    method: str


def _as_series(dates: pd.Series, values: pd.Series) -> tuple[list[dt.date], np.ndarray]:
    ordered = pd.DataFrame({"date": pd.to_datetime(dates), "value": values}).sort_values("date")
    return list(ordered["date"].dt.date), ordered["value"].to_numpy(dtype=float)


def detect_level_shifts(dates: pd.Series, values: pd.Series, *, penalty: float = LEVEL_PENALTY) -> list[CandidateBreak]:
    ds, vs = _as_series(dates, values)
    if len(vs) < MIN_POINTS_FOR_BREAK_DETECTION:
        return []
    # jump=1: ruptures' default (jump=5) only allows break points at multiples of 5, which misdates every shift by up to two years.
    # The series is standardised so `penalty` means the same for a rate in the hundreds and a share below one.
    algo = rpt.Pelt(model="l2", min_size=2, jump=1).fit(_standardised(vs).reshape(-1, 1))
    bkps = algo.predict(pen=penalty)
    out = []
    for bkp in bkps[:-1]:  # last breakpoint from ruptures is always len(series)
        before, after = vs[:bkp], vs[bkp:]
        magnitude = float(np.mean(after) - np.mean(before))
        out.append(CandidateBreak(date=ds[bkp], type="level", magnitude=magnitude, method="ruptures.Pelt(l2)"))
    return out


def detect_slope_changes(dates: pd.Series, values: pd.Series, *, penalty: float = SLOPE_PENALTY) -> list[CandidateBreak]:
    """A slope change shows up as a level shift in the first-differenced series, which is
    a more numerically stable detector than fitting ruptures' linear-cost model directly
    on a single short series."""
    ds, vs = _as_series(dates, values)
    if len(vs) < MIN_POINTS_FOR_BREAK_DETECTION:
        return []
    diffs = np.diff(vs)
    algo = rpt.Pelt(model="l2", min_size=2, jump=1).fit(_standardised(diffs).reshape(-1, 1))
    bkps = algo.predict(pen=penalty)
    out = []
    for bkp in bkps[:-1]:
        before_slope = _slope(np.arange(bkp + 1), vs[: bkp + 1])
        after_slope = _slope(np.arange(len(vs) - bkp), vs[bkp:])
        out.append(
            CandidateBreak(
                date=ds[bkp],
                type="slope",
                magnitude=float(after_slope - before_slope),
                method="ruptures.Pelt(l2) on first differences",
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
                    date=ds[i],
                    type="peak",
                    magnitude=float(vs[i] - median),
                    method="robust_zscore(median/MAD)",
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


PERSISTENCE_WINDOW = 3  # points on each side used to tell a lasting step from a spike that reverts
PERSISTENCE_MIN_AFTER = 2  # points that must follow the jump
PERSISTENCE_SHARE = 0.6  # the level after must keep at least this share of the jump to count as a level shift


LEVEL_ALPHA = 0.001  # p-value a level shift must beat against "just a straight line" (strict: every position is tried)
TREND_DEGREE = 2  # the trend a step must beat: a parabola, so that smooth curves (saturating gains) are not read as steps
MIN_STEP_SHARE = 0.15  # a step must also be at least this share of the series range (the F-test alone flags tiny steps in clean series)
MIN_SIDE = 3  # points on each side of a level shift
MAX_LEVEL_BREAKS = 3
MIN_POINTS_FOR_SEGMENT = 8


def _design(t: np.ndarray, k: int | None, degree: int = 1) -> np.ndarray:
    columns = [t ** d for d in range(degree + 1)]
    if k is not None:
        columns.append((np.arange(len(t)) >= k).astype(float))
    return np.column_stack(columns)


def _sum_squares(y: np.ndarray, design: np.ndarray) -> tuple[float, np.ndarray]:
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ coef
    return float(resid @ resid), coef


def detect_level_shifts_vs_trend(dates: pd.Series, values: pd.Series, *, alpha: float = LEVEL_ALPHA, degree: int = TREND_DEGREE, min_step_share: float = MIN_STEP_SHARE) -> list[CandidateBreak]:
    """Level shifts that a straight line cannot explain, found by binary segmentation.

    For each candidate position the series is fitted as `trend + step`; the best position is kept only if that beats the plain
    straight line by an F-test at `alpha`. A steady trend (however steep) is fitted by the line, so it produces nothing, while a
    jump or a ramp between two plateaus, which the line cannot follow, produces one break. The same test is then applied to
    each side. It replaces PELT on the mean, which reads any trend as a string of fake shifts."""
    from scipy import stats

    ds, vs = _as_series(dates, values)
    found: list[tuple[int, float]] = []

    def search(lo: int, hi: int, depth: int) -> None:
        n = hi - lo
        if n < MIN_POINTS_FOR_SEGMENT or depth > MAX_LEVEL_BREAKS or len(found) >= MAX_LEVEL_BREAKS:
            return
        y, t = vs[lo:hi], np.arange(n, dtype=float)
        ss_line, _ = _sum_squares(y, _design(t, None, degree))
        best_k, best_ss, best_coef = None, ss_line, None
        for k in range(MIN_SIDE, n - MIN_SIDE + 1):
            ss, coef = _sum_squares(y, _design(t, k, degree))
            if ss < best_ss:
                best_k, best_ss, best_coef = k, ss, coef
        if best_k is None or best_ss <= 1e-12 * max(ss_line, 1.0) and ss_line <= 1e-9:
            return
        f_stat = (ss_line - best_ss) / max(best_ss / (n - degree - 2), 1e-12)
        if stats.f.sf(f_stat, 1, n - degree - 2) >= alpha:
            return
        if abs(best_coef[-1]) < min_step_share * float(np.ptp(vs)):
            return
        found.append((lo + best_k, float(best_coef[-1])))
        search(lo, lo + best_k, depth + 1)
        search(lo + best_k, hi, depth + 1)

    search(0, len(vs), 0)
    return [CandidateBreak(date=ds[k], type="level", magnitude=m, method="trend+step regression (F-test)") for k, m in sorted(found)]


def _label_persistent_jumps(spikes: list[CandidateBreak], dates: pd.Series, values: pd.Series) -> list[CandidateBreak]:
    """A year-over-year jump that stays is a level shift, one that reverts is a peak. The spike detector sees both as one big
    difference; the two mean different things for the report, so the label must say which."""
    ds, vs = _as_series(dates, values)
    index = {d: i for i, d in enumerate(ds)}
    out = []
    for c in spikes:
        i = index.get(c.date)
        if i is None or i < 2 or i > len(vs) - PERSISTENCE_MIN_AFTER:  # too close to an edge to tell a step from noise
            out.append(c)
            continue
        before = float(np.median(vs[max(0, i - PERSISTENCE_WINDOW):i]))
        after = float(np.median(vs[i:i + PERSISTENCE_WINDOW]))
        jump = c.magnitude  # the year-over-year difference at i
        lasting = abs(jump) > 0 and (after - before) * jump > 0 and abs(after - before) >= PERSISTENCE_SHARE * abs(jump)
        out.append(CandidateBreak(date=c.date, type="level" if lasting else "peak", magnitude=float(after - before) if lasting else c.magnitude,
                                  method="robust_zscore(diff) + persistence" if lasting else c.method))
    return out


def detect_for_frame(
    df: pd.DataFrame,
    *,
    group_by: list[str],
    level_penalty: float | None = None,  # ignored: level shifts use `level_alpha` now; kept so older scripts still call it
    level_alpha: float = LEVEL_ALPHA,
    slope_penalty: float = SLOPE_PENALTY,
    spike_z: float = 3.5,
) -> pd.DataFrame:
    """Candidate breaks for every series (one per `group_by` combination) of a long-format frame.

    Spikes are looked for in the year-over-year differences, where a one-off shock (e.g. 2020)
    stands out even when the level series is monotone; a big difference that persists is labelled a
    `level` shift, one that reverts a `peak`. Level shifts also come from `detect_level_shifts_vs_trend`: a
    `trend + step` fit that must beat a straight line by an F-test, so a steady trend yields nothing while a jump or a
    ramp between two plateaus does. (PELT on the mean read any trend as a string of fake shifts, so it is not used
    here; `detect_level_shifts` stays for series without a trend.) Slope changes use PELT on the first differences;
    its penalty is scale-free (the series are standardised). The analyst reviews this table and
    records the breaks worth keeping in breaks.csv; nothing here is written automatically.
    """
    rows = []
    for key, group in df.groupby(group_by, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        group = group.sort_values("date")
        dates, values = group["date"], group["value"]
        spikes = detect_spikes(dates.iloc[1:], values.diff().iloc[1:], z_threshold=spike_z)
        jumps = _label_persistent_jumps(spikes, dates, values)
        steps = detect_level_shifts_vs_trend(dates, values, alpha=level_alpha)
        # a one-year jump is found by both detectors: keep the regression's estimate, drop the duplicate
        jumps = [j for j in jumps if not (j.type == "level" and any(abs((j.date - st.date).days) <= 366 for st in steps))]
        found = [*steps, *detect_slope_changes(dates, values, penalty=slope_penalty), *jumps]
        for c in found:
            rows.append({**dict(zip(group_by, key, strict=True)), "date": c.date.isoformat(),
                         "type": c.type, "magnitude": round(c.magnitude, 4), "method": c.method})
    return pd.DataFrame(rows, columns=[*group_by, "date", "type", "magnitude", "method"])


def main() -> int:
    """uv run python -m common.breaks <slug> <source_id> [--by region,sex] [--out f.csv]
    [--level-alpha 0.001] [--slope-penalty 8] [--spike-z 3.5]"""
    import sys

    from common.checks import STUDIES_ROOT

    args = sys.argv[1:]
    if len(args) < 2:
        print(main.__doc__, file=sys.stderr)
        return 2
    slug, source_id = args[0], args[1]
    by = args[args.index("--by") + 1].split(",") if "--by" in args else ["region", "sex"]
    study_dir = STUDIES_ROOT / slug
    df = pd.read_parquet(study_dir / "data" / "clean" / f"{source_id}.parquet")
    df["date"] = pd.to_datetime(df["date"])
    def flag(name: str, default: float) -> float:
        return float(args[args.index(name) + 1]) if name in args else default

    table = detect_for_frame(
        df, group_by=by, level_alpha=flag("--level-alpha", LEVEL_ALPHA),
        slope_penalty=flag("--slope-penalty", SLOPE_PENALTY), spike_z=flag("--spike-z", 3.5),
    )
    out = Path(args[args.index("--out") + 1]) if "--out" in args else study_dir / "analysis" / "out" / f"break_candidates_{source_id}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False)
    print(f"{len(table)} candidate break(s) in {df.groupby(by, dropna=False).ngroups} series -> {out}")
    if len(table):
        print(table.groupby([*by, "type"]).size().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
