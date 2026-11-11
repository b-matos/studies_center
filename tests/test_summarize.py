"""common.summarize: compact chart numbers for the writer, with the clean file each series comes from."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from common import summarize


def _study(tmp_path: Path) -> Path:
    study = tmp_path / "demo"
    (study / "analysis" / "out").mkdir(parents=True)
    (study / "data" / "clean").mkdir(parents=True)
    years = [f"{y}-01-01" for y in range(2000, 2012)]
    clean = pd.DataFrame({
        "date": years, "region": "Portugal", "sex": "T", "age": "Y_LT1", "indicator": "life_expectancy",
        "value": [70 + i * 0.5 for i in range(12)], "unit": "YR", "source_id": "f02",
    })
    clean.to_parquet(study / "data" / "clean" / "f02.parquet")
    # the chart relabels age and indicator; one series is derived (values not in any clean file)
    rows = [
        {"date": d, "region": "Portugal", "sex": "T", "age": "0", "indicator": "le", "value": v, "unit": "YR"}
        for d, v in zip(years, clean["value"], strict=True)
    ] + [
        {"date": d, "region": "Portugal", "sex": "T", "age": "", "indicator": "ratio", "value": 0.123 + i, "unit": "PC"}
        for i, d in enumerate(years[:3])
    ]
    (study / "analysis" / "out" / "c1.json").write_text(json.dumps(rows), encoding="utf-8")
    (study / "analysis" / "charts.yml").write_text(
        yaml.safe_dump({"c1": {"data_file": "c1.json", "axis": "x", "title_pt": "Título", "title_en": "Title"}}),
        encoding="utf-8",
    )
    return study


def test_summary_reports_values_and_clean_origin(tmp_path: Path) -> None:
    summary, rows = summarize.summarize_study(_study(tmp_path))
    assert "## c1" in summary
    # relabelled series: points to the clean file with the clean file's own labels
    line = next(entry for entry in summary.splitlines() if "| le |" in entry)
    assert "file=f02.parquet" in line
    assert "clean_labels(sex='T',age='Y_LT1',indicator='life_expectancy')" in line
    assert "2000:70 → 2011:75.5" in line
    # short series are listed in full, and a series no clean file explains is derived
    derived = next(entry for entry in summary.splitlines() if "| ratio |" in entry)
    assert "file=derived" in derived
    assert "2000:0.123" in derived and "2002:2.123" in derived
    assert len(rows) == 15


def test_write_summary_creates_greppable_series_file(tmp_path: Path) -> None:
    study = _study(tmp_path)
    summary_path, series_path = summarize.write_summary(study)
    assert summary_path.exists()
    lines = series_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("chart,date,region")
    assert "c1,2005-01-01,Portugal,T,0,le,72.5,YR,f02.parquet,T,Y_LT1,life_expectancy" in lines


def test_series_cap_points_to_series_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(summarize, "MAX_SERIES_PER_CHART", 1)
    summary, _ = summarize.summarize_study(_study(tmp_path))
    assert "1 more series" in summary


def _two_series_study(tmp_path: Path, *, tag_source: bool) -> Path:
    """Two clean files hold the same single value under different indicators: only the source tag or the
    labels can tell them apart."""
    study = tmp_path / "amb"
    (study / "analysis" / "out").mkdir(parents=True)
    (study / "data" / "clean").mkdir(parents=True)
    for sid, indicator in (("a1", "deaths|Cancer"), ("b1", "deaths|Falls")):
        pd.DataFrame({"date": ["2020-01-01"], "region": "Portugal", "sex": "T", "age": "", "indicator": indicator,
                      "value": [5.0], "unit": "N", "source_id": sid}).to_parquet(study / "data" / "clean" / f"{sid}.parquet")
    row = {"date": "2020-01-01", "region": "Portugal", "sex": "T", "age": "", "indicator": "Other label", "value": 5.0, "unit": "N"}
    if tag_source:
        row["source_id"] = "b1"
    (study / "analysis" / "out" / "c.json").write_text(json.dumps([row]), encoding="utf-8")
    (study / "analysis" / "charts.yml").write_text(yaml.safe_dump({"c": {"data_file": "c.json"}}), encoding="utf-8")
    return study


def test_series_with_the_same_value_in_two_files_is_ambiguous_not_guessed(tmp_path: Path) -> None:
    summary, _ = summarize.summarize_study(_two_series_study(tmp_path, tag_source=False))
    assert "file=ambiguous(2 candidates" in summary
    assert "clean_labels(sex" not in summary


def test_source_id_in_the_chart_json_resolves_the_ambiguity(tmp_path: Path) -> None:
    summary, rows = summarize.summarize_study(_two_series_study(tmp_path, tag_source=True))
    assert "file=b1.parquet" in summary and "ambiguous" not in summary
    assert rows[0][8] == "b1.parquet"


def test_similar_labels_break_a_tie(tmp_path: Path) -> None:
    study = _two_series_study(tmp_path, tag_source=False)
    path = study / "analysis" / "out" / "c.json"
    row = json.loads(path.read_text(encoding="utf-8"))[0] | {"indicator": "Falls"}
    path.write_text(json.dumps([row]), encoding="utf-8")
    summary, _ = summarize.summarize_study(study)
    assert "file=b1.parquet" in summary
