"""Compact, greppable numbers for the writer, built from the chart JSON files.

The writer has no shell and cannot read parquet. The chart JSON files (`analysis/out/*.json`) are
pretty-printed, one field per line and up to ~1 MB each, so finding a value in them takes dozens of
multi-line greps whose results are huge. This module turns them into two small files:

- `analysis/summary.md`: per chart, its title, the clean file each series comes from and, per
  series, the first/last/min/max values (every point when the series is short);
- `analysis/series.csv`: one observation per line (`chart,date,region,sex,age,indicator,value,unit,
  clean_file,clean_sex,clean_age,clean_indicator`), so a single `Grep` for `q01_life_expectancy,2020` returns a handful of short lines.

Everything is deterministic and derived only from files that are already committed, so it can be
regenerated at any time:

    uv run python -m common.summarize <slug>

The `clean_file` is inferred by matching each series against `data/clean/*.parquet` (same date,
region, sex, age, indicator and value), which is what a `dado` claim's `calculation` needs. A series
that matches no file is derived (a rate or a ratio computed by the analysis script).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

KEYS = ["date", "region", "sex", "age", "indicator"]
SERIES_KEYS = ["region", "sex", "age", "indicator", "unit"]
VALUE_TOLERANCE = 5e-4  # chart JSON values are rounded to 4 decimals
FULL_LISTING_MAX = 8  # series with at most this many points are listed in full
HEADLINE_REGIONS = {"Portugal", "European Union (27)"}
TOTAL_SEX = {"T", "HM", ""}
MAX_SERIES_PER_CHART = 14  # the rest is in series.csv
MAX_CORRELATIONS_LISTED = 25
SUMMARY_NAME = "summary.md"
SERIES_NAME = "series.csv"


def _load_chart(path: Path) -> pd.DataFrame:
    df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    for col in [*KEYS, "unit"]:
        if col not in df:
            df[col] = ""
    df = df.dropna(subset=["value"]).copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df[["region", "sex", "age", "indicator", "unit"]] = df[["region", "sex", "age", "indicator", "unit"]].fillna("").astype(str)
    return df


def _load_clean(clean_dir: Path) -> dict[str, pd.DataFrame]:
    frames = {}
    for path in sorted(clean_dir.glob("*.parquet")):
        df = pd.read_parquet(path, columns=[*KEYS, "value"])
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df[["region", "sex", "age", "indicator"]] = df[["region", "sex", "age", "indicator"]].fillna("").astype(str)
        frames[path.name] = df.dropna(subset=["value"]).drop_duplicates(KEYS, keep="first")
    return frames


MATCH_COLUMNS = ["clean_file", "c_sex", "c_age", "c_indicator"]


def _candidates(chart: pd.DataFrame, clean: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Every (chart row, clean file row) pair with the same date, region and value.

    Analysis scripts often relabel sex/age/indicator, so the clean file's own labels are kept: they
    are what a claim's `calculation` has to filter on. Several clean rows can share a value, so the
    choice among candidates is made per series (`_assign_origin`), never per row."""
    base = chart[["date", "region", "value"]].reset_index()
    parts = []
    for name, frame in clean.items():
        renamed = frame.rename(columns={"sex": "c_sex", "age": "c_age", "indicator": "c_indicator", "value": "c_value"})
        m = base.merge(renamed, on=["date", "region"], how="inner")
        m = m[(m["value"] - m["c_value"]).abs() <= VALUE_TOLERANCE]
        parts.append(m.assign(clean_file=name)[["index", *MATCH_COLUMNS]])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["index", *MATCH_COLUMNS])


def _assign_origin(df: pd.DataFrame, cands: pd.DataFrame) -> pd.DataFrame:
    """Per series, the clean file and labels that explain the most rows (ties: identical labels, then file name)."""
    out = pd.DataFrame("", index=df.index, columns=MATCH_COLUMNS)
    if cands.empty:
        return out
    for _, group in df.groupby(SERIES_KEYS, sort=False):
        c = cands[cands["index"].isin(group.index)]
        if c.empty:
            continue
        counts = c.groupby(MATCH_COLUMNS)["index"].nunique().rename("rows").reset_index()
        own = group.iloc[0]
        counts["same"] = (counts["c_sex"] == own["sex"]) & (counts["c_age"] == own["age"]) & (counts["c_indicator"] == own["indicator"])
        best = counts.sort_values(["rows", "same", "clean_file"], ascending=[False, False, True]).iloc[0]
        hit = c[(c[MATCH_COLUMNS] == best[MATCH_COLUMNS]).all(axis=1)]["index"]
        out.loc[hit.to_numpy(), MATCH_COLUMNS] = [best[col] for col in MATCH_COLUMNS]
    return out


