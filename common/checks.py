"""Phase-completion checks for the /study pipeline.

Each `check_phase_N` returns (ok, problems). The study skill calls these — never an
agent's own judgment — to decide whether a phase is done. Usage:

    uv run python -m common.checks <slug> <phase>

Exits 0 if the phase's condition holds, 1 otherwise, printing the problems found.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from common import chartkinds, provenance
from common.csv_io import read_csv
from common.download import verify_manifest
from common.schemas import Break, Claim, DataSource, Event, EventLink
from common.summarize import load_chart

STUDIES_ROOT = Path(__file__).resolve().parent.parent / "studies"
EVENTS_CSV = Path(__file__).resolve().parent.parent / "events" / "events.csv"

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
    axes = _plan_axes(slug)
    if not axes:
        problems.append("plan.md não tem uma secção `## Eixos` com os eixos em lista (- `slug` — organismo): o orquestrador divide a fase 2 por ela")
    else:
        used = set(re.findall(r"[Ee]ixo[:*\s`]*\s*([a-z0-9]+(?:-[a-z0-9]+)*)", text.split("## Eixos")[0]))
        problems += [f"as perguntas usam o eixo '{a}', que não está em `## Eixos`" for a in sorted(used - set(axes))]
        problems += [f"o eixo '{a}' de `## Eixos` não tem nenhuma pergunta" for a in axes if a not in used]
    return not problems, problems


TRANSIENT_REASON = re.compile(
    r"time-?out|timed out|\b429\b|too many requests|rate.?limit|temporar|tempor[aá]ri|connection (reset|refused)"
    r"|inacess[ií]vel a partir",
    re.IGNORECASE,
)


def _plan_axes(slug: str) -> list[str]:
    """Axis slugs listed under '## Eixos' in plan.md: bullets (`- `axis-slug` — organisation`) or table rows
    (`| `axis-slug` | organisation |`), the slug backticked or not."""
    plan = _study_dir(slug) / "plan.md"
    if not plan.exists():
        return []
    section = re.search(r"^## Eixos\s*\n(.*?)(?=^## |\Z)", plan.read_text(encoding="utf-8"), re.MULTILINE | re.DOTALL)
    if not section:
        return []
    axes = re.findall(r"^\s*[-*]\s*`([a-z0-9-]+)`", section.group(1), re.MULTILINE)
    axes += re.findall(r"^\s*\|\s*`?([a-z0-9]+(?:-[a-z0-9]+)*)`?\s*\|", section.group(1), re.MULTILINE)
    return [a for a in dict.fromkeys(axes) if a not in ("eixo", "axis")]  # table header cells are not axes


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
        # A timeout only matters when it leaves an axis without a usable source (flagged below);
        # a source dropped for it while the axis is otherwise covered is a smaller, disclosed loss.
        if (row.status == "excluded" and TRANSIENT_REASON.search(row.exclusion_reason or "")
                and not any(r.status == "tested" and r.axis == row.axis for r in rows)):
            problems.append(
                f"fonte {row.id} foi excluída por uma falha possivelmente temporária ('{row.exclusion_reason[:60]}'): "
                "voltar a testar mais tarde; timeout/429 não é motivo de exclusão"
            )
        if row.status == "tested" and not (row.url and row.license and row.temporal_coverage and row.format):
            problems.append(f"fonte {row.id} está testada mas falta url/licenca/cobertura/formato")
    tested_axes = {r.axis for r in rows if r.status == "tested"}
    for axis in _plan_axes(slug):
        if axis not in tested_axes:
            problems.append(
                f"eixo '{axis}' do plano não tem nenhuma fonte testada: repetir a procura ou, se for mesmo "
                "indisponível, pedir decisão ao utilizador (excluir um eixo é difícil de reverter)"
            )
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


CHART_REQUIRED_KEYS = {"date", "value", "source_id"}  # charts.js reads date/value; source_id lets common.summarize find the clean file


def _chart_json_problems(path: Path, chart_id: str) -> list[str]:
    """A chart JSON must use the canonical column names, or the site draws an empty chart."""
    if not path.is_file():
        return [f"gráfico {chart_id}: ficheiro {path.name} não existe em analysis/out/"]
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"gráfico {chart_id}: {path.name} não é JSON válido ({exc})"]
    if not isinstance(records, list) or not records or not isinstance(records[0], dict):
        return [f"gráfico {chart_id}: {path.name} deve ser uma lista não vazia de registos"]
    missing = CHART_REQUIRED_KEYS - set(records[0])
    if missing:
        return [f"gráfico {chart_id}: {path.name} sem as chaves canónicas {sorted(missing)} (tem {sorted(records[0])})"]
    return []


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
        for chart_id, entry in charts.items():
            path = study_dir / "analysis" / "out" / str(entry.get("data_file", ""))
            json_problems = _chart_json_problems(path, chart_id)
            problems.extend(json_problems)
            if not json_problems:
                problems.extend(chartkinds.kind_problems(chart_id, entry, load_chart(path)))
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
    events = {e.id: e for e in read_csv(EVENTS_CSV, Event)}
    for event_id in sorted({l.event_id for l in links if l.status == "linked" and l.event_id}):
        event = events.get(event_id)
        if event is None:
            problems.append(f"evento {event_id} está em event_links.csv mas não em events/events.csv")
        elif not event.source_excerpt or len(event.source_excerpt.split()) >= 15:
            problems.append(f"evento {event_id}: falta source_excerpt (menos de 15 palavras, copiado da página de primary_source_url)")
    return not problems, problems


FILE_VAR = re.compile(r'(\w+)\s*=\s*FileAttachment\("([^"]+\.json)"\)')
CHART_CALL = re.compile(r"\b(" + "|".join(chartkinds.JS_TO_KIND) + r")\(\s*Plotly\s*,\s*(\w+)")


def chart_use_problems(study_dir: Path) -> list[str]:
    """What the reports do with the chart catalogue: no hand-written plotting, and a chart kind the data supports.

    The kind check is best effort: it only judges a call whose data argument is a variable read straight from a
    registered chart JSON (`x = FileAttachment("f.json").json()` then `fn(Plotly, x, ...)`); data the writer
    filtered or reshaped first cannot be judged from the text and is left alone."""
    charts_path = study_dir / "analysis" / "charts.yml"
    charts = (yaml.safe_load(charts_path.read_text(encoding="utf-8")) or {}) if charts_path.exists() else {}
    by_file = {str(entry.get("data_file")): (cid, entry) for cid, entry in charts.items()}
    problems = []
    for lang in ("pt", "en"):
        report = study_dir / f"report.{lang}.qmd"
        if not report.exists():
            continue
        text = report.read_text(encoding="utf-8")
        for needle in chartkinds.HANDWRITTEN_PLOTTING:
            if needle in text:
                problems.append(f"report.{lang}.qmd escreve gráficos à mão ({needle}...): usa as funções de site/assets/charts.js")
        var_file = dict(FILE_VAR.findall(text))
        for fn, var in CHART_CALL.findall(text):
            target = by_file.get(var_file.get(var, ""))
            if target is None:
                continue
            chart_id, entry = target
            path = study_dir / "analysis" / "out" / str(entry.get("data_file"))
            if not path.exists():
                continue
            allowed = chartkinds.allowed_kinds(chartkinds.shape_of(load_chart(path)), composition=bool(entry.get("composition")))
            if chartkinds.JS_TO_KIND[fn] not in allowed:
                problems.append(f"report.{lang}.qmd: {fn}() não serve aos dados de {chart_id}; permitidos: {', '.join(allowed)}")
    return problems


def claim_row_problems(study_dir: Path, claims: list[Claim]) -> list[str]:
    """Rules every claims.csv row must satisfy before verification: what the writer can get wrong offline."""
    problems = []
    unverified_urls = {e.primary_source_url for e in read_csv(EVENTS_CSV, Event) if e.verified != "yes"}
    for c in claims:
        if c.type in ("event", "link") and c.url in unverified_urls:
            problems.append(f"afirmação {c.id}: o evento de {c.url} não está verified=yes em events.csv; só se citam eventos confirmados")
        if c.source_nature == "internal":
            problems += [f"afirmação {c.id}: {p}" for p in provenance.internal_problems(study_dir, c)]
        elif c.type == "data":
            missing = [name for name in ("value", "clean_file", "calculation") if not getattr(c, name)]
            if missing:
                problems.append(f"afirmação {c.id} (data) sem {', '.join(missing)}: tem de ser recalculável por código")
        elif not re.match(r"^https?://\S+$", c.url):
            problems.append(
                f"afirmação {c.id}: url '{c.url}' não é um URL http(s); afirmações sobre o processo do estudo "
                "usam source_nature=internal com o caminho do ficheiro"
            )
    return problems


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

    problems += claim_row_problems(study_dir, claims)
    problems += chart_use_problems(study_dir)
    return not problems, problems


# Cross-references to a section/figure/table/note by number aren't factual claims.
_CROSS_REFERENCE_PATTERN = re.compile(
    r"\b(Pergunta|Question|Figura|Figure|Tabela|Table|Nota|Note|Secção|Section)\s+\d+\b",
    re.IGNORECASE,
)


# Digits that are not facts about the world: identifiers (s1, PT11, ilm02), licence versions (CC BY 4.0), the
# denominator of a unit ("por 100 000 hab."), disease names (COVID-19), URLs, code spans, list numbering.
_NON_FACT_PATTERNS = [
    re.compile(r"https?://\S+|<[^>\s]+>|\]\([^)]*\)"),
    re.compile(r"`[^`]*`"),
    re.compile(r"\bCC[ -]BY(?:[ -][A-Z]{2})?[ -]\d(?:\.\d)?\b"),
    re.compile(r"\b(?:por|per)\s+\d{1,3}(?:[ \u00a0.,]\d{3})*\s*(?:hab\w*|habitantes|inhabitants|population|people|nados|births)?", re.IGNORECASE),
    re.compile(r"\bCOVID-19\b|\bSARS-CoV-2\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z_][A-Za-z_]*\d[A-Za-z_\d]*\b|\b\d+[A-Za-z_]+\d*\b"),  # identifiers: letters mixed with digits
    re.compile(r"^\s*\d+[.)]\s+"),  # "1. " list numbering
]
_BOLD_YEAR = re.compile(r"\*\*[^*]*\*\*")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _drop_non_fact_digits(line: str) -> str:
    """The line without digits that are labels, ids or units. Years inside a bold lead-in label ("**Pico em 2020.**")
    are labels for the claims that follow, not claims."""
    line = _BOLD_YEAR.sub(lambda m: _YEAR.sub(" ", m.group(0)), line)
    for pattern in _NON_FACT_PATTERNS:
        line = pattern.sub(" ", line)
    return line


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
        found.extend(NUMBER_PATTERN.findall(_drop_non_fact_digits(line)))
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
    problems += claim_row_problems(study_dir, claims)
    for a in claims:
        if a.verification_status != "confirmed":
            problems.append(f"afirmação {a.id} tem verification_status={a.verification_status}, não 'confirmed'")
    return not problems, problems


ALLOWED_LICENSE = re.compile(
    r"CC[\s-]?BY(?![\s-]?(NC|ND|SA))|CC0|reutiliza|reuse|dom[ií]nio p[uú]blico|public domain|open government",
    re.IGNORECASE,
)
BLOCKED_LICENSE = re.compile(r"\bNC\b|\bND\b|\bSA\b|n[aã]o[\s-]comercial|non[\s-]?commercial|sem[\s-]deriva", re.IGNORECASE)


def license_problems(study_dir: Path) -> list[str]:
    """Tested sources whose licence does not clearly allow redistributing derived data with attribution.

    The clean data, chart JSON and open_data.csv are published, so a non-commercial, no-derivatives or
    share-alike licence (or an unknown one) needs a human decision before the study can go out."""
    path = study_dir / "sources.csv"
    if not path.exists():
        return []
    problems = []
    for src in read_csv(path, DataSource):
        if src.status != "tested":
            continue
        lic = (src.license or "").strip()
        if not lic or BLOCKED_LICENSE.search(lic) or not ALLOWED_LICENSE.search(lic):
            problems.append(f"fonte {src.id} ({src.organisation}): licença '{lic or 'em falta'}' não permite publicar dados derivados; decisão do utilizador (pending.md)")
    return problems


def check_phase_8(slug: str) -> tuple[bool, list[str]]:
    site_root = Path(__file__).resolve().parent.parent / "site" / "_site"
    problems = license_problems(_study_dir(slug))
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
