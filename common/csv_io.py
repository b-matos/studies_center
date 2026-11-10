"""Typed CSV read/write helpers built on top of common.schemas models."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import TypeVar, get_args

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def _optional_fields(model: type[BaseModel]) -> set[str]:
    return {
        name
        for name, field in model.model_fields.items()
        if type(None) in get_args(field.annotation)
    }


def read_csv(path: Path, model: type[M]) -> list[M]:
    if not path.exists():
        return []
    optional = _optional_fields(model)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader]
    out: list[M] = []
    for raw in rows:
        # An empty cell means "absent" only for fields the schema allows to be None;
        # a required str field keeps "" as a valid (if flagged-by-checks) empty value.
        cleaned = {k: (None if v == "" and k in optional else v) for k, v in raw.items()}
        out.append(model.model_validate(cleaned))
    return out


def write_csv(path: Path, model: type[M], rows: list[M]) -> None:
    fields = list(model.model_fields.keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            data = row.model_dump(mode="json")
            writer.writerow({k: ("" if data[k] is None else data[k]) for k in fields})


def append_row(path: Path, model: type[M], row: M) -> None:
    rows = read_csv(path, model)
    rows.append(row)
    write_csv(path, model, rows)
