"""Export clean long-format data (plus linked events) as JSON for the site's OJS charts.

The browser never runs Python: analista scripts call export_series_json() to write a
JSON file under estudos/<slug>/analise/out/, and register it in graficos.yml so build.py
knows which files to copy into the site and which .qmd each belongs to.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml


def export_series_json(df: pd.DataFrame, out_path: Path) -> None:
    """Write a long-format DataFrame (data, regiao, sexo, idade, indicador, valor, unidade)
    as a JSON array of records, ready for Observable Plot to consume directly."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records = df.to_dict(orient="records")
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=0), encoding="utf-8")


def register_chart(study_dir: Path, *, chart_id: str, data_file: str, eixo: str, titulo_pt: str, titulo_en: str) -> None:
    """Append (or update) one entry in analise/graficos.yml."""
    registry_path = study_dir / "analise" / "graficos.yml"
    registry = {}
    if registry_path.exists():
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    registry[chart_id] = {
        "data_file": data_file,
        "eixo": eixo,
        "titulo_pt": titulo_pt,
        "titulo_en": titulo_en,
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=True), encoding="utf-8")


def export_events_json(eventos_csv: Path, out_path: Path) -> None:
    """Export the shared events catalogue as JSON for the timeline overlays and the Eventos page."""
    import csv

    with eventos_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
