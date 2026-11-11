#!/usr/bin/env python3
"""Generate the Quarto site sources from studies/ and events/, then render both languages.

Run as: uv run python site/build.py

What it does, in order:
1. Reads studies/*/study.yml and (re)writes index.pt.qmd / index.en.qmd — studies with
   estado == "teste" are excluded from the public index, per the platform's own rule.
2. Copies each study's report.<lang>.qmd into site/studies/<slug>/index.<lang>.qmd,
   along with the chart JSON files it references (from analysis/out/) and an open-license
   CSV export of its clean date, so relative paths inside the copied .qmd keep working.
3. Exports the shared events.csv catalogue as site/events.json for the Eventos page.
4. Runs `quarto render --profile pt` and `--profile en`.

Public mode (`--public`, used by the GitHub Pages workflow) builds a read-only copy into
site/_site_public/: only studies with status `published` (plus any `--include-status`),
no Queue page and no queue script (they need the local server), no cost or progress data.
Quarto turns the root-absolute links into relative ones and lang-switch.js reads any hosting
prefix from the URL, so the same output works at a domain root or under /<repo>/.
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

SITE_DIR = Path(__file__).resolve().parent
ROOT = SITE_DIR.parent
STUDIES_DIR = ROOT / "studies"
EVENTS_CSV = ROOT / "events" / "events.csv"

NC_LICENSE_PATTERN = re.compile(r"\bNC\b|n[aã]o[\s-]comercial", re.IGNORECASE)


def load_studies() -> list[dict]:
    studies = []
    if not STUDIES_DIR.exists():
        return studies
    for study_dir in sorted(STUDIES_DIR.iterdir()):
        study_yml = study_dir / "study.yml"
        if not study_yml.exists():
            continue
        meta = yaml.safe_load(study_yml.read_text(encoding="utf-8")) or {}
        meta["slug"] = study_dir.name
        meta["_dir"] = study_dir
        studies.append(meta)
    return studies


INDEX_COPY = {
    "pt": {
        "pagetitle": "Estudos sobre Portugal",
        "eyebrow": "Dados abertos · fontes verificadas",
        "headline": "Estudos sobre Portugal, com dados e fontes à vista",
        "lede": (
            "Cada estudo cruza séries oficiais com os eventos políticos e sociais que "
            "coincidem com as mudanças de tendência — e diz, em cada caso, quão forte é "
            "a evidência."
        ),
        "empty": "Ainda não há estudos publicados.",
        "read": "Ler estudo",
    },
    "en": {
        "pagetitle": "Studies on Portugal",
        "eyebrow": "Open data · verified sources",
        "headline": "Studies on Portugal, with the data and sources in plain sight",
        "lede": (
            "Each study sets official series against the political and social events that "
            "coincide with trend changes — and states, case by case, how strong the "
            "evidence is."
        ),
        "empty": "No studies published yet.",
        "read": "Read the study",
    },
}


def visible_studies(studies: list[dict], statuses: set[str] | None = None) -> list[dict]:
    """Studies shown on the index. Local build: everything except `test`. Public build:
    only the given statuses (default `published`)."""
    if statuses is None:
        return [s for s in studies if s.get("status") != "test"]
    return [s for s in studies if s.get("status") in statuses]


def write_index(studies: list[dict], lang: str, statuses: set[str] | None = None) -> None:
    copy = INDEX_COPY[lang]
    visible = visible_studies(studies, statuses)
    lines = [
        "---",
        f'pagetitle: "{copy["pagetitle"]}"',
        "output-file: index.html",
        "toc: false",
        "---",
        "",
        '<section class="hero">',
        f'<p class="hero-eyebrow">{html.escape(copy["eyebrow"])}</p>',
        f'<h1 class="hero-title">{html.escape(copy["headline"])}</h1>',
        f'<p class="hero-lede">{html.escape(copy["lede"])}</p>',
        "</section>",
        "",
    ]
    if not visible:
        lines.append(f'<p class="empty-state">{html.escape(copy["empty"])}</p>')
    else:
        lines.append('<div class="study-grid">')
        for s in visible:
            slug = s["slug"]
            titulo = html.escape(str(s.get(f"titulo_{lang}", slug)))
            resumo = html.escape(str(s.get(f"resumo_{lang}", "")))
            date = html.escape(str(s.get("date", "")))
            status = html.escape(str(s.get("status", "")))
            lines.append(
                f'<a class="study-card" href="studies/{slug}/index.html">'
                f'<span class="study-card-meta"><span class="badge-estado badge-{status}">{status}</span>'
                f"<span>{date}</span></span>"
                f'<span class="study-card-title">{titulo}</span>'
                f'<span class="study-card-summary">{resumo}</span>'
                f'<span class="study-card-cta">{html.escape(copy["read"])} →</span></a>'
            )
        lines.append("</div>")
    (SITE_DIR / f"index.{lang}.qmd").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ensure_output_file(qmd_text: str) -> str:
    if qmd_text.startswith("---"):
        end = qmd_text.find("\n---", 3)
        if end != -1 and "output-file" not in qmd_text[:end]:
            return qmd_text[:end] + "\noutput-file: index.html" + qmd_text[end:]
        return qmd_text
    return "---\noutput-file: index.html\n---\n\n" + qmd_text


STUDY_HEADER = {
    "pt": {"download": "Descarregar dados (CSV)", "sources": "Fontes e licenças (CSV)", "date": "Publicado", "tests": "estudo de teste"},
    "en": {"download": "Download data (CSV)", "sources": "Sources and licences (CSV)", "date": "Published", "tests": "test study"},
}


def _inject_study_header(qmd_text: str, study: dict, lang: str, has_data: bool) -> str:
    """Insert a meta bar (status badge, date, data download) right after the front matter."""
    copy = STUDY_HEADER[lang]
    status = html.escape(str(study.get("status", "")))
    parts = [
        f'<span class="badge-estado badge-{status}">{status}</span>',
        f'<span>{copy["date"]} {html.escape(str(study.get("date", "")))}</span>',
    ]
    if has_data:
        parts.append(f'<a class="btn-download" href="open_data.csv" download>{copy["download"]}</a>')
        parts.append(f'<a class="btn-download" href="open_data_sources.csv" download>{copy["sources"]}</a>')
    bar = '\n<div class="study-meta">' + "".join(parts) + "</div>\n"
    end = qmd_text.find("\n---", 3)
    close = end + len("\n---")
    return qmd_text[:close] + "\n" + bar + qmd_text[close:]


def export_linked_events(study: dict, out_dir: Path) -> None:
    """Write linked_events.json: events linked (estado == ligado) to this study's breaks,
    each with its best evidence grade, for the chart overlay."""
    import csv
    import json

    study_dir: Path = study["_dir"]
    links_csv = study_dir / "event_links.csv"
    out = out_dir / "linked_events.json"
    if not links_csv.exists() or not EVENTS_CSV.exists():
        out.write_text("[]", encoding="utf-8")
        return
    with EVENTS_CSV.open(newline="", encoding="utf-8") as f:
        events = {row["id"]: row for row in csv.DictReader(f)}
    with links_csv.open(newline="", encoding="utf-8") as f:
        links = [row for row in csv.DictReader(f) if row["status"] == "linked" and row["event_id"]]

    best: dict[str, dict] = {}
    for lig in links:
        ev = events.get(lig["event_id"])
        if ev is None:
            continue
        entry = best.setdefault(lig["event_id"], {**ev, "grade": lig["grade"], "n_quebras": 0})
        entry["n_quebras"] += 1
        entry["grade"] = min(entry["grade"], lig["grade"])  # "A" < "B" < "C": keep the strongest
    keep = ["id", "start_date", "end_date", "scope", "type", "title_pt", "title_en",
            "primary_source_url", "verified", "grade", "n_quebras"]
    out.write_text(
        json.dumps([{k: (e[k] or None) for k in keep} for e in best.values()], ensure_ascii=False),
        encoding="utf-8",
    )


def copy_study_pages(study: dict) -> None:
    slug = study["slug"]
    study_dir: Path = study["_dir"]
    out_dir = SITE_DIR / "studies" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    for lang in ["pt", "en"]:
        src = study_dir / f"report.{lang}.qmd"
        if not src.exists():
            continue
        text = _ensure_output_file(src.read_text(encoding="utf-8"))
        has_data = (study["_dir"] / "data" / "clean").exists()
        text = _inject_study_header(text, study, lang, has_data)
        (out_dir / f"index.{lang}.qmd").write_text(text, encoding="utf-8")

    analysis_out = study_dir / "analysis" / "out"
    if analysis_out.exists():
        for chart_file in analysis_out.glob("*.json"):
            shutil.copy2(chart_file, out_dir / chart_file.name)

    export_open_clean_data(study, out_dir)
    export_linked_events(study, out_dir)


def export_open_clean_data(study: dict, out_dir: Path) -> None:
    study_dir: Path = study["_dir"]
    sources_csv = study_dir / "sources.csv"
    clean_dir = study_dir / "data" / "clean"
    if not sources_csv.exists() or not clean_dir.exists():
        return

    sources = pd.read_csv(sources_csv)
    open_ids = set(sources.loc[~sources["license"].fillna("").str.contains(NC_LICENSE_PATTERN), "id"])

    frames = []
    for parquet_file in clean_dir.glob("*.parquet"):
        df = pd.read_parquet(parquet_file)
        if "source_id" in df.columns:
            df = df[df["source_id"].isin(open_ids)]
        frames.append(df)
    if not frames:
        return
    combined = pd.concat(frames, ignore_index=True)
    if combined.empty:
        return
    combined.to_csv(out_dir / "open_data.csv", index=False)
    used = set(combined["source_id"]) if "source_id" in combined.columns else open_ids
    cols = [c for c in ("id", "name", "organisation", "url", "license") if c in sources.columns]
    sources.loc[sources["id"].isin(used), cols].to_csv(out_dir / "open_data_sources.csv", index=False)  # attribution


def export_events_json() -> None:
    import csv
    import json

    out = SITE_DIR / "events.json"
    if not EVENTS_CSV.exists():
        out.write_text("[]", encoding="utf-8")
        return
    with EVENTS_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def copy_shared_assets(site_name: str = "_site", public: bool = False) -> None:
    """Copy site/assets/ to <site_name>/assets/, shared across languages.

    Pages reference shared scripts (e.g. lang-switch.js) via a root-absolute path like
    "/assets/lang-switch.js" so the same reference works whether the browser is on a /pt/
    or /en/ page. Quarto itself only ever writes into each profile's own output-dir
    (_site/pt or _site/en), so this top-level copy survives repeated `quarto render` runs.
    """
    src = SITE_DIR / "assets"
    dest = SITE_DIR / site_name / "assets"
    if dest.exists():
        shutil.rmtree(dest)
    ignored = ["*.scss", "queue.js"] if public else ["*.scss"]
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*ignored))


def write_root_redirect(site_name: str = "_site") -> None:
    """Write <site_name>/index.html so visiting the bare root lands on pt/.

    The target is relative, so it works both at the server's "/" and under a Pages subpath."""
    out = SITE_DIR / site_name / "index.html"
    out.write_text(
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta http-equiv="refresh" content="0; url=pt/"></head>'
        '<body><a href="pt/">Estudos sobre Portugal</a></body></html>',
        encoding="utf-8",
    )


