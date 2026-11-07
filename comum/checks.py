"""Phase-completion checks for the /estudo pipeline.

Each `check_fase_N` returns (ok, problems). The estudo skill calls these — never an
agent's own judgment — to decide whether a phase is done. Usage:

    uv run python -m comum.checks <slug> <fase>

Exits 0 if the phase's condition holds, 1 otherwise, printing the problems found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from comum.csv_io import read_csv
from comum.download import verify_manifest
from comum.schemas import Afirmacao, FonteDados, LigacaoEvento, Quebra

ESTUDOS_ROOT = Path(__file__).resolve().parent.parent / "estudos"

CLAIM_PATTERN = re.compile(r'\{\.claim\s+id="(c\d+)"\}')
NUMBER_PATTERN = re.compile(r"\d[\d.,]*\s*%?")
GRAU_LANGUAGE = {
    "A": [r"contribuiu para", r"contributed to"],
    "B": [r"pode ter contribuído", r"may have contributed to"],
    "C": [r"coincidiu com", r"coincided with"],
}


def _study_dir(slug: str) -> Path:
    return ESTUDOS_ROOT / slug


def check_fase_1(slug: str) -> tuple[bool, list[str]]:
    plano = _study_dir(slug) / "plano.md"
    problems = []
    if not plano.exists():
        return False, ["plano.md não existe"]
    text = plano.read_text(encoding="utf-8")
    questions = re.findall(r"^\s*\d+[.)]\s+.+", text, re.MULTILINE)
    if not (5 <= len(questions) <= 10):
        problems.append(f"plano.md tem {len(questions)} perguntas numeradas; são necessárias 5 a 10")
    for i, q in enumerate(questions, start=1):
        block_match = re.search(rf"{re.escape(q)}(.*?)(?=^\s*\d+[.)]|\Z)", text, re.MULTILINE | re.DOTALL)
        block = q + (block_match.group(1) if block_match else "")
        if "eixo" not in block.lower():
            problems.append(f"pergunta {i} não indica um eixo")
        if "fonte" not in block.lower():
            problems.append(f"pergunta {i} não indica uma fonte candidata")
    return not problems, problems


def check_fase_2(slug: str) -> tuple[bool, list[str]]:
    fontes_path = _study_dir(slug) / "fontes.csv"
    if not fontes_path.exists():
        return False, ["fontes.csv não existe"]
    rows = read_csv(fontes_path, FonteDados)
    problems = []
    if not rows:
        problems.append("fontes.csv não tem nenhuma linha")
    for row in rows:
        if row.estado == "excluida" and not row.motivo_exclusao:
            problems.append(f"fonte {row.id} está excluída mas não tem motivo_exclusao")
        if row.estado == "testada" and not (row.url and row.licenca and row.cobertura_temporal and row.formato):
            problems.append(f"fonte {row.id} está testada mas falta url/licenca/cobertura/formato")
    return not problems, problems


def check_fase_3(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    problems = verify_manifest(study_dir)
    fontes = read_csv(study_dir / "fontes.csv", FonteDados)
    clean_dir = study_dir / "dados" / "clean"
    clean_files = set(clean_dir.glob("*.parquet")) if clean_dir.exists() else set()
    if not clean_files:
        problems.append("dados/clean/ não tem nenhum ficheiro .parquet")
    tested = [f for f in fontes if f.estado == "testada"]
    if tested and not clean_files:
        problems.append("há fontes testadas mas nenhum dado normalizado em dados/clean/")
    return not problems, problems


def check_fase_4(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    problems = []
    graficos_path = study_dir / "analise" / "graficos.yml"
    if not graficos_path.exists():
        problems.append("analise/graficos.yml não existe (nenhum gráfico registado)")
    else:
        graficos = yaml.safe_load(graficos_path.read_text(encoding="utf-8")) or {}
        if not graficos:
            problems.append("analise/graficos.yml está vazio")
    quebras_path = study_dir / "quebras.csv"
    if not quebras_path.exists():
        problems.append("quebras.csv não existe")
    else:
        quebras = read_csv(quebras_path, Quebra)
        if not quebras:
            problems.append("quebras.csv não tem nenhuma linha")
    return not problems, problems


def check_fase_5(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    quebras = read_csv(study_dir / "quebras.csv", Quebra)
    ligacoes = read_csv(study_dir / "ligacoes_eventos.csv", LigacaoEvento)
    problems = []
    linked_quebra_ids = {l.quebra_id for l in ligacoes if l.quebra_id}
    for q in quebras:
        if q.id not in linked_quebra_ids:
            problems.append(f"quebra {q.id} sem nenhuma linha em ligacoes_eventos.csv (ligada ou 'sem evento identificado')")
    for l in ligacoes:
        if l.estado == "ligado" and not l.grau:
            problems.append(f"ligação {l.id} está 'ligado' mas não tem grau A/B/C")
    return not problems, problems


def check_fase_6(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    problems = []
    afirmacoes = read_csv(study_dir / "afirmacoes.csv", Afirmacao)
    afirmacao_ids = {a.id for a in afirmacoes}

    for lang, suffix in [("pt", "pt"), ("en", "en")]:
        report_path = study_dir / f"relatorio.{suffix}.qmd"
        if not report_path.exists():
            problems.append(f"relatorio.{suffix}.qmd não existe")
            continue
        text = report_path.read_text(encoding="utf-8")
        if len(text.strip()) < 200:
            problems.append(f"relatorio.{suffix}.qmd parece vazio")

        used_ids = set(CLAIM_PATTERN.findall(text))
        missing_ids = used_ids - afirmacao_ids
        for mid in missing_ids:
            problems.append(f"relatorio.{suffix}.qmd usa id {mid} sem linha correspondente em afirmacoes.csv")

        # crude check: numbers outside claim spans suggest an unmarked claim; this flags
        # candidates for the redator/verificador to review, it does not try to be exact.
        unmarked_numbers = _numbers_outside_claims(text)
        if unmarked_numbers:
            problems.append(
                f"relatorio.{suffix}.qmd tem números possivelmente sem marca .claim: {unmarked_numbers[:5]}"
            )

        for afirmacao in afirmacoes:
            if afirmacao.id not in used_ids or not afirmacao.grau:
                continue
            patterns = GRAU_LANGUAGE[afirmacao.grau]
            claim_text = afirmacao.texto_pt if suffix == "pt" else afirmacao.texto_en
            if not any(re.search(p, claim_text, re.IGNORECASE) for p in patterns):
                problems.append(
                    f"afirmação {afirmacao.id} tem grau {afirmacao.grau} mas o texto não usa a linguagem correspondente"
                )

    return not problems, problems


# Cross-references to a section/figure/table/note by number aren't factual claims.
_CROSS_REFERENCE_PATTERN = re.compile(
    r"\b(Pergunta|Question|Figura|Figure|Tabela|Table|Nota|Note|Secção|Section)\s+\d+\b",
    re.IGNORECASE,
)


def _numbers_outside_claims(text: str) -> list[str]:
    # Remove claim spans (and their inner text) before looking for stray numbers.
    spans = []
    for m in re.finditer(r"\[[^\]]*\]\{\.claim[^}]*\}", text):
        spans.append((m.start(), m.end()))
    stripped = []
    last = 0
    for start, end in spans:
        stripped.append(text[last:start])
        last = end
    stripped.append(text[last:])
    remainder = _CROSS_REFERENCE_PATTERN.sub("", " ".join(stripped))

    # Drop headings and the full contents of fenced code blocks (``` ... ```, including
    # ```{ojs} chunks) — code (e.g. a FileAttachment filename) is not prose with claims.
    lines = []
    in_fence = False
    for line in remainder.splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or stripped_line.startswith("#"):
            continue
        lines.append(line)

    found = []
    for line in lines:
        found.extend(NUMBER_PATTERN.findall(line))
    return found


def check_fase_7(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    problems = []
    verificacao = study_dir / "verificacao.md"
    if not verificacao.exists():
        return False, ["verificacao.md não existe"]
    text = verificacao.read_text(encoding="utf-8").lower()
    if "pendente" in text:
        problems.append("verificacao.md ainda tem itens marcados como pendentes")
    afirmacoes = read_csv(study_dir / "afirmacoes.csv", Afirmacao)
    for a in afirmacoes:
        if a.estado_verificacao != "confirmada":
            problems.append(f"afirmação {a.id} tem estado_verificacao={a.estado_verificacao}, não 'confirmada'")
    return not problems, problems


def check_fase_8(slug: str) -> tuple[bool, list[str]]:
    site_root = Path(__file__).resolve().parent.parent / "site" / "_site"
    problems = []
    for lang in ["pt", "en"]:
        index = site_root / lang / "index.html"
        study_page = site_root / lang / "estudos" / slug / "index.html"
        if not index.exists():
            problems.append(f"site/_site/{lang}/index.html não existe (quarto render falhou?)")
        if not study_page.exists():
            problems.append(f"site/_site/{lang}/estudos/{slug}/index.html não existe")
    return not problems, problems


CHECKS = {
    1: check_fase_1,
    2: check_fase_2,
    3: check_fase_3,
    4: check_fase_4,
    5: check_fase_5,
    6: check_fase_6,
    7: check_fase_7,
    8: check_fase_8,
}


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: uv run python -m comum.checks <slug> <fase 1-8>", file=sys.stderr)
        raise SystemExit(2)
    slug, fase_str = sys.argv[1], sys.argv[2]
    fase = int(fase_str)
    if fase not in CHECKS:
        print(f"fase inválida: {fase} (tem de ser 1-8)", file=sys.stderr)
        raise SystemExit(2)
    ok, problems = CHECKS[fase](slug)
    if ok:
        print(f"[OK] fase {fase} do estudo '{slug}' está completa")
        raise SystemExit(0)
    print(f"[FALHOU] fase {fase} do estudo '{slug}':")
    for p in problems:
        print(f"  - {p}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
