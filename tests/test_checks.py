from pathlib import Path

import pytest

from common import checks
from common.csv_io import write_csv
from common.schemas import Break, Claim, DataSource, EventLink


@pytest.fixture
def study_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "studies"
    monkeypatch.setattr(checks, "STUDIES_ROOT", root)
    d = root / "test"
    d.mkdir(parents=True)
    return d


def test_phase_1_requires_5_to_10_questions_with_axis_and_source(study_dir: Path) -> None:
    (study_dir / "plan.md").write_text(
        "\n".join(f"{i}. Pergunta {i}? Eixo: mortalidade. Fonte candidata: INE." for i in range(1, 6)),
        encoding="utf-8",
    )
    ok, problems = checks.check_phase_1("test")
    assert ok, problems


def test_phase_1_fails_with_too_few_questions(study_dir: Path) -> None:
    (study_dir / "plan.md").write_text("1. Só uma pergunta? Eixo: x. Fonte: y.", encoding="utf-8")
    ok, problems = checks.check_phase_1("test")
    assert not ok
    assert any("perguntas" in p for p in problems)


def test_phase_2_source_testada_needs_required_fields(study_dir: Path) -> None:
    write_csv(
        study_dir / "sources.csv",
        DataSource,
        [
            DataSource(
                id="f1",
                axis="mortalidade",
                name="x",
                organisation="INE",
                url="",
                format="",
                license="",
                temporal_coverage="",
                geographic_coverage="PT",
                status="tested",
            )
        ],
    )
    ok, problems = checks.check_phase_2("test")
    assert not ok
    assert problems


def test_phase_2_source_excluida_needs_motivo(study_dir: Path) -> None:
    write_csv(
        study_dir / "sources.csv",
        DataSource,
        [
            DataSource(
                id="f1",
                axis="mortalidade",
                name="x",
                organisation="INE",
                url="https://x",
                format="csv",
                license="CC-BY",
                temporal_coverage="2000-2020",
                geographic_coverage="PT",
                status="excluded",
                exclusion_reason=None,
            )
        ],
    )
    ok, problems = checks.check_phase_2("test")
    assert not ok
    assert "exclusion_reason" in problems[0]


def test_phase_4_requires_charts_and_breaks(study_dir: Path) -> None:
    ok, problems = checks.check_phase_4("test")
    assert not ok
    assert len(problems) == 2


def test_phase_5_flags_break_without_link(study_dir: Path) -> None:
    write_csv(
        study_dir / "breaks.csv",
        Break,
        [Break(id="q1", series="mortalidade", axis="mortalidade", date="2010-01-01", type="level", magnitude=1.0, method="pelt")],
    )
    write_csv(study_dir / "event_links.csv", EventLink, [])
    ok, problems = checks.check_phase_5("test")
    assert not ok
    assert "q1" in problems[0]


def test_phase_5_passes_with_sem_event_note(study_dir: Path) -> None:
    write_csv(
        study_dir / "breaks.csv",
        Break,
        [Break(id="q1", series="mortalidade", axis="mortalidade", date="2010-01-01", type="level", magnitude=1.0, method="pelt")],
    )
    write_csv(
        study_dir / "event_links.csv",
        EventLink,
        [
            EventLink(
                id="l1",
                break_id="q1",
                event_id=None,
                status="break_without_event",
                grade=None,
                justification_window="procurado 5 anos antes/depois, nada encontrado",
                justification_pt="sem evento identificado",
                justification_en="no event identified",
            )
        ],
    )
    ok, problems = checks.check_phase_5("test")
    assert ok, problems


def test_phase_6_flags_claim_id_missing_from_claims(study_dir: Path) -> None:
    write_csv(study_dir / "claims.csv", Claim, [])
    (study_dir / "report.pt.qmd").write_text(
        'Em 2020 houve [10 mil óbitos]{.claim id="c001"}.' + " " * 200, encoding="utf-8"
    )
    (study_dir / "report.en.qmd").write_text(
        'In 2020 there were [10 thousand deaths]{.claim id="c001"}.' + " " * 200, encoding="utf-8"
    )
    ok, problems = checks.check_phase_6("test")
    assert not ok
    assert any("c001" in p for p in problems)