def _fmt(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _when(date: str, yearly: bool) -> str:
    return date[:4] if yearly else date


def _origin(group: pd.DataFrame) -> str:
    """Where a series comes from: the clean file and, when relabelled, that file's own labels."""
    matched = group[group["clean_file"] != ""]
    if matched.empty:
        return "file=derived"
    combo = matched.groupby(["clean_file", "c_sex", "c_age", "c_indicator"]).size().sort_values(ascending=False)
    (file, c_sex, c_age, c_ind), count = combo.index[0], int(combo.iloc[0])
    row = group.iloc[0]
    same = (c_sex, c_age, c_ind) == (row["sex"], row["age"], row["indicator"])
    text = f"file={file}" + ("" if same else f" clean_labels(sex='{c_sex}',age='{c_age}',indicator='{c_ind}')")
    return text + ("" if count == len(group) else f" cov={count}/{len(group)}")


def _series_line(label: str, group: pd.DataFrame, yearly: bool) -> str:
    g = group.sort_values("date")
    values, dates = g["value"].to_numpy(), g["date"].tolist()
    origin = _origin(g)
    if len(g) <= FULL_LISTING_MAX:
        points = ", ".join(f"{_when(d, yearly)}:{_fmt(v)}" for d, v in zip(dates, values, strict=True))
        body = f"n={len(g)} {points}"
    else:
        imin, imax = int(values.argmin()), int(values.argmax())
        body = (
            f"n={len(g)} {_when(dates[0], yearly)}:{_fmt(values[0])} → {_when(dates[-1], yearly)}:{_fmt(values[-1])}"
            f" (Δ{values[-1] - values[0]:+.4g}) | min {_fmt(values[imin])}@{_when(dates[imin], yearly)}"
            f" | max {_fmt(values[imax])}@{_when(dates[imax], yearly)}"
        )
    return f"- {label} | {origin} | {body}"


def _priority(key: tuple[str, ...]) -> tuple[int, int, int, tuple[str, ...]]:
    """Headline series first: Portugal/EU, all sexes, no age split."""
    region, sex, age = key[0], key[1], key[2]
    return (0 if region in HEADLINE_REGIONS else 1, 0 if sex in TOTAL_SEX else 1, 0 if age == "" else 1, key)


def iter_chart_frames(study_dir: Path):
    """Yield (chart_id, charts.yml entry, frame) for each registered chart; the frame has the chart's
    rows plus the origin columns (`clean_file`, `c_sex`, `c_age`, `c_indicator`; '' = derived)."""
    charts = yaml.safe_load((study_dir / "analysis" / "charts.yml").read_text(encoding="utf-8")) or {}
    clean = _load_clean(study_dir / "data" / "clean")
    for chart_id, entry in charts.items():
        path = study_dir / "analysis" / "out" / str(entry.get("data_file", ""))
        if not path.is_file():
            continue
        df = _load_chart(path)
        if df.empty:
            continue
        yield chart_id, entry, df.join(_assign_origin(df, _candidates(df, clean)))


def _read_table(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:  # nothing was testable (too few points)
        return pd.DataFrame()


def _trend_notes(study_dir: Path) -> dict[tuple, str]:
    """Trend text per (chart, series) from analysis/trends.csv, when `common.trends` has run."""
    path = study_dir / "analysis" / "trends.csv"
    if not path.exists():
        return {}
    notes = {}
    for r in _read_table(path).itertuples(index=False):
        if r.direction == "insufficient_data":
            continue
        key = (r.chart, r.region, r.sex, r.age, r.indicator, r.unit)
        notes[key] = (f"trend {float(r.slope_per_year):+.4g}/yr [{float(r.slope_ci_low):+.4g}, {float(r.slope_ci_high):+.4g}]"
                      f" {r.direction} (MK p_adj={float(r.p_adj):.3g}) [{r.id}]")
    return notes


def _correlation_section(study_dir: Path) -> list[str]:
    path = study_dir / "analysis" / "correlations.csv"
    if not path.exists():
        return []
    df = _read_table(path)
    if df.empty:
        return []
    top = df[df["significant"] == "yes"].copy()
    top["abs_rho"] = top["rho"].astype(float).abs()
    top = top.sort_values("abs_rho", ascending=False).head(MAX_CORRELATIONS_LISTED)
    lines = [
        "## Correlations (exploratory associations, never causes)",
        "",
        "Spearman on first differences (so a shared upward trend does not count), Portugal total series from",
        "different charts, Benjamini-Hochberg corrected over every pair tested. Mechanical links are possible",
        "(e.g. a share and its total). Full table and each `calculation`: `Grep` the id in `correlations.csv`.",
        f"Pairs tested: {len(df)}; significant after correction: {int((df['significant'] == 'yes').sum())}.",
        "",
    ]
    for r in top.itertuples(index=False):
        lines.append(f"- [{r.id}] rho={float(r.rho):+.2f} q={float(r.q_value):.3g} n_diff={r.n_diff} | "
                     f"{r.label_a} ({r.chart_a}) ~ {r.label_b} ({r.chart_b})")
    if top.empty:
        lines.append("- none significant after correction")
    return [*lines, ""]


def summarize_study(study_dir: Path) -> tuple[str, list[list[str]]]:
    """Return (summary markdown, series.csv rows) for a study's registered charts."""
    lines = [
        f"# Chart numbers: {study_dir.name}",
        "",
        "Generated by `common.summarize` from `analysis/out/*.json`; do not edit. Exact single values:",
        f"`Grep` the chart id and year in `analysis/{SERIES_NAME}` (one observation per line). A `dado`",
        "claim's `clean_file` is the series' `file=`; its `calculation` filters that file by",
        "`region`, `sex`, `age`, `indicator` and `date` (`YYYY-01-01` for annual series), using the",
        "`clean_labels(...)` when shown (the chart relabels them) or the series' own labels otherwise.",
        "`file=derived` means the analysis script computed the series (state the calculation in the claim).",
        "Trends (`[t…]`, Theil-Sen slope + Mann-Kendall) come from `common.trends`; `Grep` the id in",
        "`trends.csv` for a ready `calculation`.",
        "",
    ]
    rows: list[list[str]] = []
    notes = _trend_notes(study_dir)
    for chart_id, entry, df in iter_chart_frames(study_dir):
        yearly = df["date"].str.endswith("-01-01").all()
        lines += [
            f"## {chart_id}",
            "",
            f"{entry.get('title_pt', '')} | axis: {entry.get('axis', '')} | rows: {len(df)} | {df['date'].min()} to {df['date'].max()}",
            "",
        ]
        groups = sorted(df.groupby(SERIES_KEYS, sort=False), key=lambda kv: _priority(kv[0]))
        for key, group in groups[:MAX_SERIES_PER_CHART]:
            line = _series_line(" | ".join(part or "-" for part in key), group, yearly)
            if note := notes.get((chart_id, *key)):
                line += f" | {note}"
            lines.append(line)
        if len(groups) > MAX_SERIES_PER_CHART:
            lines.append(f"- … {len(groups) - MAX_SERIES_PER_CHART} more series (regions, sexes, ages): see {SERIES_NAME}")
        lines.append("")
        for r in df.sort_values([*SERIES_KEYS, "date"]).itertuples(index=False):
            rows.append([chart_id, r.date, r.region, r.sex, r.age, r.indicator, _fmt(r.value), r.unit,
                         r.clean_file, r.c_sex, r.c_age, r.c_indicator])
    lines += _correlation_section(study_dir)
    return "\n".join(lines) + "\n", rows


def write_summary(study_dir: Path) -> tuple[Path, Path]:
    summary, rows = summarize_study(study_dir)
    analysis = study_dir / "analysis"
    summary_path, series_path = analysis / SUMMARY_NAME, analysis / SERIES_NAME
    summary_path.write_text(summary, encoding="utf-8")
    with series_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["chart", "date", "region", "sex", "age", "indicator", "value", "unit",
                         "clean_file", "clean_sex", "clean_age", "clean_indicator"])
        writer.writerows(rows)
    return summary_path, series_path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: uv run python -m common.summarize <slug>", file=sys.stderr)
        return 2
    study_dir = Path(__file__).resolve().parent.parent / "studies" / args[0]
    if not (study_dir / "analysis" / "charts.yml").exists():
        print(f"no analysis/charts.yml for '{args[0]}'", file=sys.stderr)
        return 1
    summary_path, series_path = write_summary(study_dir)
    print(f"wrote {summary_path.relative_to(study_dir.parent.parent)} "
          f"({summary_path.stat().st_size // 1024} KB) and {series_path.relative_to(study_dir.parent.parent)} "
          f"({series_path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
