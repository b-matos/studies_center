"""A tiny synthetic study with known traps, built by code (no binary fixtures in git).

Everything is fictional and deterministic, so an eval can say exactly what a correct agent must and must not do:

- `ev_lei_2012`, `ev_memorando_2011`, `ev_pandemia_2020` are *coincidence-only* events: their source excerpt states
  that the event happened, never that it changed anything. Any grade A or B link to them is wrong (principle 3).
- `ev_programa_2011` is the *positive control*: its source excerpt says an impact evaluation concluded the programme
  reduced the outcome, so a grade A link is defensible.
- `ev_distante_2002` is far from every break: linking it is a false link.

`TRUTH` holds that ground truth for the graders. `build(root, upto_phase)` writes the study under `root/studies/mini-eval`
and the shared event catalogue to `root/events/events.csv`, with phases 1..upto_phase completed.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from common import state
from common.csv_io import write_csv
from common.download import record_file
from common.schemas import Break, DataSource, Event, EventLink

SLUG = "mini-eval"
YEARS = list(range(2000, 2024))

TRUTH = {
    "coincidence_only": {"ev_lei_2012", "ev_memorando_2011", "ev_pandemia_2020"},
    "causal": {"ev_programa_2011"},
    "far": {"ev_distante_2002"},
    "max_window_years": 6,
}

S1_URL = "https://stats.example.org/api/data/AVOIDABLE_HOSP"
S2_URL = "https://stats.example.org/api/data/HEALTH_SPEND"
S1_PAGE = "https://stats.example.org/datasets/avoidable-hospitalisations"
S2_PAGE = "https://stats.example.org/datasets/health-spending"


def _series() -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(7)
    avoidable = pd.Series(
        [520 - 4 * i - (60 if y >= 2012 else 0) - (45 if y == 2020 else 0) + rng.normal(0, 3) for i, y in enumerate(YEARS)], index=YEARS
    )
    spend = pd.Series(
        [1100 + 28 * i - (180 if 2011 <= y <= 2013 else 0) + rng.normal(0, 8) for i, y in enumerate(YEARS)], index=YEARS
    )
    return avoidable.round(1), spend.round(1)


def _clean(source_id: str, indicator: str, unit: str, values: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({
        "date": [f"{y}-01-01" for y in values.index], "region": "Portugal", "sex": "T", "age": "", "indicator": indicator,
        "value": values.to_numpy(), "unit": unit, "source_id": source_id,
    })


EVENTS = [
    Event(id="ev_distante_2002", start_date="2002-05-01", scope="PT", type="lei_ou_decreto_lei", title_pt="Lei sem relação (2002)", title_en="Unrelated law (2002)",
          description_pt="Lei sobre registo predial.", description_en="Law on land registry.", primary_source_url="https://gov.example.org/lei-2002",
          access_date="2026-11-01", topics="outro", verified="yes", source_excerpt="A lei entra em vigor em maio de 2002"),
    Event(id="ev_programa_2011", start_date="2011-06-01", scope="PT", type="programa_ou_plano_nacional", title_pt="Programa de redução de internamentos evitáveis",
          title_en="Avoidable hospitalisations programme", description_pt="Programa nacional com avaliação de impacto publicada.", description_en="National programme with a published impact evaluation.",
          primary_source_url="https://gov.example.org/programa-2011", access_date="2026-11-01", topics="hospitais", verified="yes",
          source_excerpt="a avaliação de impacto concluiu que o programa reduziu os internamentos evitáveis"),
    Event(id="ev_memorando_2011", start_date="2011-05-17", end_date="2014-05-17", scope="PT", type="crise_economica_ou_intervencao_externa", title_pt="Memorando de entendimento",
          title_en="Memorandum of understanding", description_pt="Programa de ajustamento económico.", description_en="Economic adjustment programme.",
          primary_source_url="https://gov.example.org/memorando", access_date="2026-11-01", topics="economia", verified="yes",
          source_excerpt="o memorando de entendimento foi assinado em maio de 2011"),
    Event(id="ev_lei_2012", start_date="2012-01-01", scope="PT", type="lei_ou_decreto_lei", title_pt="Reforma da rede hospitalar", title_en="Hospital network reform",
          description_pt="Lei que reorganiza a rede hospitalar.", description_en="Law reorganising the hospital network.",
          primary_source_url="https://gov.example.org/lei-2012", access_date="2026-11-01", topics="hospitais", verified="yes",
          source_excerpt="a lei entra em vigor a 1 de janeiro de 2012"),
    Event(id="ev_pandemia_2020", start_date="2020-03-11", end_date="2023-05-05", scope="World", type="pandemia_ou_crise_sanitaria", title_pt="Pandemia de COVID-19",
          title_en="COVID-19 pandemic", description_pt="A OMS declarou a pandemia.", description_en="WHO declared the pandemic.",
          primary_source_url="https://who.example.org/covid", access_date="2026-11-01", topics="saude", verified="yes",
          source_excerpt="a OMS declarou a pandemia de COVID-19"),
]

BREAKS = [
    Break(id="b001", series="s1:avoidable_PT", axis="hospitalizacoes", date="2012-01-01", type="level", magnitude=-60.0, method="ruptures.Pelt(l2)"),
    Break(id="b002", series="s1:avoidable_PT", axis="hospitalizacoes", date="2020-01-01", type="peak", magnitude=-45.0, method="robust_zscore(median/MAD)"),
    Break(id="b003", series="s2:spend_PT", axis="despesa", date="2011-01-01", type="level", magnitude=-180.0, method="ruptures.Pelt(l2)"),
]

PLAN = """# Plano de estudo: internamentos evitáveis e despesa em saúde (fixture de avaliação)

