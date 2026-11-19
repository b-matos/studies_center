"""Graders for the planner, data-researcher, extractor and analyst: each accepts a reference output and rejects each kind of bad one."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pandas as pd
import pytest

from common.csv_io import write_csv
from common.download import record_file
from common.schemas import Break, DataSource
from evals import fixtures, graders, run, sandbox

PORT = 4321


def make(case: dict, tmp_path: Path):
    root, params = sandbox.make_sandbox(case, port=PORT, parent=tmp_path)
    return root, params, sandbox.snapshot(root)


def grade(names: list[str], root: Path, before: dict, params: dict, agent: str, output: str = "Feito.") -> dict[str, bool]:
    ctx = graders.Ctx(sandbox=root, agent=agent, before=before, after=sandbox.snapshot(root), output=output, params=params)
    return {r.name: r.passed for r in graders.grade(names, ctx)}


def load_case(agent: str) -> dict:
    return sandbox.load_cases(run.CASES_DIR / f"{agent}.yaml")[0]


# ---- planner -----------------------------------------------------------------------------------------------------

GOOD_PLAN = """# Plano: internamentos evitáveis e despesa

## Âmbito

- Portugal, 2000-2023, por região NUTS II quando os dados o permitirem.

## Perguntas de investigação

1. Como evoluiu a taxa de internamentos evitáveis? Eixo: hospitalizacoes. Fonte candidata: INE.
2. Há diferenças regionais nos internamentos evitáveis? Eixo: hospitalizacoes. Fonte candidata: INE.
3. Como evoluiu a despesa em saúde per capita? Eixo: despesa. Fonte candidata: Eurostat.
4. Houve mudanças de tendência na despesa? Eixo: despesa. Fonte candidata: INE.
5. Que eventos coincidem com as quebras? Eixo: hospitalizacoes. Fonte candidata: Diário da República.

## Decisões em aberto e exclusões

- Fora do âmbito: o setor privado.

## Eixos

