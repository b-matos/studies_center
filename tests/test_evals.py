"""The eval framework: graders must accept good agent output and reject each kind of bad output, deterministically."""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from common.csv_io import read_csv, write_csv
from common.schemas import Claim, EventLink
from evals import fixtures, graders, report, run, sandbox


@pytest.fixture
def box(tmp_path: Path) -> Path:
    root, _ = sandbox.make_sandbox({"fixture": {"upto_phase": 4}}, parent=tmp_path)
    return root


def ctx(root: Path, agent: str, before: dict | None = None, **params) -> graders.Ctx:
    return graders.Ctx(sandbox=root, agent=agent, before=before or {}, after=sandbox.snapshot(root), params=params)


def names(results: list[graders.Result], passed: bool) -> set[str]:
    return {r.name for r in results if r.passed is passed}


def link(i: int, break_id: str, event_id: str, grade: str, status: str = "linked") -> EventLink:
    return EventLink(id=f"l{i}", break_id=break_id, event_id=event_id, status=status, grade=grade, justification_window="2 anos", justification_pt="p", justification_en="e")


# ---- sandbox and fixtures ----------------------------------------------------------------------------------------

def test_the_fixture_study_is_deterministic_and_complete(tmp_path: Path) -> None:
    a, _ = sandbox.make_sandbox({"fixture": {"upto_phase": 5, "links": True, "summaries": True}}, parent=tmp_path)
    b, _ = sandbox.make_sandbox({"fixture": {"upto_phase": 5, "links": True, "summaries": True}}, parent=tmp_path)
    study = a / "studies" / fixtures.SLUG
    for name in ("plan.md", "sources.csv", "breaks.csv", "event_links.csv", "analysis/charts.yml", "analysis/summary.md", "analysis/trends.csv", "data/raw_manifest.csv"):
        assert (study / name).exists(), name
    assert (a / "events" / "events.csv").exists() and (a / ".claude" / "agents" / "historian.md").exists()
    assert sandbox.snapshot(a)["studies/mini-eval/breaks.csv"] == sandbox.snapshot(b)["studies/mini-eval/breaks.csv"]
    assert not (a / "studies" / "health-status-portugal").exists(), "the repository's real studies are never copied"


def test_snapshot_sees_what_an_agent_changes(box: Path) -> None:
    before = sandbox.snapshot(box)
    (box / "studies" / fixtures.SLUG / "event_links.csv").write_text("x", encoding="utf-8")
    (box / "studies" / fixtures.SLUG / "plan.md").write_text("changed", encoding="utf-8")
    assert graders.Ctx(sandbox=box, agent="historian", before=before, after=sandbox.snapshot(box)).changed() == [
        "studies/mini-eval/event_links.csv", "studies/mini-eval/plan.md"]


# ---- historian graders -------------------------------------------------------------------------------------------

def test_a_careful_historian_passes_every_grader(box: Path) -> None:
    before = sandbox.snapshot(box)
    write_csv(box / "studies" / fixtures.SLUG / "event_links.csv", EventLink, fixtures.correct_links())
    results = graders.grade(["historian_links_valid", "historian_no_overclaiming", "historian_window_and_far_events", "historian_positive_control", "writes_only_own_files"],
                            ctx(box, "historian", before))
    assert all(r.passed for r in results), [(r.name, r.detail) for r in results if not r.passed]


@pytest.mark.parametrize(("links", "failing"), [
    ([link(1, "b001", "ev_lei_2012", "A"), link(2, "b002", "ev_pandemia_2020", "C"), link(3, "b003", "ev_memorando_2011", "C")], "no_overclaiming"),
    ([link(1, "b001", "ev_lei_2012", "B"), link(2, "b002", "ev_pandemia_2020", "C"), link(3, "b003", "ev_memorando_2011", "C")], "no_overclaiming"),
    ([link(1, "b001", "ev_distante_2002", "C"), link(2, "b002", "ev_pandemia_2020", "C"), link(3, "b003", "ev_memorando_2011", "C")], "links_within_window"),
    ([link(1, "b001", "ev_inventado", "C"), link(2, "b002", "ev_pandemia_2020", "C"), link(3, "b003", "ev_memorando_2011", "C")], "links_name_existing_events"),
    ([link(1, "b001", "ev_programa_2011", "C"), link(2, "b002", "ev_pandemia_2020", "C"), link(3, "b003", "ev_memorando_2011", "C")], "positive_control_recognised"),
])
def test_each_kind_of_bad_historian_output_is_caught(box: Path, links: list[EventLink], failing: str) -> None:
    write_csv(box / "studies" / fixtures.SLUG / "event_links.csv", EventLink, links)
    results = graders.grade(["historian_links_valid", "historian_no_overclaiming", "historian_window_and_far_events", "historian_positive_control"], ctx(box, "historian"))
    assert failing in names(results, False), [(r.name, r.passed) for r in results]


