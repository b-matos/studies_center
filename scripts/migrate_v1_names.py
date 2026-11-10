#!/usr/bin/env python3
"""One-off, idempotent migration of tracked data from Portuguese (v1) to English (v2) names.

Run after the directories/files were renamed (`git mv`):

    uv run python scripts/migrate_v1_names.py

Rewrites, for every study under studies/ and for events/events.csv: CSV headers and enum
values, parquet column names (values are asserted unchanged), chart JSON keys, charts.yml,
study.yml, the raw manifest and state.json (v1 -> v2). Running it twice changes nothing.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent

COLUMNS = {
    "data": "date", "regiao": "region", "sexo": "sex", "idade": "age", "indicador": "indicator",
    "valor": "value", "unidade": "unit", "fonte_id": "source_id", "eixo": "axis", "nome": "name",
    "organismo": "organisation", "formato": "format", "licenca": "license",
    "cobertura_temporal": "temporal_coverage", "cobertura_geografica": "geographic_coverage",
    "estado": "status", "motivo_exclusao": "exclusion_reason", "data_verificacao": "verification_date",
    "serie": "series", "tipo": "type", "metodo": "method", "ic_inf": "ci_low", "ic_sup": "ci_high",
    "nota": "note", "quebra_id": "break_id", "evento_id": "event_id", "grau": "grade",
    "janela_justificacao": "justification_window", "justificacao_pt": "justification_pt",
    "justificacao_en": "justification_en", "texto_pt": "text_pt", "texto_en": "text_en",
    "data_acesso": "access_date", "excerto": "excerpt", "natureza_fonte": "source_nature",
    "localizacao": "location", "ficheiro_clean": "clean_file", "calculo": "calculation",
    "estado_verificacao": "verification_status", "data_inicio": "start_date", "data_fim": "end_date",
    "ambito": "scope", "titulo_pt": "title_pt", "titulo_en": "title_en", "descricao_pt": "description_pt",
    "descricao_en": "description_en", "fonte_primaria_url": "primary_source_url",
    "fonte_secundaria_url": "secondary_source_url", "temas": "topics", "verificado": "verified",
    "ficheiro": "file", "data_download": "download_date", "resumo_pt": "summary_pt",
    "resumo_en": "summary_en", "fase_atual": "current_phase",
}

EVENT_TYPES = {
    "lei_ou_decreto_lei": "law_or_decree_law", "orcamento_do_estado": "state_budget",
    "mudanca_de_governo": "government_change", "eleicao": "election",
    "diretiva_ou_regulamento_europeu": "eu_directive_or_regulation",
    "programa_ou_plano_nacional": "national_programme_or_plan",
    "crise_economica_ou_intervencao_externa": "economic_crisis_or_external_intervention",
    "pandemia_ou_crise_sanitaria": "pandemic_or_health_crisis",
    "catastrofe_natural_ou_climatica": "natural_or_climate_disaster",
    "greve_ou_conflito_laboral": "strike_or_labour_dispute",
    "evento_internacional_relevante": "relevant_international_event",
}

# (file name, new column name) -> {old value: new value}
VALUES = {
    ("sources.csv", "status"): {"testada": "tested", "excluida": "excluded"},
    ("claims.csv", "type"): {"dado": "data", "facto": "fact", "evento": "event", "ligacao": "link"},
    ("claims.csv", "source_nature"): {"primaria": "primary", "secundaria": "secondary", "noticia": "news"},
    ("claims.csv", "verification_status"): {"pendente": "pending", "confirmada": "confirmed", "falhada": "failed"},
    ("breaks.csv", "type"): {"nivel": "level", "declive": "slope", "pico": "peak"},
    ("event_links.csv", "status"): {
        "ligado": "linked", "quebra_sem_evento": "break_without_event",
        "evento_sem_efeito": "event_without_effect",
    },
    ("events.csv", "scope"): {"UE": "EU", "Mundo": "World"},
    ("events.csv", "verified"): {"sim": "yes", "nao": "no"},
    ("events.csv", "type"): EVENT_TYPES,
}

QUERY_WORDS = {"regiao": "region", "sexo": "sex", "idade": "age", "indicador": "indicator",
               "valor": "value", "unidade": "unit"}


def migrate_calculation(expr: str) -> str:
    for old, new in QUERY_WORDS.items():
        expr = re.sub(rf"\b{old}\b", new, expr)
    return re.sub(r"\bdata\b(?=\s*==)", "date", expr)


def migrate_csv(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        old_fields = reader.fieldnames or []
        rows = list(reader)
    new_fields = [COLUMNS.get(c, c) for c in old_fields]
    out_rows = []
    for row in rows:
        new = {COLUMNS.get(k, k): v for k, v in row.items()}
        for col, value in list(new.items()):
            mapping = VALUES.get((path.name, col))
            if mapping and value in mapping:
                new[col] = mapping[value]
        if new.get("calculation"):
            new["calculation"] = migrate_calculation(new["calculation"])
        out_rows.append(new)
    if new_fields == old_fields and out_rows == rows:
        return False
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_fields)
        writer.writeheader()
        writer.writerows(out_rows)
    return True


def migrate_parquet(path: Path) -> bool:
    df = pd.read_parquet(path)
    renamed = df.rename(columns=COLUMNS)
    if list(renamed.columns) == list(df.columns):
        return False
    renamed.to_parquet(path, index=False)
    pd.testing.assert_frame_equal(pd.read_parquet(path), renamed)  # values must be untouched
    return True


def migrate_json_records(path: Path) -> bool:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not (isinstance(records, list) and records and isinstance(records[0], dict)):
        return False
    new = [{COLUMNS.get(k, k): v for k, v in r.items()} for r in records]
    if new == records:
        return False
    path.write_text(json.dumps(new, ensure_ascii=False, indent=0), encoding="utf-8")
    return True


def migrate_yaml_keys(path: Path, *, nested: bool, value_map: dict | None = None) -> bool:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def conv(d: dict) -> dict:
        return {COLUMNS.get(k, k): v for k, v in d.items()}

    new = {k: conv(v) for k, v in data.items()} if nested else conv(data)
    if value_map and new.get("status") in value_map:
        new["status"] = value_map[new["status"]]
    if new == data:
        return False
    path.write_text(yaml.safe_dump(new, allow_unicode=True, sort_keys=True), encoding="utf-8")
    return True


def migrate_state(path: Path) -> bool:
    if not path.exists():
        return False
    old = json.loads(path.read_text(encoding="utf-8"))
    if old.get("schema_version") == 2:
        return False
    new = {
        "schema_version": 2,
        "current_phase": old.get("fase_atual", 1),
        "completed_phases": old.get("fases_concluidas", []),
        "phases": {},
        "updated_at": "2026-11-10T00:00:00Z",
    }
    path.write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> None:
    changed: list[str] = []

    def note(path: Path, did: bool) -> None:
        if did:
            changed.append(str(path.relative_to(ROOT)))

    note(ROOT / "events" / "events.csv", migrate_csv(ROOT / "events" / "events.csv"))
    for study in sorted((ROOT / "studies").glob("*/")):
        for name in ("sources.csv", "claims.csv", "breaks.csv", "event_links.csv"):
            note(study / name, migrate_csv(study / name))
        note(study / "data" / "raw_manifest.csv", migrate_csv(study / "data" / "raw_manifest.csv"))
        for pq in (study / "data" / "clean").glob("*.parquet"):
            note(pq, migrate_parquet(pq))
        for js in (study / "analysis" / "out").glob("*.json"):
            note(js, migrate_json_records(js))
        charts = study / "analysis" / "charts.yml"
        if charts.exists():
            note(charts, migrate_yaml_keys(charts, nested=True))
        study_yml = study / "study.yml"
        if study_yml.exists():
            note(study_yml, migrate_yaml_keys(
                study_yml, nested=False,
                value_map={"teste": "test", "publicado": "published", "em_curso": "in_progress",
                           "pendente_decisao": "pending_decision"},
            ))
        note(study / "state.json", migrate_state(study / "state.json"))
    print("\n".join(f"migrated {p}" for p in changed) or "nothing to migrate")


if __name__ == "__main__":
    main()