def test_phase_6_ignores_code_fences_and_cross_references(study_dir: Path) -> None:
    write_csv(
        study_dir / "claims.csv",
        Claim,
        [
            Claim(
                id="c001",
                type="fact",
                text_pt="x",
                text_en="x",
                source_id="f1",
                url="https://x",
                access_date="2026-01-01",
                excerpt="algo",
                source_nature="primary",
                location="intro",
                verification_status="confirmed",
            )
        ],
    )
    body = (
        'Ver Pergunta 5 para mais detalhe sobre [82,5 anos]{.claim id="c001"}.\n\n'
        "```{ojs}\n"
        'dados = FileAttachment("regional_snapshot_2022.json").json()\n'
        "```\n\n"
    ) + "Texto de enchimento para passar o limite mínimo de tamanho do relatório. " * 5
    (study_dir / "report.pt.qmd").write_text(body, encoding="utf-8")
    (study_dir / "report.en.qmd").write_text(body, encoding="utf-8")
    (study_dir / "verification.md").write_text("tudo confirmado", encoding="utf-8")

    ok, problems = checks.check_phase_6("test")
    assert ok, problems


def test_phase_6_grade_language_tolerates_an_adverb(study_dir: Path) -> None:
    write_csv(
        study_dir / "claims.csv",
        Claim,
        [
            Claim(
                id="c001",
                type="link",
                text_pt="a pandemia contribuiu também para esta quebra em Portugal.",
                text_en="the pandemic also contributed to this break in Portugal.",
                source_id="f1",
                url="https://x",
                access_date="2026-01-01",
                excerpt="algo",
                source_nature="primary",
                location="intro",
                grade="A",
                verification_status="confirmed",
            )
        ],
    )
    body = 'Texto com [a ligação]{.claim id="c001"}. ' + "Enchimento. " * 30
    (study_dir / "report.pt.qmd").write_text(body, encoding="utf-8")
    (study_dir / "report.en.qmd").write_text(body, encoding="utf-8")

    ok, problems = checks.check_phase_6("test")
    assert ok, problems


def test_phase_7_flags_pending_claims(study_dir: Path) -> None:
    write_csv(
        study_dir / "claims.csv",
        Claim,
        [
            Claim(
                id="c001",
                type="fact",
                text_pt="x",
                text_en="x",
                source_id="f1",
                url="https://x",
                access_date="2026-01-01",
                excerpt="algo",
                source_nature="primary",
                location="intro",
                verification_status="pending",
            )
        ],
    )
    (study_dir / "verification.md").write_text("Todas as afirmações foram confirmadas ou corrigidas.", encoding="utf-8")
    ok, problems = checks.check_phase_7("test")
    assert not ok
    assert any("c001" in p for p in problems)


def _chart_study(study_dir: Path, record: dict) -> None:
    import json

    (study_dir / "analysis" / "out").mkdir(parents=True)
    (study_dir / "analysis" / "out" / "c1.json").write_text(json.dumps([record]), encoding="utf-8")
    (study_dir / "analysis" / "charts.yml").write_text("c1:\n  data_file: c1.json\n  axis: x\n", encoding="utf-8")
    write_csv(
        study_dir / "breaks.csv",
        Break,
        [Break(id="q1", series="s", axis="x", date="2010-01-01", type="level", magnitude=1.0, method="pelt")],
    )


def test_phase_4_accepts_canonical_chart_keys(study_dir: Path) -> None:
    _chart_study(study_dir, {"date": "2010-01-01", "region": "Portugal", "value": 1.0, "source_id": "s1"})
    ok, problems = checks.check_phase_4("test")
    assert ok, problems


def test_phase_4_rejects_legacy_portuguese_chart_keys(study_dir: Path) -> None:
    _chart_study(study_dir, {"data": "2010-01-01", "regiao": "Portugal", "valor": 1.0})
    ok, problems = checks.check_phase_4("test")
    assert not ok
    assert "canónicas" in problems[0]


def _source(study_dir: Path, sid: str, license_text: str) -> None:
    write_csv(
        study_dir / "sources.csv",
        DataSource,
        [DataSource(id=sid, axis="x", name="n", organisation="INE", url="https://x", format="csv", license=license_text,
                    temporal_coverage="2000-2020", geographic_coverage="PT", status="tested")],
    )


def test_license_gate_allows_open_licences(study_dir: Path) -> None:
    for lic in ("CC BY 4.0 (INE)", "Eurostat reuse policy (reutilização livre com atribuição)", "CC0"):
        _source(study_dir, "s1", lic)
        assert checks.license_problems(study_dir) == [], lic


def test_license_gate_blocks_restrictive_or_unknown_licences(study_dir: Path) -> None:
    for lic in ("CC BY-NC-SA 3.0 IGO", "CC BY-ND 4.0", "uso não comercial", "licença desconhecida"):
        _source(study_dir, "s1", lic)
        assert len(checks.license_problems(study_dir)) == 1, lic


def test_phase_4_rejects_chart_json_without_source_id(study_dir: Path) -> None:
    _chart_study(study_dir, {"date": "2010-01-01", "region": "Portugal", "value": 1.0})
    ok, problems = checks.check_phase_4("test")
    assert not ok
    assert "source_id" in problems[0]
