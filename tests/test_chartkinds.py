"""common.chartkinds: which chart kinds fit a data shape, and the checks that enforce it."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from common import chartkinds, checks
from common.charts import register_chart


def frame(n_dates: int = 10, regions: tuple[str, ...] = ("Portugal",), indicators: tuple[str, ...] = ("x",), value=lambda i, j: 10 + i + j):
    rows = [
        {"date": f"{2000 + i}-01-01", "region": r, "sex": "T", "age": "", "indicator": ind, "value": value(i, j), "unit": "%"}
        for i in range(n_dates) for j, r in enumerate(regions) for ind in indicators
    ]
    return pd.DataFrame(rows)


def allowed(df, **kw):
    return chartkinds.allowed_kinds(chartkinds.shape_of(df), **kw)


def test_a_few_long_series_are_a_line_chart() -> None:
    kinds = allowed(frame(12, regions=("PT", "EU")))
    assert kinds[0] == "line" and "small_multiples" in kinds and kinds[-1] == "table"


def test_too_many_series_must_become_small_multiples_not_one_line_chart() -> None:
    kinds = allowed(frame(12, regions=tuple(f"R{i}" for i in range(12))))
    assert "line" not in kinds and "small_multiples" in kinds


def test_short_series_are_not_a_line_chart() -> None:
    kinds = allowed(frame(4, regions=("PT", "EU")))
    assert "line" not in kinds and "small_multiples" not in kinds
    assert "grouped_bars" in kinds


def test_stacked_kinds_need_the_composition_declaration() -> None:
    df = frame(8, regions=("a", "b", "c"))
    assert not {"stacked_bars", "stacked_area"} & set(allowed(df))
    assert {"stacked_bars", "stacked_area"} <= set(allowed(df, composition=True))
    assert not {"stacked_bars", "stacked_area"} & set(allowed(frame(8, regions=("a", "b")).assign(value=-1.0), composition=True))


def test_scatter_needs_two_indicators_with_enough_paired_points() -> None:
    assert "scatter" in allowed(frame(10, regions=("a", "b"), indicators=("u", "v")))
    assert "scatter" not in allowed(frame(10, regions=("a", "b"), indicators=("u",)))
    assert "scatter" not in allowed(frame(3, regions=("a",), indicators=("u", "v")))


def test_heatmap_and_dumbbell_need_regions() -> None:
    many = allowed(frame(6, regions=tuple(f"R{i}" for i in range(6))))
    assert "heatmap" in many and "dumbbell" in many and "ranking" in many
    assert "heatmap" not in allowed(frame(6, regions=("a", "b")))


def test_kind_problems_checks_kind_why_and_fit() -> None:
    df = frame(12, regions=("PT", "EU"))
    ok = {"kind": "line", "why": "evolução longa de duas séries"}
    assert chartkinds.kind_problems("c", ok, df) == []
    assert "falta `kind`" in chartkinds.kind_problems("c", {}, df)[0]
    assert "não existe" in chartkinds.kind_problems("c", {"kind": "pie", "why": "porque sim, é redondo"}, df)[0]
    assert "falta `why`" in chartkinds.kind_problems("c", {"kind": "line", "why": ""}, df)[0]
    bad = chartkinds.kind_problems("c", {"kind": "scatter", "why": "relação entre duas variáveis"}, df)
    assert "não serve" in bad[0] and "line" in bad[0]
    stacked = chartkinds.kind_problems("c", {"kind": "stacked_area", "why": "composição ao longo do tempo"}, df)
    assert "composition: true" in stacked[0]


def test_register_chart_records_kind_why_and_composition(tmp_path: Path) -> None:
    register_chart(tmp_path, chart_id="a", data_file="a.json", axis="x", title_pt="t", title_en="t",
                   kind="stacked_area", why="partes de um todo", composition=True)
    register_chart(tmp_path, chart_id="b", data_file="b.json", axis="x", title_pt="t", title_en="t")
    reg = yaml.safe_load((tmp_path / "analysis" / "charts.yml").read_text(encoding="utf-8"))
    assert reg["a"]["kind"] == "stacked_area" and reg["a"]["why"] == "partes de um todo" and reg["a"]["composition"] is True
    assert "kind" not in reg["b"] and "composition" not in reg["b"]


@pytest.fixture
def study(tmp_path: Path) -> Path:
    root = tmp_path / "studies" / "demo"
    (root / "analysis" / "out").mkdir(parents=True)
    rows = frame(12, regions=("PT", "EU")).assign(source_id="s1").to_dict(orient="records")
    (root / "analysis" / "out" / "c1.json").write_text(json.dumps(rows), encoding="utf-8")
    (root / "analysis" / "charts.yml").write_text(yaml.safe_dump({"c1": {"data_file": "c1.json", "kind": "line", "why": "duas séries longas"}}), encoding="utf-8")
    return root


def test_reports_may_not_hand_write_plotting(study: Path) -> None:
    (study / "report.pt.qmd").write_text('```{ojs}\nPlotly.newPlot(div, [], {})\n```\n', encoding="utf-8")
    assert any("à mão" in p for p in checks.chart_use_problems(study))


def test_report_chart_calls_are_checked_against_the_data_they_read(study: Path) -> None:
    good = 'chart_data = FileAttachment("c1.json").json()\nchart = timeSeries(Plotly, chart_data, {lang})\n'
    (study / "report.pt.qmd").write_text(good, encoding="utf-8")
    assert checks.chart_use_problems(study) == []
    wrong = 'chart_data = FileAttachment("c1.json").json()\nchart = scatter(Plotly, chart_data, {lang})\n'
    (study / "report.pt.qmd").write_text(wrong, encoding="utf-8")
    problems = checks.chart_use_problems(study)
    assert len(problems) == 1 and "scatter()" in problems[0] and "c1" in problems[0]
    reshaped = 'chart_data = FileAttachment("c1.json").json()\nsub = chart_data.filter((d) => d.region === "PT")\nchart = scatter(Plotly, sub, {lang})\n'
    (study / "report.pt.qmd").write_text(reshaped, encoding="utf-8")
    assert checks.chart_use_problems(study) == []  # reshaped data cannot be judged from the text