def test_a_missing_or_unparsable_links_file_fails_cleanly(box: Path) -> None:
    assert "links_file_written" in names(graders.grade(["historian_links_valid"], ctx(box, "historian")), False)
    (box / "studies" / fixtures.SLUG / "event_links.csv").write_text("not,a,valid\nfile,at,all\n", encoding="utf-8")
    assert "links_file_written" in names(graders.grade(["historian_links_valid"], ctx(box, "historian")), False)


def test_events_never_invented_and_breaks_all_covered(box: Path) -> None:
    write_csv(box / "studies" / fixtures.SLUG / "event_links.csv", EventLink, fixtures.correct_links()[:2])  # b002 and b003 missing
    assert "phase5_check_passes" in names(graders.grade(["historian_links_valid"], ctx(box, "historian")), False)


# ---- generic graders ---------------------------------------------------------------------------------------------

def test_writing_outside_the_allow_list_is_caught(box: Path) -> None:
    before = sandbox.snapshot(box)
    (box / "studies" / fixtures.SLUG / "event_links.csv").write_text("x", encoding="utf-8")
    assert graders.grade(["writes_only_own_files"], ctx(box, "historian", before))[0].passed
    (box / "studies" / fixtures.SLUG / "breaks.csv").write_text("tampered", encoding="utf-8")  # the analyst's file
    res = graders.grade(["writes_only_own_files"], ctx(box, "historian", before))[0]
    assert not res.passed and "breaks.csv" in res.detail


def test_self_publishing_is_caught(box: Path) -> None:
    assert graders.grade(["not_published"], ctx(box, "writer"))[0].passed
    (box / "studies" / fixtures.SLUG / "review.json").write_text("{}", encoding="utf-8")
    assert not graders.grade(["not_published"], ctx(box, "writer"))[0].passed


# ---- writer graders ----------------------------------------------------------------------------------------------

@pytest.fixture
def writer_box(tmp_path: Path) -> Path:
    root, _ = sandbox.make_sandbox({"fixture": {"upto_phase": 5, "links": True, "summaries": True}}, parent=tmp_path)
    return root


def test_numbers_must_trace_to_an_input(writer_box: Path) -> None:
    study = writer_box / "studies" / fixtures.SLUG
    real = pd.read_csv(study / "analysis" / "series.csv")["value"].iloc[3]
    (study / "report.pt.qmd").write_text(f"# R\n\nEm 2003 a taxa foi de {str(real).replace('.', ',')} [x]{{.claim id=\"c001\"}}. São 3 perguntas.\n", encoding="utf-8")
    assert graders.grade(["writer_numbers_traceable"], ctx(writer_box, "writer"))[0].passed
    (study / "report.en.qmd").write_text('# R\n\nThe rate fell to 777.7 [x]{.claim id="c001"}.\n', encoding="utf-8")
    res = graders.grade(["writer_numbers_traceable"], ctx(writer_box, "writer"))[0]
    assert not res.passed and "777.7" in res.detail


def test_urls_the_writer_could_not_know_are_flagged(writer_box: Path) -> None:
    study = writer_box / "studies" / fixtures.SLUG

    def claim(cid: str, url: str, type_: str = "fact") -> Claim:
        return Claim(id=cid, type=type_, text_pt="t", text_en="t", source_id="s1", url=url, access_date="2026-11-18", excerpt="e", source_nature="primary", location="Q1")

    write_csv(study / "claims.csv", Claim, [claim("c001", "https://gov.example.org/lei-2012"), claim("c002", "https://stats.example.org/datasets/health-spending", "data")])
    assert graders.grade(["writer_urls_not_invented"], ctx(writer_box, "writer"))[0].passed
    write_csv(study / "claims.csv", Claim, [claim("c001", "https://www.dre.pt/inventado")])
    assert not graders.grade(["writer_urls_not_invented"], ctx(writer_box, "writer"))[0].passed


