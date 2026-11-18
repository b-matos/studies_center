"""Which chart kinds fit a chart's data, decided by code.

`site/assets/charts.js` has a catalogue of chart kinds. Choosing among them is a judgement about the data's shape
(how many dates, how many series, whether the parts sum to a whole), so it is made by rules here and not by whoever
writes the prose: the analyst declares a `kind` and a one-line `why` per chart in `analysis/charts.yml`, the writer
may switch to another kind in `allowed_kinds`, and `common.checks` rejects the rest.

    chart kind      JS function     fits
    line            timeSeries      evolution: >= 6 points per series, <= 8 series
    small_multiples smallMultiples  evolution of many series (2-24): one panel each, same axes
    ranking         ranking         one value per category at the latest date, 3-40 categories
    grouped_bars    groupedBars     a few dates or regions compared across a few series; values >= 0
    stacked_bars    stackedBars     parts of a whole per category (`composition: true`)
    stacked_area    stackedArea     a whole split over time (`composition: true`)
    slope           slope           before and after for 2-12 series
    dumbbell        dumbbell        before and after for 3-30 categories (regions)
    scatter         scatter         two indicators against each other, >= 8 paired points
    heatmap         heatmap         region by year grid, >= 4 regions and >= 4 dates
    table           dataTable       always allowed

The rules apply to the whole exported chart JSON (the analyst exports one JSON per chart idea). `charts.yml`
entries may also set `composition: true` when the series are parts of one whole (shares that add up).

    uv run python -m common.chartkinds <slug>     # allowed kinds per chart
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

KINDS: dict[str, str] = {
    "line": "timeSeries",
    "small_multiples": "smallMultiples",
    "ranking": "ranking",
    "grouped_bars": "groupedBars",
    "stacked_bars": "stackedBars",
    "stacked_area": "stackedArea",
    "slope": "slope",
    "dumbbell": "dumbbell",
    "scatter": "scatter",
    "heatmap": "heatmap",
    "table": "dataTable",
}
JS_TO_KIND = {fn: kind for kind, fn in KINDS.items()}
HANDWRITTEN_PLOTTING = ("Plotly.newPlot(", "Plotly.react(", "Plot.plot(", "Plotly.plot(")

MIN_LINE_POINTS = 6
MAX_LINE_SERIES = 8
MAX_PANELS = 24
MAX_BAR_CATEGORIES = 8
MAX_BAR_SERIES = 6
MAX_STACKED_PARTS = 8
MIN_SCATTER_PAIRS = 8
MIN_WHY_CHARS = 10
SERIES_KEYS = ["region", "sex", "age", "indicator", "unit"]


@dataclass
class Shape:
    n_dates: int
    n_series: int
    n_regions: int
    n_indicators: int
    median_points: float
    series_at_latest: int
    min_value: float
    scatter_pairs: int


def shape_of(df: pd.DataFrame) -> Shape:
    for col in SERIES_KEYS:
        if col not in df:
            df = df.assign(**{col: ""})
    df = df.dropna(subset=["value"])
    groups = df.groupby(SERIES_KEYS, dropna=False)
    indicators = sorted(df["indicator"].astype(str).unique())
    pairs = 0
    if len(indicators) == 2:
        a, b = (df[df["indicator"] == i].set_index(["region", "date"])["value"] for i in indicators)
        pairs = len(a.index.intersection(b.index))
    latest = df["date"].max() if len(df) else None
    return Shape(
        n_dates=int(df["date"].nunique()),
        n_series=int(groups.ngroups),
        n_regions=int(df["region"].nunique()),
        n_indicators=len(indicators),
        median_points=float(groups.size().median()) if groups.ngroups else 0.0,
        series_at_latest=int(df[df["date"] == latest].groupby(SERIES_KEYS, dropna=False).ngroups) if latest else 0,
        min_value=float(df["value"].min()) if len(df) else 0.0,
        scatter_pairs=pairs,
    )


def allowed_kinds(shape: Shape, *, composition: bool = False) -> list[str]:
    """Kinds that fit the data, most natural first."""
    ok = []
    evolution = shape.median_points >= MIN_LINE_POINTS and shape.n_dates >= MIN_LINE_POINTS
    if evolution and shape.n_series <= MAX_LINE_SERIES:
        ok.append("line")
    if evolution and 2 <= shape.n_series <= MAX_PANELS:
        ok.append("small_multiples")
    if 3 <= shape.series_at_latest <= 40:
        ok.append("ranking")
    few_categories = 2 <= shape.n_dates <= MAX_BAR_CATEGORIES or 2 <= shape.n_regions <= MAX_BAR_CATEGORIES
    if few_categories and 1 <= shape.n_series <= MAX_BAR_SERIES and shape.min_value >= 0:
        ok.append("grouped_bars")
    if composition and shape.min_value >= 0:
        if few_categories and 2 <= shape.n_series <= MAX_STACKED_PARTS:
            ok.append("stacked_bars")
        if shape.n_dates >= MIN_LINE_POINTS and 2 <= shape.n_series <= MAX_STACKED_PARTS:
            ok.append("stacked_area")
    if shape.n_dates >= 2 and 2 <= shape.n_series <= 12:
        ok.append("slope")
    if shape.n_dates >= 2 and 3 <= shape.n_series <= 30:
        ok.append("dumbbell")
    if shape.n_indicators == 2 and shape.scatter_pairs >= MIN_SCATTER_PAIRS:
        ok.append("scatter")
    if shape.n_dates >= 4 and shape.n_regions >= 4:
        ok.append("heatmap")
    return [*ok, "table"]


def kind_problems(chart_id: str, entry: dict, df: pd.DataFrame) -> list[str]:
    """Problems with one `charts.yml` entry: missing/unknown kind, no reason, or a kind the data cannot support."""
    kind, why = entry.get("kind"), str(entry.get("why") or "").strip()
    if not kind:
        return [f"gráfico {chart_id}: falta `kind` em charts.yml (um de: {', '.join(KINDS)})"]
    if kind not in KINDS:
        return [f"gráfico {chart_id}: kind '{kind}' não existe (um de: {', '.join(KINDS)})"]
    problems = []
    if len(why) < MIN_WHY_CHARS:
        problems.append(f"gráfico {chart_id}: falta `why` (uma frase a justificar a escolha de '{kind}')")
    allowed = allowed_kinds(shape_of(df), composition=bool(entry.get("composition")))
    if kind not in allowed:
        hint = " (as partes somam um todo? declara `composition: true`)" if kind.startswith("stacked") else ""
        problems.append(f"gráfico {chart_id}: kind '{kind}' não serve a estes dados; permitidos: {', '.join(allowed)}{hint}")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: uv run python -m common.chartkinds <slug>", file=sys.stderr)
        return 2
    from common.summarize import iter_chart_frames

    study_dir = Path(__file__).resolve().parent.parent / "studies" / args[0]
    charts = yaml.safe_load((study_dir / "analysis" / "charts.yml").read_text(encoding="utf-8")) or {}
    for chart_id, entry, df in iter_chart_frames(study_dir):
        allowed = allowed_kinds(shape_of(df), composition=bool(charts[chart_id].get("composition")))
        print(f"{chart_id}: declared={entry.get('kind') or '-'} | allowed: {', '.join(allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