def write_public_profiles() -> None:
    """Generate _quarto-<lang>-public.yml from the local profiles (gitignored, rebuilt every run).

    Drops the Queue page from the render list and the navbar and redirects the output to
    _site_public/.
    """
    for lang in ("pt", "en"):
        cfg = yaml.safe_load((SITE_DIR / f"_quarto-{lang}.yml").read_text(encoding="utf-8"))
        cfg["project"]["output-dir"] = f"_site_public/{lang}"
        cfg["project"]["render"] = [r for r in cfg["project"]["render"] if not r.startswith("queue.")]
        navbar = cfg["website"]["navbar"]
        navbar["left"] = [i for i in navbar["left"] if not str(i.get("href", "")).startswith("queue.")]
        out = SITE_DIR / f"_quarto-{lang}-public.yml"
        out.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the bilingual Quarto site.")
    parser.add_argument("--public", action="store_true",
                        help="read-only build for GitHub Pages into site/_site_public/")
    parser.add_argument("--include-status", action="append", default=[], metavar="STATUS",
                        help="public build: also show studies with this status (repeatable)")
    args = parser.parse_args(argv)
    statuses = {"published", *args.include_status} if args.public else None
    site_name = "_site_public" if args.public else "_site"

    studies = load_studies()
    if args.public:
        studies = visible_studies(studies, statuses)
    shutil.rmtree(SITE_DIR / "studies", ignore_errors=True)  # generated; avoids stale study pages
    write_index(studies, "pt", statuses)
    write_index(studies, "en", statuses)
    for study in studies:
        copy_study_pages(study)
    export_events_json()
    if args.public:
        write_public_profiles()

    if shutil.which("quarto") is None:
        print("quarto não está instalado — as páginas .qmd foram geradas, mas não compiladas.", file=sys.stderr)
        print("instala com: brew install --cask quarto", file=sys.stderr)
        raise SystemExit(1)

    suffix = "-public" if args.public else ""
    render(f"pt{suffix}")
    render(f"en{suffix}")
    copy_shared_assets(site_name, public=args.public)
    write_root_redirect(site_name)


if __name__ == "__main__":
    main()