def test_bilingual_parity_and_causal_wording(writer_box: Path) -> None:
    study = writer_box / "studies" / fixtures.SLUG
    (study / "report.pt.qmd").write_text('A taxa [a]{.claim id="c001"} e [b]{.claim id="c002"}.', encoding="utf-8")
    (study / "report.en.qmd").write_text('The rate [a]{.claim id="c001"}.', encoding="utf-8")
    assert not graders.grade(["writer_bilingual_parity"], ctx(writer_box, "writer"))[0].passed
    (study / "report.en.qmd").write_text('The rate [a]{.claim id="c001"} and [b]{.claim id="c002"}.', encoding="utf-8")
    assert graders.grade(["writer_bilingual_parity"], ctx(writer_box, "writer"))[0].passed

    (study / "report.pt.qmd").write_text("A pandemia de COVID-19 coincidiu com a queda.", encoding="utf-8")
    (study / "report.en.qmd").write_text("The COVID-19 pandemic coincided with the drop.", encoding="utf-8")
    assert graders.grade(["writer_causal_wording"], ctx(writer_box, "writer"))[0].passed
    (study / "report.pt.qmd").write_text("A reforma da rede hospitalar causou a queda dos internamentos.", encoding="utf-8")
    assert not graders.grade(["writer_causal_wording"], ctx(writer_box, "writer"))[0].passed


def test_coverage_tells_a_thorough_report_from_a_thin_one(writer_box: Path) -> None:
    study = writer_box / "studies" / fixtures.SLUG
    thin = "# R\n\nUm relatório curto sem detalhe.\n"
    thorough_pt = ("Quebras em 2012, 2020 e 2011. Programa de redução de internamentos evitáveis; Reforma da rede hospitalar; "
                   "Pandemia de COVID-19; Memorando de entendimento.")
    thorough_en = ("Breaks in 2012, 2020 and 2011. Avoidable hospitalisations programme; Hospital network reform; "
                   "COVID-19 pandemic; Memorandum of understanding.")
    (study / "report.pt.qmd").write_text(thin, encoding="utf-8")
    (study / "report.en.qmd").write_text(thin, encoding="utf-8")
    res = graders.grade(["writer_covers_inputs"], ctx(writer_box, "writer"))[0]
    assert not res.passed and res.severity == "quality" and "break b001" in res.detail
    (study / "report.pt.qmd").write_text(thorough_pt, encoding="utf-8")
    (study / "report.en.qmd").write_text(thorough_en, encoding="utf-8")
    assert graders.grade(["writer_covers_inputs"], ctx(writer_box, "writer"))[0].passed


def test_a_grader_crash_is_a_failed_grade_not_a_crashed_eval(box: Path) -> None:
    res = graders.grade(["writer_phase6_checks", "historian_links_valid"], ctx(box, "writer"))
    assert all(isinstance(r, graders.Result) for r in res) and not res[0].passed


# ---- verifier fault injection ------------------------------------------------------------------------------------

def test_verifier_grader_measures_recall_and_false_alarms(tmp_path: Path) -> None:
    case = {"fixture": {"upto_phase": 6, "verifier_claims": True}}
    root, params = sandbox.make_sandbox(case, port=1234, parent=tmp_path)
    claims_path = root / "studies" / fixtures.SLUG / "claims.csv"
    assert params["faulty_ids"] == {"c004", "c005", "c006", "c007"}

    def set_status(failed: set[str]) -> None:
        rows = read_csv(claims_path, Claim)
        for c in rows:
            c.verification_status = "failed" if c.id in failed else "confirmed"
        write_csv(claims_path, Claim, rows)

    set_status({"c004", "c005", "c006", "c007"})
    assert all(r.passed for r in graders.grade(["verifier_detects_faults", "verifier_does_not_touch_the_text"], ctx(root, "verifier", **params)))
    set_status({"c004", "c005"})  # missed two faults
    assert not graders.grade(["verifier_detects_faults"], ctx(root, "verifier", **params))[0].passed
    set_status({"c004", "c005", "c006", "c007", "c001"})  # one false alarm
    assert "no_false_alarms" in names(graders.grade(["verifier_detects_faults"], ctx(root, "verifier", **params)), False)
    rows = read_csv(claims_path, Claim)
    rows[0].excerpt = "texto alterado pelo verifier"
    write_csv(claims_path, Claim, rows)
    assert not graders.grade(["verifier_does_not_touch_the_text"], ctx(root, "verifier", **params))[0].passed


