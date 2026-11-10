"""Shared helpers for the health-status-portugal analysis scripts."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from common.breaks import detect_for_frame  # noqa: E402
from common.charts import export_series_json, register_chart  # noqa: E402
from common.schemas import Break  # noqa: E402

STUDY = ROOT / "studies" / "health-status-portugal"
CLEAN = STUDY / "data" / "clean"
OUT = STUDY / "analysis" / "out"
BREAKS_CSV = STUDY / "breaks.csv"
EU = "European Union (27)"
PT = "Portugal"


def load(source_id: str) -> pd.DataFrame:
    df = pd.read_parquet(CLEAN / f"{source_id}.parquet")
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    return df


def export(df: pd.DataFrame, name: str, axis: str, title_pt: str, title_en: str,
           *, region="region", sex="sex", age="age", indicator="indicator", value="value", unit="unit") -> None:
    """Export to the browser schema (data, regiao, sexo, idade, indicador, valor, unidade)."""
    out = pd.DataFrame({
        "data": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
        "regiao": df[region] if region in df else "",
        "sexo": df[sex] if sex in df else "",
        "idade": df[age] if age in df else "",
        "indicador": df[indicator] if indicator in df else "",
        "valor": df[value].round(4),
        "unidade": df[unit] if unit in df else "",
    }).dropna(subset=["valor"])
    out[["regiao", "sexo", "idade", "indicador", "unidade"]] = out[["regiao", "sexo", "idade", "indicador", "unidade"]].astype(object).fillna("")
    export_series_json(out, OUT / f"{name}.json")
    register_chart(STUDY, chart_id=name, data_file=f"{name}.json", axis=axis, title_pt=title_pt, title_en=title_en)
    print(f"chart {name}: {len(out)} rows")


def _recompute(vs: np.ndarray, i: int, kind: str) -> float:
    if kind == "level":
        return float(vs[i:].mean() - vs[:i].mean())
    if kind == "slope":
        def sl(y):
            return float(np.polyfit(np.arange(len(y)), y, 1)[0]) if len(y) > 1 else 0.0
        return sl(vs[i:]) - sl(vs[: i + 1])
    d = np.diff(vs)
    return float(d[i - 1] - np.median(d))


def find_breaks(series: dict[str, pd.DataFrame], axis: str, source_id: str, *, level_pen=8.0,
                slope_pen=8.0, spike_z=4.0, per_type: int = 1, notes: dict[str, str] | None = None) -> int:
    """Run common.breaks detectors on z-scored series (so one penalty fits all units), save all
    candidates to out/break_candidates_<source_id>_<axis>.csv, keep the `per_type` largest
    candidates per series and type (relative to the series spread), and upsert into breaks.csv.
    Magnitudes are reported in the original unit of each series. `series` maps a series label to a
    frame with columns date, value."""
    frames, raw = [], {}
    for label, g in series.items():
        g = g.dropna(subset=["value"]).sort_values("date")
        if len(g) < 8:
            continue
        v = g["value"].to_numpy(float)
        sd = v.std() or 1.0
        frames.append(pd.DataFrame({"series": label, "date": g["date"].to_numpy(), "value": (v - v.mean()) / sd}))
        raw[label] = (g["date"].reset_index(drop=True), v, sd)
    if not frames:
        return 0
    cand = detect_for_frame(pd.concat(frames), group_by=["series"], level_penalty=level_pen,
                            slope_penalty=slope_pen, spike_z=spike_z)
    rows = []
    for _, c in cand.iterrows():
        dates, v, sd = raw[c["series"]]
        i = int(dates[dates == pd.Timestamp(c["date"])].index[0])
        mag = _recompute(v, i, c["type"]) if 0 < i < len(v) else float(c["magnitude"])
        rows.append({**c.to_dict(), "magnitude": round(mag, 4), "rel": abs(mag) / sd if c["type"] != "slope" else abs(mag) / sd})
    cand = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    cand.to_csv(OUT / f"break_candidates_{source_id}_{axis}.csv", index=False)
    if cand.empty:
        return 0
    keep = (cand.sort_values("rel", ascending=False).groupby(["series", "type"]).head(per_type)).copy()
    keep["note"] = keep["series"].map(notes or {}).fillna("")
    upsert_breaks(axis, source_id, keep)
    return len(keep)


def reset_breaks(axis: str) -> None:
    """Drop this axis' rows from breaks.csv so reruns give stable ids."""
    if not BREAKS_CSV.exists():
        return
    with BREAKS_CSV.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["axis"] != axis]
    with BREAKS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(Break.model_fields))
        w.writeheader()
        w.writerows(rows)


def upsert_breaks(axis: str, source_id: str, keep: pd.DataFrame) -> None:
    existing = []
    if BREAKS_CSV.exists():
        with BREAKS_CSV.open(newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f)
                        if not (r["axis"] == axis and r["series"].startswith(f"{source_id}:"))]
    cols = list(Break.model_fields)
    n = max([int(r["id"].rsplit("b", 1)[1]) for r in existing if r["axis"] == axis] or [0])
    new = []
    for _, r in keep.sort_values(["series", "date"]).iterrows():
        n += 1
        b = Break(id=f"{axis}-b{n:03d}", series=f"{source_id}:{r['series']}", axis=axis, date=r["date"],
                  type=r["type"], magnitude=float(r["magnitude"]), method=r["method"],
                  note=r.get("note") or None)
        new.append({k: ("" if v is None else v) for k, v in b.model_dump().items()})
    with BREAKS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(existing + new)
    print(f"breaks {source_id}/{axis}: +{len(new)}")
