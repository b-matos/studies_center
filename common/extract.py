"""Deterministic extraction: raw source -> data/clean/<source_id>.parquet, no LLM in the loop.

The extractor agent only has to describe *what* to fetch and how columns map onto the
canonical long format, in a small JSON spec; this module does the fetching, hashing,
normalizing, validating and summarizing. Re-running is cheap and reproducible: a raw file
that is already on disk and matches the manifest hash is reused instead of re-downloaded.

Spec: studies/<slug>/data/extract/<source_id>.json

    {
      "fetch": {"kind": "eurostat", "dataset": "DEMO_MLEXPEC", "key": {"geo": "PT+EU27_2020"},
                "url": "https://ec.europa.eu/eurostat/...", "filename": "f02_eurostat_demo_mlexpec.csv"},
      "normalize": {
        "indicator": "life_expectancy_at_birth", "unit": "years",
        "date": "TIME_PERIOD", "value": "value", "region": "geo", "sex": "sex",
        "filters": {"age": ["Y_LT1"]},
        "labels": {"geo": {"PT": "Portugal", "EU27_2020": "European Union (27)"}}
      }
    }

`fetch.kind` is "eurostat" (sdmx client), "oecd" (sdmx client) or "http" (csv/json/xlsx file;
`format` and pandas `read_options` optional). Sources that do not fit a flat table (e.g. INE's
nested JSON) use a script instead: studies/<slug>/data/extract/<source_id>.py defining
`build(study_dir: Path) -> pandas.DataFrame` that returns the canonical columns.

    uv run python -m common.extract <slug> <source_id>
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pandas as pd

from common.download import read_manifest, record_file
from common.normalize import CANONICAL_COLUMNS, to_long, write_clean

SUMMARY_MAX_VALUES = 12


class ExtractError(Exception):
    pass


def _extract_dir(study_dir: Path) -> Path:
    return study_dir / "data" / "extract"


def _raw_is_valid(study_dir: Path, filename: str) -> bool:
    path = study_dir / "data" / "raw" / filename
    entry = next((e for e in read_manifest(study_dir) if e.file == filename), None)
    return bool(entry) and path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == entry.sha256


def _fetch_bytes(fetch: dict) -> bytes:
    kind = fetch["kind"]
    if kind in {"eurostat", "oecd"}:
        if kind == "eurostat":
            from common.sources.eurostat import fetch_dataset
        else:
            from common.sources.oecd import fetch_dataset
        df = fetch_dataset(fetch["dataset"], key=fetch.get("key"), params=fetch.get("params"))
        return df.to_csv(index=False).encode("utf-8")
    if kind == "http":
        import httpx

        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            response = client.get(fetch["url"])
            response.raise_for_status()
        return response.content
    raise ExtractError(f"unknown fetch.kind: {kind!r}")


def load_raw(study_dir: Path, fetch: dict) -> pd.DataFrame:
    filename = fetch["filename"]
    if not _raw_is_valid(study_dir, filename):
        record_file(study_dir, fetch["url"], filename, _fetch_bytes(fetch))
    content = (study_dir / "data" / "raw" / filename).read_bytes()
    fmt = fetch.get("format") or Path(filename).suffix.lstrip(".").lower()
    options = fetch.get("read_options", {})
    if fmt == "csv":
        return pd.read_csv(io.BytesIO(content), **options)
    if fmt == "json":
        return pd.read_json(io.BytesIO(content), **options)
    if fmt in {"xlsx", "xls"}:
        return pd.read_excel(io.BytesIO(content), **options)
    raise ExtractError(f"unsupported raw format: {fmt!r}")


def _as_iso_dates(series: pd.Series) -> pd.Series:
    """Years like 2002 / '2002' become 2002-01-01; anything else goes through to_datetime."""
    text = series.astype(str).str.strip()
    is_year = text.str.fullmatch(r"\d{4}")
    return text.where(~is_year, text + "-01-01")


def normalize_frame(raw: pd.DataFrame, source_id: str, spec: dict) -> pd.DataFrame:
    for column, allowed in spec.get("filters", {}).items():
        raw = raw[raw[column].isin(allowed)]
    raw = raw.copy()
    for column, mapping in spec.get("labels", {}).items():
        raw[column] = raw[column].map(mapping).fillna(raw[column])
    raw[spec["date"]] = _as_iso_dates(raw[spec["date"]])
    out = to_long(
        raw,
        indicator=spec["indicator"],
        source_id=source_id,
        unit=spec["unit"],
        date_col=spec["date"],
        value_col=spec["value"],
        region_col=spec.get("region"),
        sex_col=spec.get("sex"),
        age_col=spec.get("age"),
    )
    return out.dropna(subset=["value"]).reset_index(drop=True)


def _build_from_script(study_dir: Path, source_id: str) -> pd.DataFrame:
    script = _extract_dir(study_dir) / f"{source_id}.py"
    module_spec = importlib.util.spec_from_file_location(f"extract_{source_id}", script)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    df = module.build(study_dir)
    missing = set(CANONICAL_COLUMNS) - set(df.columns)
    if missing:
        raise ExtractError(f"{script.name}: build() result is missing columns {sorted(missing)}")
    return df[CANONICAL_COLUMNS]


def summarize(df: pd.DataFrame) -> str:
    """A compact picture of the result, enough to cross-check against the published source."""
    lines = [f"rows: {len(df)} | date: {df['date'].min()} .. {df['date'].max()}"]
    for column in ("region", "sex", "age", "indicator", "unit"):
        values = sorted(v for v in df[column].unique() if v != "")
        shown = ", ".join(map(str, values[:SUMMARY_MAX_VALUES])) + (" ..." if len(values) > SUMMARY_MAX_VALUES else "")
        lines.append(f"{column} ({len(values)}): {shown or '-'}")
    lines.append(
        f"value: min {df['value'].min():g} | mean {df['value'].mean():.4g} | max {df['value'].max():g}"
        f" | nulls {int(df['value'].isna().sum())}"
    )
    last = df.sort_values("date").tail(1).iloc[0]
    lines.append(f"latest row: {last['date']} {last['region'] or '-'} {last['sex'] or '-'} = {last['value']:g}")
    return "\n".join(lines)


def extract(study_dir: Path, source_id: str) -> pd.DataFrame:
    extract_dir = _extract_dir(study_dir)
    if (extract_dir / f"{source_id}.py").exists():
        df = _build_from_script(study_dir, source_id)
    elif (extract_dir / f"{source_id}.json").exists():
        spec = json.loads((extract_dir / f"{source_id}.json").read_text(encoding="utf-8"))
        df = normalize_frame(load_raw(study_dir, spec["fetch"]), source_id, spec["normalize"])
    else:
        raise ExtractError(f"no spec: create data/extract/{source_id}.json (or {source_id}.py)")
    if df.empty:
        raise ExtractError(f"{source_id}: no rows left after normalization; check filters and column names")
    clean = study_dir / "data" / "clean"
    clean.mkdir(parents=True, exist_ok=True)
    write_clean(df, clean / f"{source_id}.parquet")
    return df


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: uv run python -m common.extract <slug> <source_id>", file=sys.stderr)
        return 2
    from common.checks import STUDIES_ROOT

    slug, source_id = sys.argv[1:]
    try:
        df = extract(STUDIES_ROOT / slug, source_id)
    except (ExtractError, KeyError) as exc:
        print(f"[FAILED] {source_id}: {exc!r}", file=sys.stderr)
        return 1
    print(f"[OK] data/clean/{source_id}.parquet")
    print(summarize(df))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