# ---- the runner and the report -----------------------------------------------------------------------------------

def test_every_case_names_real_graders_and_a_real_agent() -> None:
    for path in run.CASES_DIR.glob("*.yaml"):
        for case in sandbox.load_cases(path):
            assert set(case["graders"]) <= set(graders.GRADERS), (path.name, case["id"])
            assert (run.REPO / ".claude" / "agents" / f"{path.stem}.md").exists()


def test_agent_command_runs_the_agent_headlessly_with_the_cases_tools() -> None:
    cmd = run.agent_command("historian", {"tools": ["Read", "Write"], "deny": ["WebSearch", "WebFetch"]}, "do it", "sonnet")
    assert cmd[:3] == ["claude", "-p", "do it"] and cmd[cmd.index("--agent") + 1] == "historian"
    assert cmd[cmd.index("--model") + 1] == "sonnet" and cmd[cmd.index("--allowedTools") + 1] == "Read,Write,Bash(uv run *)"
    assert cmd[cmd.index("--disallowedTools") + 1] == "WebSearch,WebFetch"
    assert "dontAsk" in cmd and "stream-json" in cmd


def test_parse_stream_reads_cost_tokens_and_the_final_message() -> None:
    stream = '{"type":"assistant"}\nnot json\n{"type":"result","result":"done","total_cost_usd":1.5,"num_turns":4,"usage":{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":100}}\n'
    assert run.parse_stream(stream) == {"cost_usd": 1.5, "tokens": 115, "output": "done", "turns": 4}


def test_a_dry_run_builds_grades_and_records_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "RUNS_CSV", tmp_path / "runs.csv")
    for agent in ("historian", "writer", "verifier"):
        assert run.main([agent, "--dry-run"]) == 0
    assert not (tmp_path / "runs.csv").exists()


def test_report_flags_a_regression_between_batches(tmp_path: Path) -> None:
    def row(batch: str, passed: int, cost: float = 1.0) -> dict:
        return {"batch": batch, "timestamp": "t", "git_sha": "x", "agent": "historian", "case": "traps", "run": "1", "model": "m",
                "grader": "historian_no_overclaiming", "passed": str(passed), "severity": "critical", "detail": "", "cost_usd": str(cost), "tokens": "1", "duration_s": "1"}

    path = tmp_path / "runs.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=run.COLUMNS)
        writer.writeheader()
        writer.writerows([row("20260101T000000Z", 1, 1.0), row("20260102T000000Z", 0, 2.0), row("20260103T000000Z-dry", 0)])
    lines = report.compare(report.load(path), "historian")
    assert "20260102T000000Z vs 20260101T000000Z" in lines[0] and "dry" not in lines[0]
    assert any("REGRESSION (was 100%)" in line for line in lines)
    assert "$2.00 (was $1.00)" in lines[1]


def test_report_leaves_crashed_runs_out_of_the_pass_rates(tmp_path: Path) -> None:
    def row(run_: str, grader: str, passed: int) -> dict:
        return {"batch": "20260102T000000Z", "timestamp": "t", "git_sha": "x", "agent": "writer", "case": "c", "run": run_, "model": "opus", "grader": grader,
                "passed": str(passed), "severity": "critical", "detail": "", "cost_usd": "0", "tokens": "0", "duration_s": "1"}

    rows = [row("1", "numbers_traceable", 1), row("2", "numbers_traceable", 0), row("2", "run_completed", 0), row("3", "numbers_traceable", 1)]
    assert report.pass_rates(rows, "writer", "20260102T000000Z")[("c", "numbers_traceable")][:2] == (1.0, 2)  # run 2 crashed: not counted
