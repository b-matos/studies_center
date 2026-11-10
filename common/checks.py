"""Phase-completion checks for the /study pipeline.

Each `check_phase_N` returns (ok, problems). The study skill calls these — never an
agent's own judgment — to decide whether a phase is done. Usage:

    uv run python -m common.checks <slug> <phase>

Exits 0 if the phase's condition holds, 1 otherwise, printing the problems found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from common.csv_io import read_csv
from common.download import verify_manifest
from common.schemas import Break, Claim, DataSource, EventLink

STUDIES_ROOT = Path(__file__).resolve().parent.parent / "studies"

CLAIM_PATTERN = re.compile(r'\{\.claim\s+id="(c\d+)"\}')
NUMBER_PATTERN = re.compile(r"\d[\d.,]*\s*%?")
GRAU_LANGUAGE = {
    # One optional adverb between the verb and "para"/"to" is tolerated (e.g. "contribuiu
    # também para", "also contributed to") — natural phrasing, not a different claim.
    "A": [r"contribuiu\s+(?:\w+\s+)?para", r"contributed\s+(?:\w+\s+)?to"],
    "B": [r"pode\s+ter\s+contribuído\s+(?:\w+\s+)?para", r"may\s+have\s+(?:\w+\s+)?contributed\s+(?:\w+\s+)?to"],
    "C": [r"coincidiu\s+(?:\w+\s+)?com", r"coincided\s+(?:\w+\s+)?with"],
}


def _study_dir(slug: str) -> Path:
    return STUDIES_ROOT / slug


def check_phase_1(slug: str) -> tuple[bool, list[str]]:
    plan = _study_dir(slug) / "plan.md"
    problems = []
    if not plan.exists():
        return False, ["plan.md não existe"]
    text = plan.read_text(encoding="utf-8")
    questions = re.findall(r"^\s*\d+[.)]\s+.+", text, re.MULTILINE)
    if not (5 <= len(questions) <= 10):
        problems.append(f"plan.md tem {len(questions)} perguntas numeradas; são necessárias 5 a 10")
    for i, q in enumerate(questions, start=1):
        block_match = re.search(rf"{re.escape(q)}(.*?)(?=^\s*\d+[.)]|\Z)", text, re.MULTILINE | re.DOTALL)
        block = q + (block_match.group(1) if block_match else "")
        if "eixo" not in block.lower():
            problems.append(f"pergunta {i} não indica um eixo")
        if "fonte" not in block.lower():
            problems.append(f"pergunta {i} não indica uma fonte candidata")
    return not problems, problems


def check_phase_2(slug: str) -> tuple[bool, list[str]]:
    sources_path = _study_dir(slug) / "sources.csv"
    if not sources_path.exists():
        return False, ["sources.csv não existe"]
    rows = read_csv(sources_path, DataSource)
    problems = []
    if not rows:
        problems.append("sources.csv não tem nenhuma linha")
    for row in rows:
        if row.status == "excluded" and not row.exclusion_reason:
            problems.append(f"fonte {row.id} está excluída mas não tem exclusion_reason")
        if row.status == "tested" and not (row.url and row.license and row.temporal_coverage and row.format):
            problems.append(f"fonte {row.id} está testada mas falta url/licenca/cobertura/formato")
    return not problems, problems


def check_phase_3(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    problems = verify_manifest(study_dir)
    sources = read_csv(study_dir / "sources.csv", DataSource)
    clean_dir = study_dir / "data" / "clean"
    clean_files = set(clean_dir.glob("*.parquet")) if clean_dir.exists() else set()
    if not clean_files:
        problems.append("data/clean/ não tem nenhum ficheiro .parquet")
    tested = [f for f in sources if f.status == "tested"]
    if tested and not clean_files:
        problems.append("há fontes testadas mas nenhum dado normalizado em data/clean/")
    return not problems, problems


def check_phase_4(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    problems = []
    charts_path = study_dir / "analysis" / "charts.yml"
    if not charts_path.exists():
        problems.append("analysis/charts.yml não existe (nenhum gráfico registado)")
    else:
        charts = yaml.safe_load(charts_path.read_text(encoding="utf-8")) or {}
        if not charts:
            problems.append("analysis/charts.yml está vazio")
    breaks_path = study_dir / "breaks.csv"
    if not breaks_path.exists():
        problems.append("breaks.csv não existe")
    else:
        breaks = read_csv(breaks_path, Break)
        if not breaks:
            problems.append("breaks.csv não tem nenhuma linha")
    return not problems, problems


def check_phase_5(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    breaks = read_csv(study_dir / "breaks.csv", Break)
    links = read_csv(study_dir / "event_links.csv", EventLink)
    problems = []
    linked_break_ids = {l.break_id for l in links if l.break_id}
    for q in breaks:
        if q.id not in linked_break_ids:
            problems.append(f"quebra {q.id} sem nenhuma linha em event_links.csv (ligada ou 'sem evento identificado')")
    for l in links:
        if l.status == "linked" and not l.grade:
            problems.append(f"ligação {l.id} está 'ligado' mas não tem grau A/B/C")
    return not problems, problems


def check_phase_6(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    problems = []
    claims = read_csv(study_dir / "claims.csv", Claim)
    claim_ids = {a.id for a in claims}

    for lang, suffix in [("pt", "pt"), ("en", "en")]:
        report_path = study_dir / f"report.{suffix}.qmd"
        if not report_path.exists():
            problems.append(f"report.{suffix}.qmd não existe")
            continue
        text = report_path.read_text(encoding="utf-8")
        if len(text.strip()) < 200:
            problems.append(f"report.{suffix}.qmd parece vazio")

        used_ids = set(CLAIM_PATTERN.findall(text))
        missing_ids = used_ids - claim_ids
        for mid in missing_ids:
            problems.append(f"report.{suffix}.qmd usa id {mid} sem linha correspondente em claims.csv")

        # crude check: numbers outside claim spans suggest an unmarked claim; this flags
        # candidates for the writer/verifier to review, it does not try to be exact.
        unmarked_numbers = _numbers_outside_claims(text)
        if unmarked_numbers:
            problems.append(
                f"report.{suffix}.qmd tem números possivelmente sem marca .claim: {unmarked_numbers[:5]}"
            )

        for claim in claims:
            if claim.id not in used_ids or not claim.grade:
                continue
            patterns = GRAU_LANGUAGE[claim.grade]
            claim_text = claim.text_pt if suffix == "pt" else claim.text_en
            if not any(re.search(p, claim_text, re.IGNORECASE) for p in patterns):
                problems.append(
                    f"afirmação {claim.id} tem grau {claim.grade} mas o texto não usa a linguagem correspondente"
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


def check_phase_7(slug: str) -> tuple[bool, list[str]]:
    study_dir = _study_dir(slug)
    problems = []
    verification = study_dir / "verification.md"
    if not verification.exists():
        return False, ["verification.md não existe"]
    text = verification.read_text(encoding="utf-8").lower()
    if "pendente" in text or "pending" in text:
        problems.append("verification.md ainda tem itens marcados como pendentes")
    claims = read_csv(study_dir / "claims.csv", Claim)
    for a in claims:
        if a.verification_status != "confirmed":
            problems.append(f"afirmação {a.id} tem verification_status={a.verification_status}, não 'confirmed'")
    return not problems, problems


def check_phase_8(slug: str) -> tuple[bool, list[str]]:
    site_root = Path(__file__).resolve().parent.parent / "site" / "_site"
    problems = []
    for lang in ["pt", "en"]:
        index = site_root / lang / "index.html"
        study_page = site_root / lang / "studies" / slug / "index.html"
        if not index.exists():
            problems.append(f"site/_site/{lang}/index.html não existe (quarto render falhou?)")
        if not study_page.exists():
            problems.append(f"site/_site/{lang}/studies/{slug}/index.html não existe")
    return not problems, problems


CHECKS = {
    1: check_phase_1,
    2: check_phase_2,
    3: check_phase_3,
    4: check_phase_4,
    5: check_phase_5,
    6: check_phase_6,
    7: check_phase_7,
    8: check_phase_8,
}


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: uv run python -m common.checks <slug> <fase 1-8>", file=sys.stderr)
        raise SystemExit(2)
    slug, phase_str = sys.argv[1], sys.argv[2]
    phase = int(phase_str)
    if phase not in CHECKS:
        print(f"fase inválida: {phase} (tem de ser 1-8)", file=sys.stderr)
        raise SystemExit(2)
    ok, problems = CHECKS[phase](slug)
    if ok:
        print(f"[OK] fase {phase} do estudo '{slug}' está completa")
        raise SystemExit(0)
    print(f"[FALHOU] fase {phase} do estudo '{slug}':")
    for p in problems:
        print(f"  - {p}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
