#!/usr/bin/env python3
"""Generate the Quarto site sources from estudos/ and eventos/, then render both languages.

Run as: uv run python site/build.py

What it does, in order:
1. Reads estudos/*/estudo.yml and (re)writes index.pt.qmd / index.en.qmd — studies with
   estado == "teste" are excluded from the public index, per the platform's own rule.
2. Copies each study's relatorio.<lang>.qmd into site/estudos/<slug>/index.<lang>.qmd,
   along with the chart JSON files it references (from analise/out/) and an open-license
   CSV export of its clean data, so relative paths inside the copied .qmd keep working.
3. Exports the shared eventos.csv catalogue as site/eventos.json for the Eventos page.
4. Runs `quarto render --profile pt` and `--profile en`.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

SITE_DIR = Path(__file__).resolve().parent
ROOT = SITE_DIR.parent
ESTUDOS_DIR = ROOT / "estudos"
EVENTOS_CSV = ROOT / "eventos" / "eventos.csv"

NC_LICENSE_PATTERN = re.compile(r"\bNC\b|n[aã]o[\s-]comercial", re.IGNORECASE)


def load_studies() -> list[dict]:
    studies = []
    if not ESTUDOS_DIR.exists():
        return studies
    for study_dir in sorted(ESTUDOS_DIR.iterdir()):
        estudo_yml = study_dir / "estudo.yml"
        if not estudo_yml.exists():
            continue
        meta = yaml.safe_load(estudo_yml.read_text(encoding="utf-8")) or {}
        meta["slug"] = study_dir.name
        meta["_dir"] = study_dir
        studies.append(meta)
    return studies


def write_index(studies: list[dict], lang: str) -> None:
    visible = [s for s in studies if s.get("estado") != "teste"]
    title_key = f"titulo_{lang}"
    resumo_key = f"resumo_{lang}"
    lines = [
        "---",
        "title: " + ("Estudos" if lang == "pt" else "Studies"),
        "output-file: index.html",
        "---",
        "",
    ]
    if not visible:
        lines.append("_Ainda não há estudos publicados._" if lang == "pt" else "_No studies published yet._")
    for s in visible:
        slug = s["slug"]
        titulo = s.get(title_key, slug)
        resumo = s.get(resumo_key, "")
        data = s.get("data", "")
        estado = s.get("estado", "")
        lines.append(f"## [{titulo}](estudos/{slug}/index.{lang}.qmd)")
        lines.append("")
        if data:
            lines.append(f"*{data} · {estado}*")
            lines.append("")
        lines.append(resumo)
        lines.append("")
    (SITE_DIR / f"index.{lang}.qmd").write_text("\n".join(lines), encoding="utf-8")


def _ensure_output_file(qmd_text: str) -> str:
    if qmd_text.startswith("---"):
        end = qmd_text.find("\n---", 3)
        if end != -1 and "output-file" not in qmd_text[:end]:
            return qmd_text[:end] + "\noutput-file: index.html" + qmd_text[end:]
        return qmd_text
    return "---\noutput-file: index.html\n---\n\n" + qmd_text


def copy_study_pages(study: dict) -> None:
    slug = study["slug"]
    study_dir: Path = study["_dir"]
    out_dir = SITE_DIR / "estudos" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    for lang in ["pt", "en"]:
        src = study_dir / f"relatorio.{lang}.qmd"
        if not src.exists():
            continue
        text = _ensure_output_file(src.read_text(encoding="utf-8"))
        (out_dir / f"index.{lang}.qmd").write_text(text, encoding="utf-8")

    analise_out = study_dir / "analise" / "out"
    if analise_out.exists():
        for chart_file in analise_out.glob("*.json"):
            shutil.copy2(chart_file, out_dir / chart_file.name)

    export_open_clean_data(study, out_dir)


def export_open_clean_data(study: dict, out_dir: Path) -> None:
    study_dir: Path = study["_dir"]
    fontes_csv = study_dir / "fontes.csv"
    clean_dir = study_dir / "dados" / "clean"
    if not fontes_csv.exists() or not clean_dir.exists():
        return

    fontes = pd.read_csv(fontes_csv)
    open_ids = set(fontes.loc[~fontes["licenca"].fillna("").str.contains(NC_LICENSE_PATTERN), "id"])

    frames = []
    for parquet_file in clean_dir.glob("*.parquet"):
        df = pd.read_parquet(parquet_file)
        if "fonte_id" in df.columns:
            df = df[df["fonte_id"].isin(open_ids)]
        frames.append(df)
    if not frames:
        return
    combined = pd.concat(frames, ignore_index=True)
    if combined.empty:
        return
    combined.to_csv(out_dir / "dados_abertos.csv", index=False)


def export_eventos_json() -> None:
    import csv
    import json

    out = SITE_DIR / "eventos.json"
    if not EVENTOS_CSV.exists():
        out.write_text("[]", encoding="utf-8")
        return
    with EVENTOS_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def render(profile: str) -> None:
    result = subprocess.run(
        ["quarto", "render", "--profile", profile],
        cwd=SITE_DIR,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"quarto render --profile {profile} falhou (código {result.returncode})")


def main() -> None:
    studies = load_studies()
    write_index(studies, "pt")
    write_index(studies, "en")
    for study in studies:
        copy_study_pages(study)
    export_eventos_json()

    if shutil.which("quarto") is None:
        print("quarto não está instalado — as páginas .qmd foram geradas, mas não compiladas.", file=sys.stderr)
        print("instala com: brew install --cask quarto", file=sys.stderr)
        raise SystemExit(1)

    render("pt")
    render("en")


if __name__ == "__main__":
    main()
