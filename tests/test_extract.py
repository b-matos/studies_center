"""Tests for common.extract (deterministic raw -> clean) and common.probe helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from common import extract
from common.download import read_manifest, record_file
from common.normalize import CANONICAL_COLUMNS

RAW = "freq,sex,age,geo,TIME_PERIOD,obs\nA,T,Y_LT1,PT,2020,81.0\nA,T,Y_LT1,PT,2021,81.2\nA,F,Y_LT1,PT,2021,84.0\nA,T,Y1,PT,2021,80.0\n"


@pytest.fixture
def study(tmp_path: Path) -> Path:
    study_dir = tmp_path / "demo"
    record_file(study_dir, "https://example.org/x", "f1_x.csv", RAW.encode())
    spec = {
        "fetch": {"kind": "http", "url": "https://example.org/x", "filename": "f1_x.csv", "format": "csv"},
        "normalize": {
            "indicator": "life_expectancy", "unit": "years", "date": "TIME_PERIOD", "value": "obs",
            "region": "geo", "sex": "sex", "filters": {"age": ["Y_LT1"]}, "labels": {"geo": {"PT": "Portugal"}},
        },
    }
    (study_dir / "data" / "extract").mkdir(parents=True)
    (study_dir / "data" / "extract" / "f1.json").write_text(json.dumps(spec), encoding="utf-8")
    return study_dir


def test_extract_applies_filters_labels_and_year_dates(study: Path) -> None:
    df = extract.extract(study, "f1")
    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 3  # the Y1 row is filtered out
    assert set(df["region"]) == {"Portugal"}
    assert sorted(df["date"].unique()) == ["2020-01-01", "2021-01-01"]
    assert (study / "data" / "clean" / "f1.parquet").exists()


def test_extract_reuses_valid_raw_without_network(study: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(_fetch: dict) -> bytes:
        raise AssertionError("raw file with a matching manifest hash must not be re-downloaded")

    monkeypatch.setattr(extract, "_fetch_bytes", no_network)
    extract.extract(study, "f1")


def test_extract_refetches_when_raw_drifted_from_manifest(study: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (study / "data" / "raw" / "f1_x.csv").write_text("corrupted", encoding="utf-8")
    monkeypatch.setattr(extract, "_fetch_bytes", lambda _f: RAW.encode())
    df = extract.extract(study, "f1")
    assert len(df) == 3
    assert len(read_manifest(study)) == 1


def test_script_mode_validates_canonical_columns(study: Path) -> None:
    (study / "data" / "extract" / "f2.py").write_text(
        "import pandas as pd\ndef build(study_dir):\n    return pd.DataFrame({'date': ['2020-01-01']})\n",
        encoding="utf-8",
    )
    with pytest.raises(extract.ExtractError, match="missing columns"):
        extract.extract(study, "f2")


def test_missing_spec_and_empty_result_fail_loudly(study: Path) -> None:
    with pytest.raises(extract.ExtractError, match="no spec"):
        extract.extract(study, "f9")
    spec_path = study / "data" / "extract" / "f1.json"
    spec = json.loads(spec_path.read_text())
    spec["normalize"]["filters"] = {"age": ["NOPE"]}
    spec_path.write_text(json.dumps(spec))
    with pytest.raises(extract.ExtractError, match="no rows"):
        extract.extract(study, "f1")


def test_summary_is_compact() -> None:
    df = pd.DataFrame({
        "date": ["2020-01-01", "2021-01-01"], "region": ["PT", "PT"], "sex": ["T", "T"], "age": ["", ""],
        "indicator": ["i", "i"], "value": [1.0, 2.0], "unit": ["u", "u"], "source_id": ["f1", "f1"],
    })
    text = extract.summarize(df)
    assert "rows: 2" in text and "latest row: 2021-01-01 PT T = 2" in text
    assert len(text.splitlines()) <= 9
