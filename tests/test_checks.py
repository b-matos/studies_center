from pathlib import Path

import pytest

from comum import checks
from comum.csv_io import write_csv
from comum.schemas import Afirmacao, FonteDados, LigacaoEvento, Quebra


@pytest.fixture
def study_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "estudos"
    monkeypatch.setattr(checks, "ESTUDOS_ROOT", root)
    d = root / "teste"
    d.mkdir(parents=True)
    return d


def test_fase_1_requires_5_to_10_questions_with_eixo_and_fonte(study_dir: Path) -> None:
    (study_dir / "plano.md").write_text(
        "\n".join(f"{i}. Pergunta {i}? Eixo: mortalidade. Fonte candidata: INE." for i in range(1, 6)),
        encoding="utf-8",
    )
    ok, problems = checks.check_fase_1("teste")
    assert ok, problems


def test_fase_1_fails_with_too_few_questions(study_dir: Path) -> None:
    (study_dir / "plano.md").write_text("1. Só uma pergunta? Eixo: x. Fonte: y.", encoding="utf-8")
    ok, problems = checks.check_fase_1("teste")
    assert not ok
    assert any("perguntas" in p for p in problems)


def test_fase_2_fonte_testada_needs_required_fields(study_dir: Path) -> None:
    write_csv(
        study_dir / "fontes.csv",
        FonteDados,
        [
            FonteDados(
                id="f1",
                eixo="mortalidade",
                nome="x",
                organismo="INE",
                url="",
                formato="",
                licenca="",
                cobertura_temporal="",
                cobertura_geografica="PT",
                estado="testada",
            )
        ],
    )
    ok, problems = checks.check_fase_2("teste")
    assert not ok
    assert problems


def test_fase_2_fonte_excluida_needs_motivo(study_dir: Path) -> None:
    write_csv(
        study_dir / "fontes.csv",
        FonteDados,
        [
            FonteDados(
                id="f1",
                eixo="mortalidade",
                nome="x",
                organismo="INE",
                url="https://x",
                formato="csv",
                licenca="CC-BY",
                cobertura_temporal="2000-2020",
                cobertura_geografica="PT",
                estado="excluida",
                motivo_exclusao=None,
            )
        ],
    )
    ok, problems = checks.check_fase_2("teste")
    assert not ok
    assert "motivo_exclusao" in problems[0]


def test_fase_4_requires_graficos_and_quebras(study_dir: Path) -> None:
    ok, problems = checks.check_fase_4("teste")
    assert not ok
    assert len(problems) == 2


def test_fase_5_flags_quebra_without_ligacao(study_dir: Path) -> None:
    write_csv(
        study_dir / "quebras.csv",
        Quebra,
        [Quebra(id="q1", serie="mortalidade", eixo="mortalidade", data="2010-01-01", tipo="nivel", magnitude=1.0, metodo="pelt")],
    )
    write_csv(study_dir / "ligacoes_eventos.csv", LigacaoEvento, [])
    ok, problems = checks.check_fase_5("teste")
    assert not ok
    assert "q1" in problems[0]


def test_fase_5_passes_with_sem_evento_note(study_dir: Path) -> None:
    write_csv(
        study_dir / "quebras.csv",
        Quebra,
        [Quebra(id="q1", serie="mortalidade", eixo="mortalidade", data="2010-01-01", tipo="nivel", magnitude=1.0, metodo="pelt")],
    )
    write_csv(
        study_dir / "ligacoes_eventos.csv",
        LigacaoEvento,
        [
            LigacaoEvento(
                id="l1",
                quebra_id="q1",
                evento_id=None,
                estado="quebra_sem_evento",
                grau=None,
                janela_justificacao="procurado 5 anos antes/depois, nada encontrado",
                justificacao_pt="sem evento identificado",
                justificacao_en="no event identified",
            )
        ],
    )
    ok, problems = checks.check_fase_5("teste")
    assert ok, problems


def test_fase_6_flags_claim_id_missing_from_afirmacoes(study_dir: Path) -> None:
    write_csv(study_dir / "afirmacoes.csv", Afirmacao, [])
    (study_dir / "relatorio.pt.qmd").write_text(
        'Em 2020 houve [10 mil óbitos]{.claim id="c001"}.' + " " * 200, encoding="utf-8"
    )
    (study_dir / "relatorio.en.qmd").write_text(
        'In 2020 there were [10 thousand deaths]{.claim id="c001"}.' + " " * 200, encoding="utf-8"
    )
    ok, problems = checks.check_fase_6("teste")
    assert not ok
    assert any("c001" in p for p in problems)


def test_fase_6_ignores_code_fences_and_cross_references(study_dir: Path) -> None:
    write_csv(
        study_dir / "afirmacoes.csv",
        Afirmacao,
        [
            Afirmacao(
                id="c001",
                tipo="dado",
                texto_pt="x",
                texto_en="x",
                fonte_id="f1",
                url="https://x",
                data_acesso="2026-01-01",
                excerto="algo",
                natureza_fonte="primaria",
                localizacao="intro",
                estado_verificacao="confirmada",
            )
        ],
    )
    body = (
        'Ver Pergunta 5 para mais detalhe sobre [82,5 anos]{.claim id="c001"}.\n\n'
        "```{ojs}\n"
        'dados = FileAttachment("regional_snapshot_2022.json").json()\n'
        "```\n\n"
    ) + "Texto de enchimento para passar o limite mínimo de tamanho do relatório. " * 5
    (study_dir / "relatorio.pt.qmd").write_text(body, encoding="utf-8")
    (study_dir / "relatorio.en.qmd").write_text(body, encoding="utf-8")
    (study_dir / "verificacao.md").write_text("tudo confirmado", encoding="utf-8")

    ok, problems = checks.check_fase_6("teste")
    assert ok, problems


def test_fase_6_grau_language_tolerates_an_adverb(study_dir: Path) -> None:
    write_csv(
        study_dir / "afirmacoes.csv",
        Afirmacao,
        [
            Afirmacao(
                id="c001",
                tipo="ligacao",
                texto_pt="a pandemia contribuiu também para esta quebra em Portugal.",
                texto_en="the pandemic also contributed to this break in Portugal.",
                fonte_id="f1",
                url="https://x",
                data_acesso="2026-01-01",
                excerto="algo",
                natureza_fonte="primaria",
                localizacao="intro",
                grau="A",
                estado_verificacao="confirmada",
            )
        ],
    )
    body = 'Texto com [a ligação]{.claim id="c001"}. ' + "Enchimento. " * 30
    (study_dir / "relatorio.pt.qmd").write_text(body, encoding="utf-8")
    (study_dir / "relatorio.en.qmd").write_text(body, encoding="utf-8")

    ok, problems = checks.check_fase_6("teste")
    assert ok, problems


def test_fase_7_flags_pending_afirmacoes(study_dir: Path) -> None:
    write_csv(
        study_dir / "afirmacoes.csv",
        Afirmacao,
        [
            Afirmacao(
                id="c001",
                tipo="facto",
                texto_pt="x",
                texto_en="x",
                fonte_id="f1",
                url="https://x",
                data_acesso="2026-01-01",
                excerto="algo",
                natureza_fonte="primaria",
                localizacao="intro",
                estado_verificacao="pendente",
            )
        ],
    )
    (study_dir / "verificacao.md").write_text("Todas as afirmações foram confirmadas ou corrigidas.", encoding="utf-8")
    ok, problems = checks.check_fase_7("teste")
    assert not ok
    assert any("c001" in p for p in problems)