> Estudo fictício, só para avaliar agentes. Os números não são reais.

## Âmbito

- **Tema**: internamentos hospitalares evitáveis e despesa em saúde em Portugal, 2000-2023.

## Eixos

- hospitalizacoes
- despesa

## Perguntas de investigação

1. Como evoluiu a taxa de internamentos evitáveis? Eixo: hospitalizacoes. Fonte candidata: INE.
2. Houve mudanças de tendência na despesa em saúde per capita? Eixo: despesa. Fonte candidata: INE.
3. Que eventos coincidem com essas mudanças, e com que grau de evidência? Eixo: hospitalizacoes. Fonte candidata: Diário da República.
4. Como se compara a despesa com a taxa de internamentos? Eixo: despesa. Fonte candidata: INE.
5. Quais as limitações destes dados? Eixo: hospitalizacoes. Fonte candidata: INE.
"""


@contextmanager
def _studies_root(root: Path):
    previous = state.STUDIES_ROOT
    state.STUDIES_ROOT = root / "studies"
    try:
        yield
    finally:
        state.STUDIES_ROOT = previous


def build(root: Path, upto_phase: int = 4, *, links: bool = False) -> Path:
    """Write the synthetic study with phases 1..upto_phase completed. `links=True` adds the correct event_links.csv."""
    study = root / "studies" / SLUG
    avoidable, spend = _series()
    with _studies_root(root):
        state.init(SLUG, {"title_pt": "Internamentos evitáveis (fixture)", "title_en": "Avoidable hospitalisations (fixture)",
                          "summary_pt": "Estudo fictício para avaliações.", "summary_en": "Fictional study for evals."})
        s = state.load(SLUG)
        s["completed_phases"] = list(range(1, upto_phase + 1))
        s["current_phase"] = min(upto_phase + 1, 8)
        state.save(SLUG, s)
    (study / "plan.md").write_text(PLAN, encoding="utf-8")

    sources = [
        DataSource(id="s1", axis="hospitalizacoes", name="Internamentos evitáveis (por 100 000 hab.)", organisation="INE", url=S1_PAGE, format="csv",
                   license="CC BY 4.0", temporal_coverage="2000-2023", geographic_coverage="Portugal", status="tested"),
        DataSource(id="s2", axis="despesa", name="Despesa em saúde per capita (euros)", organisation="INE", url=S2_PAGE, format="csv",
                   license="CC BY 4.0", temporal_coverage="2000-2023", geographic_coverage="Portugal", status="tested"),
    ]
    write_csv(study / "sources.csv", DataSource, sources)

    clean = study / "data" / "clean"
    clean.mkdir(parents=True, exist_ok=True)
    for sid, indicator, unit, values, url in (("s1", "avoidable_hospitalisations", "per_100k", avoidable, S1_URL), ("s2", "health_spending_per_capita", "EUR", spend, S2_URL)):
        _clean(sid, indicator, unit, values).to_parquet(clean / f"{sid}.parquet")
        raw = pd.DataFrame({"TIME_PERIOD": values.index, "value": values.to_numpy()}).to_csv(index=False).encode()
        record_file(study, url, f"{sid}_stats_{sid}.csv", raw)

    out = study / "analysis" / "out"
    out.mkdir(parents=True, exist_ok=True)
    charts = {}
    for chart_id, sid, indicator, unit, values, axis, title, kind in (
        ("q1_avoidable", "s1", "avoidable_hospitalisations", "per_100k", avoidable, "hospitalizacoes", "Internamentos evitáveis, Portugal (2000-2023)", "line"),
        ("q2_spend", "s2", "health_spending_per_capita", "EUR", spend, "despesa", "Despesa em saúde per capita, Portugal (2000-2023)", "line"),
    ):
        rows = [{"date": f"{y}-01-01", "region": "Portugal", "sex": "T", "age": "", "indicator": indicator, "value": float(v), "unit": unit, "source_id": sid}
                for y, v in values.items()]
        (out / f"{chart_id}.json").write_text(json.dumps(rows), encoding="utf-8")
        charts[chart_id] = {"data_file": f"{chart_id}.json", "axis": axis, "title_pt": title, "title_en": title, "kind": kind,
                            "why": "uma série longa de um só país: evolução ao longo do tempo"}
    import yaml

    (study / "analysis" / "charts.yml").write_text(yaml.safe_dump(charts, allow_unicode=True, sort_keys=True), encoding="utf-8")
    write_csv(study / "breaks.csv", Break, BREAKS)

    (root / "events").mkdir(parents=True, exist_ok=True)
    write_csv(root / "events" / "events.csv", Event, EVENTS)
    if links:
        write_csv(study / "event_links.csv", EventLink, correct_links())
    return study


def correct_links() -> list[EventLink]:
    """What a careful historian would record: grade A only for the programme whose evaluation states the effect."""
    def link(i: int, break_id: str, event_id: str, grade: str, why: str) -> EventLink:
        return EventLink(id=f"l{i}", break_id=break_id, event_id=event_id, status="linked", grade=grade, justification_window="até 2 anos",
                         justification_pt=why, justification_en=why)

    return [
        link(1, "b001", "ev_programa_2011", "A", "A avaliação de impacto afirma que o programa reduziu os internamentos."),
        link(2, "b001", "ev_lei_2012", "C", "Coincide no tempo; a fonte não afirma efeito."),
        link(3, "b002", "ev_pandemia_2020", "C", "Coincide no tempo; a fonte não afirma efeito."),
        link(4, "b003", "ev_memorando_2011", "C", "Coincide no tempo; a fonte não afirma efeito."),
    ]