- `hospitalizacoes` — INE
- `despesa` — INE
"""


@pytest.fixture
def planner_box(tmp_path: Path):
    return make(load_case("planner"), tmp_path)


def run_planner(box, plan: str) -> dict[str, bool]:
    root, params, before = box
    (root / "studies" / fixtures.SLUG / "plan.md").write_text(plan, encoding="utf-8")
    return grade(["planner_plan_valid", "planner_axes_section", "planner_scope_and_decisions", "planner_questions_answerable", "writes_only_own_files"], root, before, params, "planner")


def test_a_good_plan_passes_every_planner_grader(planner_box) -> None:
    assert all(run_planner(planner_box, GOOD_PLAN).values())


@pytest.mark.parametrize(("edit", "failing"), [
    (lambda p: p.split("## Eixos")[0], "axes_section"),
    (lambda p: p.replace("- `despesa` — INE", ""), "axes_section"),
    (lambda p: p.replace("Eixo: despesa", "Eixo: gastos", 1), "axes_section"),
    (lambda p: p.replace("`hospitalizacoes`", "`Hospitalizacoes_Evitaveis`"), "axes_section"),
    (lambda p: "\n".join(line for line in p.splitlines() if not line.startswith(("3.", "4.", "5."))), "phase1_check_passes"),
    (lambda p: p.replace(" Fonte candidata: INE.", "", 1), "phase1_check_passes"),
    (lambda p: p.replace("## Âmbito\n\n- Portugal, 2000-2023, por região NUTS II quando os dados o permitirem.", "## Âmbito\n\n- Tudo."), "scope_and_decisions"),
    (lambda p: p.replace("Como evoluiu a despesa em saúde per capita?", "O Estado deveria gastar mais em saúde?"), "questions_answerable_with_data"),
])
def test_each_kind_of_bad_plan_is_caught(planner_box, edit, failing: str) -> None:
    results = run_planner(planner_box, edit(GOOD_PLAN))
    assert not results[failing], results


def test_a_question_that_wraps_over_several_lines_is_still_a_question(planner_box) -> None:
    wrapped = GOOD_PLAN.replace("1. Como evoluiu a taxa de internamentos evitáveis? Eixo: hospitalizacoes.", "1. Como evoluiu, desde o início das séries,\n   a taxa de internamentos evitáveis?\n   Eixo: hospitalizacoes.")
    assert run_planner(planner_box, wrapped)["questions_answerable_with_data"]


def test_a_wrapped_line_starting_with_a_year_is_not_a_new_question(planner_box) -> None:
    plan = GOOD_PLAN.replace("## Decisões em aberto e exclusões\n", "## Decisões em aberto e exclusões\n\n- Quebras de série (revisões do INE em\n  2017) a tratar.\n")
    assert run_planner(planner_box, plan)["questions_answerable_with_data"]


def test_summary_length_is_checked() -> None:
    ctx = graders.Ctx(sandbox=Path("."), agent="planner", output=" ".join(["palavra"] * 151))
    assert not graders.grade(["summary_short"], ctx)[0].passed
    assert graders.grade(["summary_short"], graders.Ctx(sandbox=Path("."), agent="planner", output="Curto."))[0].passed


# ---- data-researcher ---------------------------------------------------------------------------------------------

def row(sid: str, path: str, status: str, **kw) -> DataSource:
    base = {"id": sid, "axis": "hospitalizacoes", "name": f"fonte {sid}", "organisation": "Instituto de Estatística Fictício", "url": f"http://127.0.0.1:{PORT}{path}",
            "format": "csv", "license": "CC BY 4.0", "temporal_coverage": "2000-2023", "geographic_coverage": "Portugal", "status": status}
    return DataSource(**{**base, **kw})


GOOD_ROWS = [row("f01", "/ok.csv", "tested"), row("f02", "/missing.csv", "excluded", exclusion_reason="404: o ficheiro não existe", license="", temporal_coverage="", format="csv"),
             row("f03", "/nc.csv", "excluded", exclusion_reason="licença incompatível (CC BY-NC 4.0)", license="CC BY-NC 4.0")]


@pytest.fixture
def researcher_box(tmp_path: Path):
    return make(load_case("data-researcher"), tmp_path)


def run_researcher(box, rows: list[DataSource] | None, output: str = "f04 inacessível (transitório): repetir a unidade mais tarde.") -> dict[str, bool]:
    root, params, before = box
    if rows is not None:
        write_csv(root / "studies" / fixtures.SLUG / "sources.d" / "hospitalizacoes.csv", DataSource, rows)
    return grade(["researcher_registers_each_candidate_correctly", "writes_only_own_files"], root, before, params, "data-researcher", output)


def test_a_careful_researcher_passes(researcher_box) -> None:
    assert all(run_researcher(researcher_box, GOOD_ROWS).values())


@pytest.mark.parametrize(("rows", "failing"), [
    (None, "sources_file_parses"),
    ([row("f01", "/ok.csv", "tested", license="CC BY-NC 4.0")] + GOOD_ROWS[1:], "good_source_tested_with_real_licence"),
    ([row("f01", "/ok.csv", "tested", license="CC BY 4.0", temporal_coverage="1990-2000")] + GOOD_ROWS[1:], "good_source_tested_with_real_licence"),
    ([GOOD_ROWS[0], row("f02", "/missing.csv", "excluded", exclusion_reason="timeout ao testar")] + GOOD_ROWS[2:], "dead_source_excluded_with_reason"),
    (GOOD_ROWS[:1] + GOOD_ROWS[2:], "dead_source_excluded_with_reason"),
    (GOOD_ROWS[:2] + [row("f03", "/nc.csv", "tested", license="CC BY 4.0")], "non_commercial_source_not_passed_off"),
    (GOOD_ROWS + [row("f04", "/flaky.csv", "excluded", exclusion_reason="HTTP 503, sem resposta")], "transient_failure_not_recorded"),
    (GOOD_ROWS + [row("f09", "/inventado.csv", "tested")], "no_invented_urls"),
])
def test_each_kind_of_bad_registration_is_caught(researcher_box, rows, failing: str) -> None:
    assert not run_researcher(researcher_box, rows)[failing]


def test_the_orchestrator_must_be_told_about_the_transient_source(researcher_box) -> None:
    assert not run_researcher(researcher_box, GOOD_ROWS, output="Fontes registadas.")["transient_mentioned_in_summary"]
    for wording in ("O probe devolveu TRANSIENT para f04.", "f04 devolveu 503.", "Repetir a unidade mais tarde."):
        assert run_researcher(researcher_box, GOOD_ROWS, output=wording)["transient_mentioned_in_summary"], wording


def test_a_data_researcher_writing_elsewhere_is_caught(researcher_box) -> None:
    root, *_ = researcher_box
    (root / "studies" / fixtures.SLUG / "sources.csv").write_text("tampered", encoding="utf-8")  # the orchestrator's merged file
    assert not run_researcher(researcher_box, GOOD_ROWS)["writes_only_own_files"]


# ---- extractor ---------------------------------------------------------------------------------------------------

@pytest.fixture
def extractor_box(tmp_path: Path):
    return make(load_case("extractor"), tmp_path)


def good_clean(drop: tuple = ()) -> pd.DataFrame:
    rows = [{"date": f"{y}-01-01", "region": region, "sex": "T", "age": "", "indicator": "life_expectancy_at_birth", "value": v, "unit": "years", "source_id": "s1"}
            for (region, y), v in fixtures.EXTRACTOR_TRUTH.items() if (region, y) not in drop]
    return pd.DataFrame(rows)


def run_extractor(box, df: pd.DataFrame | None, *, raw: bool = True, tamper: bool = False) -> dict[str, bool]:
    root, params, before = box
    study = root / "studies" / fixtures.SLUG
    if df is not None:
        (study / "data" / "clean").mkdir(parents=True, exist_ok=True)
        df.to_parquet(study / "data" / "clean" / "s1.parquet")
    if raw:
        record_file(study, f"http://127.0.0.1:{PORT}/data.csv", "s1_data.csv", fixtures.EXTRACTOR_CSV.encode())
        (study / "data" / "extract").mkdir(parents=True, exist_ok=True)
        (study / "data" / "extract" / "s1.json").write_text("{}", encoding="utf-8")
        if tamper:
            (study / "data" / "raw" / "s1_data.csv").write_text("edited by hand", encoding="utf-8")
    return grade(["extractor_output_correct", "writes_only_own_files"], root, before, params, "extractor")


def test_a_correct_extraction_passes(extractor_box) -> None:
    results = run_extractor(extractor_box, good_clean())
    assert all(results.values()), results


def test_the_planted_gap_is_expected_not_filled() -> None:
    assert ("Portugal", 2022) not in fixtures.EXTRACTOR_TRUTH and ("Portugal", 2021) in fixtures.EXTRACTOR_TRUTH
    assert ("European Union (27)", 2022) in fixtures.EXTRACTOR_TRUTH


@pytest.mark.parametrize(("make_df", "kwargs", "failing"), [
    (lambda: None, {"raw": False}, "clean_parquet_written"),
    (lambda: good_clean().drop(columns="source_id"), {}, "canonical_columns"),
    (lambda: good_clean().assign(value=lambda d: d["value"] + (d["date"] == "2020-01-01") * 1.0), {}, "values_match_the_source"),
    (lambda: good_clean(drop=(("Portugal", 2015),)), {}, "values_match_the_source"),
    (lambda: pd.concat([good_clean(), good_clean().assign(region="Spain")]), {}, "only_the_requested_rows"),
    (lambda: good_clean().assign(sex=lambda d: d["sex"].where(d.index % 2 == 0, "M")), {}, "only_the_requested_rows"),
    (lambda: good_clean().replace({"Portugal": "PT", "European Union (27)": "EU27_2020"}), {}, "readable_labels"),
    (lambda: good_clean(), {"raw": False}, "provenance_recorded"),
    (lambda: good_clean(), {"tamper": True}, "provenance_recorded"),
])
def test_each_kind_of_bad_extraction_is_caught(extractor_box, make_df, kwargs, failing: str) -> None:
    assert not run_extractor(extractor_box, make_df(), **kwargs)[failing]


# ---- analyst -----------------------------------------------------------------------------------------------------

REFERENCE_SCRIPT = textwrap.dedent('''
    """Reference analysis: one line chart per source, from data/clean."""
    import sys
    from pathlib import Path

    import pandas as pd

    ROOT = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(ROOT))
    from common.charts import export_series_json, register_chart

    STUDY = ROOT / "studies" / "mini-eval"
    for sid, chart_id, axis in (("s1", "q1_avoidable", "hospitalizacoes"), ("s2", "q2_spend", "despesa")):
        df = pd.read_parquet(STUDY / "data" / "clean" / f"{sid}.parquet")
        export_series_json(df[["date", "region", "sex", "age", "indicator", "value", "unit", "source_id"]], STUDY / "analysis" / "out" / f"{chart_id}.json")
        register_chart(STUDY, chart_id=chart_id, data_file=f"{chart_id}.json", axis=axis, title_pt=chart_id, title_en=chart_id,
                       kind="line", why="uma série longa de um só país: evolução ao longo do tempo")
''')


def analyst_breaks(extra: int = 0, drop: str | None = None) -> list[Break]:
    rows = [Break(id="b001", series="s1:avoidable", axis="hospitalizacoes", date="2012-01-01", type="level", magnitude=-60.0, method="pelt"),
            Break(id="b002", series="s1:avoidable", axis="hospitalizacoes", date="2020-01-01", type="peak", magnitude=-45.0, method="zscore"),
            Break(id="b003", series="s2:spend", axis="despesa", date="2011-01-01", type="level", magnitude=-180.0, method="pelt")]
    rows += [Break(id=f"x{i:03d}", series="s1:avoidable", axis="hospitalizacoes", date=f"{2001 + i % 20}-01-01", type="slope", magnitude=1.0, method="pelt") for i in range(extra)]
    return [r for r in rows if r.id != drop]


@pytest.fixture
def analyst_box(tmp_path: Path):
    return make(load_case("analyst"), tmp_path)


ANALYST_GRADERS = ["analyst_phase4_passes", "analyst_breaks_found", "analyst_scripts_reproduce_the_charts", "analyst_charts_trace_to_clean_data", "writes_only_own_files"]


def run_analyst(box, script: str | None = REFERENCE_SCRIPT, breaks: list[Break] | None = None, *, execute: bool = True) -> dict[str, bool]:
    import os
    import subprocess
    import sys

    root, params, before = box
    study = root / "studies" / fixtures.SLUG
    (study / "analysis").mkdir(parents=True, exist_ok=True)
    if script is not None:
        (study / "analysis" / "q1.py").write_text(script, encoding="utf-8")
        if execute:  # the agent ran it
            subprocess.run([sys.executable, str(study / "analysis" / "q1.py")], cwd=root, env={**os.environ, "PYTHONPATH": "."}, check=False, capture_output=True)
    write_csv(study / "breaks.csv", Break, analyst_breaks() if breaks is None else breaks)
    return grade(ANALYST_GRADERS, root, before, params, "analyst")


def test_a_reference_analysis_passes_every_analyst_grader(analyst_box) -> None:
    results = run_analyst(analyst_box)
    assert all(results.values()), results


@pytest.mark.parametrize(("kwargs", "failing"), [
    ({"breaks": analyst_breaks(drop="b002")}, "planted_breaks_recorded"),
    ({"breaks": analyst_breaks(drop="b003")}, "planted_breaks_recorded"),
    ({"breaks": analyst_breaks(extra=15)}, "no_flood_of_breaks"),
    ({"script": REFERENCE_SCRIPT + "\nraise RuntimeError('boom')\n"}, "scripts_reproduce_charts"),
    ({"script": REFERENCE_SCRIPT + "\nimport random, json, pathlib\np = STUDY / 'analysis' / 'out' / 'q1_avoidable.json'\nrows = json.loads(p.read_text())\nrows[0]['value'] = round(random.random(), 4)\np.write_text(json.dumps(rows))\n"}, "scripts_reproduce_charts"),
    ({"script": None}, "scripts_reproduce_charts"),
    ({"script": REFERENCE_SCRIPT.replace('df[["date"', 'df.assign(value=df["value"] * 3)[["date"')}, "charts_trace_to_clean_data"),
])
def test_each_kind_of_bad_analysis_is_caught(analyst_box, kwargs: dict, failing: str) -> None:
    assert not run_analyst(analyst_box, **kwargs)[failing]


def test_a_notebook_is_rejected_even_when_the_script_is_fine(analyst_box) -> None:
    root, *_ = analyst_box
    (root / "studies" / fixtures.SLUG / "analysis").mkdir(parents=True, exist_ok=True)
    (root / "studies" / fixtures.SLUG / "analysis" / "q1.ipynb").write_text("{}", encoding="utf-8")
    assert not run_analyst(analyst_box)["scripts_reproduce_charts"]


def test_a_chart_without_a_registered_kind_fails_phase_4(analyst_box) -> None:
    results = run_analyst(analyst_box, REFERENCE_SCRIPT.replace('kind="line", why="uma série longa de um só país: evolução ao longo do tempo"', "kind=None"))
    assert not results["phase4_check_passes"]
    json.dumps(results)
