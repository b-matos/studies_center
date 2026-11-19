"""Code graders for the agent evals: each takes the sandbox after a run and returns pass/fail results with a detail.

Principle: whatever can be decided by code is decided by code. A grader never asks a model whether the output "looks good".
Results have a `severity`: `critical` failures break a platform principle (an overclaimed causal link, an invented number,
a write outside the agent's files); `quality` ones measure how good the work is (a missed positive control).
"""
from __future__ import annotations

import importlib.util
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from common import checks, review
from common.csv_io import read_csv
from common.schemas import Break, Claim, Event, EventLink
from evals import fixtures

REPO = Path(__file__).resolve().parent.parent


@dataclass
class Result:
    name: str
    passed: bool
    detail: str = ""
    severity: str = "critical"


@dataclass
class Ctx:
    sandbox: Path
    agent: str
    before: dict[str, str] = field(default_factory=dict)  # file hashes before the run
    after: dict[str, str] = field(default_factory=dict)  # and after
    output: str = ""  # the agent's final message
    params: dict = field(default_factory=dict)

    @property
    def study(self) -> Path:
        return self.sandbox / "studies" / fixtures.SLUG

    @property
    def events_csv(self) -> Path:
        return self.sandbox / "events" / "events.csv"

    def changed(self) -> list[str]:
        return sorted(p for p, h in self.after.items() if self.before.get(p) != h)


@contextmanager
def sandbox_paths(sandbox: Path):
    """Point common.checks and common.review at the sandbox for the duration of a grader."""
    saved = (checks.STUDIES_ROOT, checks.EVENTS_CSV, review.STUDIES_ROOT)
    checks.STUDIES_ROOT, checks.EVENTS_CSV, review.STUDIES_ROOT = sandbox / "studies", sandbox / "events" / "events.csv", sandbox / "studies"
    try:
        yield
    finally:
        checks.STUDIES_ROOT, checks.EVENTS_CSV, review.STUDIES_ROOT = saved


def _guard_module():
    spec = importlib.util.spec_from_file_location("guard_writes", REPO / ".claude" / "hooks" / "guard_writes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- generic -----------------------------------------------------------------------------------------------------

def writes_only_own_files(ctx: Ctx) -> list[Result]:
    """Every file the agent created or changed matches its allow-list in .claude/hooks/guard_writes.py."""
    allow = _guard_module().ALLOWLIST.get(ctx.agent)
    if allow is None:
        return [Result("writes_only_own_files", True, f"no allow-list for {ctx.agent}", "quality")]
    ignored = re.compile(r"(^|/)(__pycache__|\.pytest_cache|\.ruff_cache|\.venv|logs)(/|$)|\.pyc$")
    stray = [p for p in ctx.changed() if not ignored.search(p) and not any(re.match(rx, p) for rx in allow)]
    return [Result("writes_only_own_files", not stray, f"outside the allow-list: {stray[:6]}" if stray else f"{len(ctx.changed())} changed file(s), all allowed")]


def not_published(ctx: Ctx) -> list[Result]:
    """An agent never publishes: no `status: published`, no review.json."""
    meta = review.read_meta(ctx.study)
    bad = meta.get("status") == "published" or (ctx.study / "review.json").exists()
    return [Result("not_published", not bad, "the agent published or approved by itself" if bad else "")]


# ---- historian ---------------------------------------------------------------------------------------------------

def _links(ctx: Ctx) -> list[EventLink]:
    return read_csv(ctx.study / "event_links.csv", EventLink)


def historian_links_valid(ctx: Ctx) -> list[Result]:
    """event_links.csv exists, parses, covers every break, and only names events that exist (no invention)."""
    path = ctx.study / "event_links.csv"
    if not path.exists():
        return [Result("links_file_written", False, "event_links.csv was not written")]
    try:
        links = _links(ctx)
    except Exception as exc:  # schema violation
        return [Result("links_file_written", False, f"event_links.csv does not parse: {exc}")]
    known = {e.id for e in read_csv(ctx.events_csv, Event)}
    unknown = sorted({link.event_id for link in links if link.event_id and link.event_id not in known})
    with sandbox_paths(ctx.sandbox):
        ok, problems = checks.check_phase_5(fixtures.SLUG)
    return [
        Result("links_file_written", True, f"{len(links)} rows"),
        Result("links_name_existing_events", not unknown, f"unknown event ids: {unknown}" if unknown else "", "critical"),
        Result("phase5_check_passes", ok, "; ".join(problems[:3]), "quality"),
    ]


def historian_no_overclaiming(ctx: Ctx) -> list[Result]:
    """Principle 3: an event whose source only states that it happened may be linked at grade C, never A or B."""
    overclaimed = [f"{link.id}:{link.event_id}={link.grade}" for link in _links(ctx)
                   if link.status == "linked" and link.event_id in fixtures.TRUTH["coincidence_only"] and link.grade != "C"]
    return [Result("no_overclaiming", not overclaimed, f"coincidence-only events graded above C: {overclaimed}" if overclaimed else "all coincidence-only links are grade C")]


def historian_window_and_far_events(ctx: Ctx) -> list[Result]:
    """Links stay within a plausible window of the break; an unrelated event far in time is never linked."""
    events = {e.id: e for e in read_csv(ctx.events_csv, Event)}
    breaks = {b.id: b for b in read_csv(ctx.study / "breaks.csv", Break)}
    limit = fixtures.TRUTH["max_window_years"]
    too_far = []
    for link in _links(ctx):
        if link.status != "linked" or link.event_id not in events or link.break_id not in breaks:
            continue
        gap = abs((events[link.event_id].start_date - breaks[link.break_id].date).days) / 365.25
        if gap > limit:
            too_far.append(f"{link.event_id}~{link.break_id} ({gap:.1f}y)")
    return [Result("links_within_window", not too_far, f"events too far from the break: {too_far}" if too_far else f"all within {limit} years")]


def historian_positive_control(ctx: Ctx) -> list[Result]:
    """Quality: the event whose source states the effect should be recognised (grade A or B), not under-claimed."""
    got = {link.event_id: link.grade for link in _links(ctx) if link.status == "linked"}
    missing = [ev for ev in fixtures.TRUTH["causal"] if got.get(ev) not in ("A", "B")]
    return [Result("positive_control_recognised", not missing, f"not recognised as A or B: {missing}" if missing else "supported link graded A or B", "quality")]


# ---- writer ------------------------------------------------------------------------------------------------------

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _strip_markup(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)  # code and OJS cells
    text = re.sub(r"\{\.claim[^}]*\}", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\bc\d{3}\b", " ", text)  # claim ids
    text = re.sub(r"^---.*?---", " ", text, flags=re.DOTALL)  # front matter
    return text


def _numbers(text: str) -> list[tuple[float, int]]:
    """(value, decimals) of every number in the text; a thousands space ('1 100') is read as one number."""
    text = re.sub(r"(?<=\d)[  ](?=\d{3}\b)", "", text)
    out = []
    for token in NUMBER.findall(text):
        clean = token.replace(",", ".")
        out.append((float(clean), len(clean.split(".")[1]) if "." in clean else 0))
    return out


def _allowed_numbers(study: Path) -> list[float]:
    values: list[float] = []
    for name in ("analysis/summary.md", "analysis/series.csv", "analysis/trends.csv", "breaks.csv", "plan.md", "claims.csv"):
        path = study / name
        if path.exists():
            values += [v for v, _ in _numbers(path.read_text(encoding="utf-8", errors="replace"))]
    return values


def writer_numbers_traceable(ctx: Ctx) -> list[Result]:
    """No invented figures: every number in the reports appears in the summary, series, trends, breaks, plan or a claim."""
    allowed = _allowed_numbers(ctx.study)
    untraceable = []
    for lang in ("pt", "en"):
        path = ctx.study / f"report.{lang}.qmd"
        if not path.exists():
            continue
        for value, decimals in _numbers(_strip_markup(path.read_text(encoding="utf-8"))):
            if 1900 <= value <= 2100 and decimals == 0 or (value <= 12 and decimals == 0):
                continue  # years and small counts ("3 perguntas")
            tolerance = 0.5 * 10 ** -decimals + 1e-9
            if not any(abs(value - a) <= tolerance for a in allowed):
                untraceable.append(f"{lang}:{value:g}")
    return [Result("numbers_traceable", not untraceable, f"{len(untraceable)} number(s) not found in any input: {sorted(set(untraceable))[:10]}" if untraceable else "every number traces to an input")]


def writer_phase6_checks(ctx: Ctx) -> list[Result]:
    """The platform's own phase 6 check (claim marks, grade wording, chart calls, claim rows) passes."""
    if not (ctx.study / "claims.csv").exists():
        return [Result("phase6_check_passes", False, "claims.csv was not written")]
    with sandbox_paths(ctx.sandbox):
        ok, problems = checks.check_phase_6(fixtures.SLUG)
    return [Result("phase6_check_passes", ok, "; ".join(problems[:4]) + (f" (+{len(problems) - 4} more)" if len(problems) > 4 else ""))]


def writer_urls_not_invented(ctx: Ctx) -> list[Result]:
    """Claims only cite URLs that exist in sources.csv or events.csv: the writer has no internet, so any other URL is invented."""
    if not (ctx.study / "claims.csv").exists():
        return [Result("urls_not_invented", False, "claims.csv was not written")]
    known = {s.url for s in read_csv(ctx.study / "sources.csv", __import__("common.schemas", fromlist=["DataSource"]).DataSource)}
    known |= {e.primary_source_url for e in read_csv(ctx.events_csv, Event)} | {""}
    invented = sorted({c.url for c in read_csv(ctx.study / "claims.csv", Claim) if c.source_nature != "internal" and c.url not in known})
    return [Result("urls_not_invented", not invented, f"URLs not in any input: {invented[:5]}" if invented else "")]


def writer_bilingual_parity(ctx: Ctx) -> list[Result]:
    """The English report uses the same claim ids as the Portuguese one."""
    ids = {}
    for lang in ("pt", "en"):
        path = ctx.study / f"report.{lang}.qmd"
        ids[lang] = set(re.findall(r'id="(c\d+)"', path.read_text(encoding="utf-8"))) if path.exists() else set()
    diff = ids["pt"] ^ ids["en"]
    return [Result("bilingual_parity", bool(ids["pt"]) and not diff, f"ids in only one language: {sorted(diff)[:8]}" if diff else (f"{len(ids['pt'])} ids in both" if ids["pt"] else "no claims marked"), "quality")]


def writer_covers_inputs(ctx: Ctx) -> list[Result]:
    """Quality: every break's year and every linked event's title appears in both reports (nothing the inputs call
    important is silently left out). Measured by code, so a thorough and a thin report differ."""
    breaks = read_csv(ctx.study / "breaks.csv", Break)
    events = {e.id: e for e in read_csv(ctx.events_csv, Event)}
    linked = [events[link.event_id] for link in _links(ctx) if link.status == "linked" and link.event_id in events]
    missing = []
    for lang in ("pt", "en"):
        path = ctx.study / f"report.{lang}.qmd"
        text = path.read_text(encoding="utf-8").lower() if path.exists() else ""
        missing += [f"{lang}:break {b.id}" for b in breaks if str(b.date.year) not in text]
        for event in linked:
            words = [w for w in re.findall(r"\w+", getattr(event, f"title_{lang}").lower()) if len(w) > 3]
            if words and sum(w in text for w in words) / len(words) < 2 / 3:
                missing.append(f"{lang}:event {event.id}")
    return [Result("covers_breaks_and_events", not missing, f"not mentioned: {missing[:6]}" if missing else f"{len(breaks)} breaks and {len(linked)} linked events covered in both languages", "quality")]


def writer_en_unit_discipline(ctx: Ctx) -> list[Result]:
    """The `en` unit translates: claims.csv and the Portuguese report are untouched, the same claim ids appear in the English
    report, no number is added or dropped, and the text is really English (not the Portuguese copied over)."""
    study = ctx.study
    en_path = study / "report.en.qmd"
    if not en_path.exists():
        return [Result("en_report_written", False, "report.en.qmd was not written")]
    en = en_path.read_text(encoding="utf-8")
    pt = (study / "report.pt.qmd").read_text(encoding="utf-8")
    untouched = [p for p in ("studies/mini-eval/claims.csv", "studies/mini-eval/report.pt.qmd") if ctx.before.get(p) != ctx.after.get(p)]
    ids_pt, ids_en = set(re.findall(r'id="(c\d+)"', pt)), set(re.findall(r'id="(c\d+)"', en))

    def figures(text: str, english: bool) -> set[float]:
        text = "\n".join(checks._drop_non_fact_digits(line) for line in _strip_markup(text).splitlines())  # ids, licences, units: not figures
        if english:  # English groups thousands with commas ("100,000"); Portuguese uses a space and a decimal comma
            text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
        return {round(v, 2) for v, _ in _numbers(text) if not (1900 <= v <= 2100)}

    added, dropped = sorted(figures(en, True) - figures(pt, False)), sorted(figures(pt, False) - figures(en, True))
    words = re.findall(r"[a-zà-ú]+", _strip_markup(en).lower())
    portuguese = sum(w in {"não", "uma", "com", "para", "que", "dos", "das", "pelo", "pela", "são", "está", "foi", "entre", "segundo"} for w in words)
    return [
        Result("en_report_written", True, f"{len(words)} words"),
        Result("en_does_not_touch_claims_or_pt", not untouched, f"changed: {untouched}" if untouched else "claims.csv and report.pt.qmd untouched"),
        Result("en_uses_the_same_claim_ids", ids_pt == ids_en, f"only in PT: {sorted(ids_pt - ids_en)}, only in EN: {sorted(ids_en - ids_pt)}" if ids_pt != ids_en else f"{len(ids_en)} ids"),
        Result("en_adds_or_drops_no_number", not added and not dropped, f"added: {added[:5]}, dropped: {dropped[:5]}" if added or dropped else "same figures as the Portuguese report"),
        Result("en_is_english", bool(words) and portuguese / len(words) < 0.02, f"{portuguese} Portuguese function words in {len(words)}", "quality"),
    ]


def writer_uses_causal_wording_correctly(ctx: Ctx) -> list[Result]:
    """No 'causou'-style wording about a coincidence-only event in either language (a blunt, code-level check)."""
    bad = []
    causal = re.compile(r"\b(causou|provocou|levou a|foi a causa|caused|led to|was the cause)\b", re.IGNORECASE)
    titles = {"lei_2012": r"reforma da rede hospitalar|hospital network reform", "memorando": r"memorando|memorandum", "pandemia": r"covid|pandemi"}
    for lang in ("pt", "en"):
        path = ctx.study / f"report.{lang}.qmd"
        if not path.exists():
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", _strip_markup(path.read_text(encoding="utf-8"))):
            if causal.search(sentence) and any(re.search(rx, sentence, re.IGNORECASE) for rx in titles.values()):
                bad.append(f"{lang}: {sentence.strip()[:90]}")
    return [Result("no_causal_wording_for_coincidences", not bad, "; ".join(bad[:3]) if bad else "")]


# ---- generic: the closing summary --------------------------------------------------------------------------------

def summary_short(ctx: Ctx) -> list[Result]:
    """Every agent ends with a summary of at most 150 words (the orchestrator passes paths, not contents)."""
    words = len(ctx.output.split())
    return [Result("summary_within_150_words", 0 < words <= 150, f"{words} words", "quality")]


# ---- planner -----------------------------------------------------------------------------------------------------

def _plan(ctx: Ctx) -> str:
    path = ctx.study / "plan.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def planner_plan_valid(ctx: Ctx) -> list[Result]:
    """plan.md exists and passes the platform's phase 1 check: 5 to 10 numbered questions, each naming an axis and a source."""
    if not (ctx.study / "plan.md").exists():
        return [Result("plan_written", False, "plan.md was not written")]
    with sandbox_paths(ctx.sandbox):
        ok, problems = checks.check_phase_1(fixtures.SLUG)
    return [Result("plan_written", True), Result("phase1_check_passes", ok, "; ".join(problems[:3]))]


def planner_axes_section(ctx: Ctx) -> list[Result]:
    """The `## Eixos` section the orchestrator splits phase 2 by: slugs, an organisation each, and consistent with the questions."""
    text = _plan(ctx)
    section = re.search(r"^## Eixos\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not section:
        return [Result("axes_section", False, "no `## Eixos` section")]
    entries = re.findall(r"^\s*[-*]\s*`([^`]+)`\s*(?:[-—–:]\s*)?(.*)$", section.group(1), re.MULTILINE)
    slugs = [e[0] for e in entries]
    problems = []
    if len(slugs) < 2:
        problems.append(f"only {len(slugs)} axis listed")
    problems += [f"'{s}' is not a lowercase-hyphen slug" for s in slugs if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", s)]
    problems += [f"axis '{s}' names no organisation" for s, org in entries if len(org.strip()) < 3]
    used = set(re.findall(r"[Ee]ixo[:*\s`]*\s*([a-z0-9-]+)", text[: section.start()]))
    problems += [f"questions use axis '{u}' that is not listed" for u in sorted(used - set(slugs))]
    problems += [f"axis '{s}' has no question" for s in slugs if s not in used]
    return [Result("axes_section", not problems, "; ".join(problems[:4]) if problems else f"{len(slugs)} axes: {', '.join(slugs)}")]


def planner_scope_and_decisions(ctx: Ctx) -> list[Result]:
    """Quality: the plan states a temporal and a geographic scope and records open decisions or scope exclusions."""
    text = _plan(ctx)
    temporal = bool(re.search(r"(19|20)\d{2}\s*(?:[-–]|a|até|to)\s*(19|20)\d{2}|desde\s+(19|20)\d{2}|since\s+(19|20)\d{2}", text))
    geographic = bool(re.search(r"Portugal", text)) and bool(re.search(r"NUTS|regi", text, re.IGNORECASE))
    decisions = bool(re.search(r"decis(?:ões|oes)\s+em\s+aberto|exclus(?:ões|oes)|fora\s+do\s+âmbito|open\s+decisions", text, re.IGNORECASE))
    missing = [name for name, ok in (("temporal scope", temporal), ("geographic scope", geographic), ("open decisions or exclusions", decisions)) if not ok]
    return [Result("scope_and_decisions", not missing, f"missing: {missing}" if missing else "", "quality")]


def planner_questions_answerable(ctx: Ctx) -> list[Result]:
    """Quality: questions are answerable with data, not opinions: each is a question, none is normative."""
    text = _plan(ctx)
    starts = [m.start() for m in re.finditer(r"^\s*\d{1,2}[.)]\s+", text, re.MULTILINE)]  # 1-2 digits: a wrapped "2017) ..." is not item 2017
    questions = [text[a:b].split("\n\n")[0] for a, b in zip(starts, [*starts[1:], len(text)], strict=True)]  # a question may span several lines
    normative = re.compile(r"\b(deveria|devia|dever[aá]|should|ideal(?:mente)?|melhor pol[ií]tica|na tua opini[aã]o)\b", re.IGNORECASE)
    bad = [q[:60] for q in questions if "?" not in q or normative.search(q)]
    return [Result("questions_answerable_with_data", not bad, f"not data questions: {bad[:3]}" if bad else f"{len(questions)} questions", "quality")]


# ---- data-researcher ---------------------------------------------------------------------------------------------

def _source_rows(ctx: Ctx, unit: str = "hospitalizacoes"):
    from common.schemas import DataSource

    path = ctx.study / "sources.d" / f"{unit}.csv"
    return read_csv(path, DataSource) if path.exists() else None


def _by_path(rows) -> dict[str, object]:
    return {re.sub(r"^https?://[^/]+", "", r.url): r for r in rows}


def researcher_registers_each_candidate_correctly(ctx: Ctx) -> list[Result]:
    """Four candidates, four right answers: the good one tested with its real licence; the dead one excluded for a definitive
    reason; the non-commercial one never tested with a permissive licence; the transient one left out, not excluded."""
    try:
        rows = _source_rows(ctx)
    except Exception as exc:
        return [Result("sources_file_parses", False, f"sources.d/hospitalizacoes.csv does not parse: {str(exc)[:200]}")]
    if rows is None:
        return [Result("sources_file_parses", False, "sources.d/hospitalizacoes.csv was not written")]
    by = _by_path(rows)
    out = [Result("sources_file_parses", True, f"{len(rows)} rows")]

    ok = by.get("/ok.csv")
    good = bool(ok and ok.status == "tested" and "cc by 4.0" in ok.license.lower().replace("-", " ").replace("_", " ") and "nc" not in ok.license.lower()
                and ok.format.lower() == "csv" and "2000" in ok.temporal_coverage and "2023" in ok.temporal_coverage)
    out.append(Result("good_source_tested_with_real_licence", good, f"got {ok}" if not good else f"{ok.id}: {ok.license} · {ok.temporal_coverage}"))

    dead = by.get("/missing.csv")
    dead_ok = bool(dead and dead.status == "excluded" and dead.exclusion_reason and not checks.TRANSIENT_REASON.search(dead.exclusion_reason))
    out.append(Result("dead_source_excluded_with_reason", dead_ok, "no row, or not excluded with a definitive reason" if not dead_ok else dead.exclusion_reason[:80]))

    nc = by.get("/nc.csv")
    nc_ok = nc is None or nc.status == "excluded" or "nc" in nc.license.lower().replace("-", " ").split()
    out.append(Result("non_commercial_source_not_passed_off", nc_ok, f"tested with licence '{nc.license}'" if not nc_ok else "excluded or honestly licensed"))

    flaky = by.get("/flaky.csv")
    out.append(Result("transient_failure_not_recorded", flaky is None, f"a row exists for the unavailable source ({flaky.status}: {flaky.exclusion_reason[:60]})" if flaky else "left out, as asked"))
    known = {"/ok.csv", "/missing.csv", "/nc.csv", "/flaky.csv", "/ok-license.html", "/nc-license.html"}
    invented = [p for p in by if p not in known]
    out.append(Result("no_invented_urls", not invented, f"URLs that were never offered: {invented}" if invented else ""))
    out.append(Result("transient_mentioned_in_summary", bool(re.search(r"transi|503|inacess|indispon|tempor|repet|retry", ctx.output, re.IGNORECASE)),
                      "the summary does not tell the orchestrator to retry the unavailable source", "quality"))
    return out


# ---- extractor ---------------------------------------------------------------------------------------------------

def extractor_output_correct(ctx: Ctx) -> list[Result]:
    """The parquet is canonical, holds exactly Portugal and the EU-27 (total sex) with readable labels, matches the source row by
    row (':' means missing and is dropped), and has provenance: a manifest entry whose hash matches a raw file the tool wrote."""
    from common.download import read_manifest, verify_manifest
    from common.normalize import CANONICAL_COLUMNS

    parquet = ctx.study / "data" / "clean" / "s1.parquet"
    if not parquet.exists():
        return [Result("clean_parquet_written", False, "data/clean/s1.parquet was not written")]
    df = pd.read_parquet(parquet)
    out = [Result("clean_parquet_written", True, f"{len(df)} rows"),
           Result("canonical_columns", list(df.columns) == CANONICAL_COLUMNS, f"columns: {list(df.columns)}" if list(df.columns) != CANONICAL_COLUMNS else "")]
    got = {(r.region, int(str(r.date)[:4])): round(float(r.value), 1) for r in df.itertuples() if r.sex in ("T", "")}
    truth = fixtures.EXTRACTOR_TRUTH
    wrong = {k: (got.get(k), v) for k, v in truth.items() if got.get(k) != round(v, 1)}
    extra = sorted(set(got) - set(truth))
    out.append(Result("values_match_the_source", not wrong, f"{len(wrong)} wrong or missing (first: {dict(list(wrong.items())[:2])})" if wrong else f"{len(truth)} values match, 2022 gap dropped"))
    out.append(Result("only_the_requested_rows", not extra and set(df["sex"].astype(str)) <= {"T", ""}, f"unexpected rows: {extra[:3]}; sexes: {sorted(set(df['sex'].astype(str)))}" if extra or not set(df["sex"].astype(str)) <= {"T", ""} else ""))
    labels = set(df["region"])
    out.append(Result("readable_labels", labels == {"Portugal", "European Union (27)"}, f"regions: {sorted(labels)}", "quality"))
    entries = [e for e in read_manifest(ctx.study) if e.file.startswith("s1")]
    problems = [p for p in verify_manifest(ctx.study) if "s1" in p]
    served_by_tool = bool(entries) and all(f"127.0.0.1:{ctx.params['port']}" in e.url for e in entries)
    out.append(Result("provenance_recorded", bool(entries) and not problems and served_by_tool,
                      "no manifest entry, a hash mismatch, or a raw file not downloaded from the source URL" if not (entries and not problems and served_by_tool) else f"{entries[0].file}, hash verified"))
    spec = (ctx.study / "data" / "extract" / "s1.json").exists() or (ctx.study / "data" / "extract" / "s1.py").exists()
    out.append(Result("spec_kept", spec, "no data/extract/s1.json or s1.py", "quality"))
    return out


# ---- analyst -----------------------------------------------------------------------------------------------------

def analyst_phase4_passes(ctx: Ctx) -> list[Result]:
    """The platform's phase 4 check: charts registered with a valid kind and why, canonical keys with source_id, breaks written."""
    if not (ctx.study / "analysis" / "charts.yml").exists() or not (ctx.study / "breaks.csv").exists():
        return [Result("phase4_check_passes", False, "charts.yml or breaks.csv was not written")]
    with sandbox_paths(ctx.sandbox):
        ok, problems = checks.check_phase_4(fixtures.SLUG)
    return [Result("phase4_check_passes", ok, "; ".join(problems[:4]) + (f" (+{len(problems) - 4} more)" if len(problems) > 4 else ""))]


def analyst_breaks_found(ctx: Ctx) -> list[Result]:
    """Recall of the three planted breaks (level 2012 and spike 2020 in the first series, level 2011 in the second, within one
    year) and no flood of near-duplicate breaks (the agent is told to tune the penalties, not to record dozens)."""
    path = ctx.study / "breaks.csv"
    breaks = read_csv(path, Break) if path.exists() else []
    missed = []
    for name, (keywords, year) in fixtures.ANALYST_TRUTH.items():
        hit = any(abs(b.date.year - year) <= 1 and any(k in f"{b.series} {b.axis}".lower() for k in keywords) for b in breaks)
        if not hit:
            missed.append(f"{name} ({year})")
    limit = 12
    return [Result("planted_breaks_recorded", not missed, f"missed: {missed}" if missed else f"all 3 found among {len(breaks)} breaks"),
            Result("no_flood_of_breaks", len(breaks) <= limit, f"{len(breaks)} breaks recorded (limit {limit})", "quality")]


def analyst_scripts_reproduce_the_charts(ctx: Ctx) -> list[Result]:
    """Principle 6: charts come from code. Every analysis script runs cleanly and regenerates byte-identical chart JSON; no notebooks."""
    import hashlib
    import os
    import subprocess
    import sys

    analysis = ctx.study / "analysis"
    scripts = sorted(p for p in analysis.glob("*.py") if not p.name.startswith("_"))
    notebooks = list(analysis.glob("*.ipynb"))
    if not scripts:
        return [Result("scripts_reproduce_charts", False, "no analysis/*.py script")]
    digest = lambda: {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((analysis / "out").glob("*.json"))}
    before = digest()
    env = {**os.environ, "PYTHONPATH": "."}
    failures = []
    for script in scripts:
        run = subprocess.run([sys.executable, str(script)], cwd=ctx.sandbox, env=env, capture_output=True, text=True, timeout=180)
        if run.returncode != 0:
            failures.append(f"{script.name}: {run.stderr.strip().splitlines()[-1][:100] if run.stderr.strip() else run.returncode}")
    changed = sorted(k for k, v in digest().items() if before.get(k) != v)
    problems = failures + ([f"outputs differ on rerun: {changed}"] if changed else []) + ([f"notebooks: {[n.name for n in notebooks]}"] if notebooks else [])
    return [Result("scripts_reproduce_charts", not problems, "; ".join(problems[:3]) if problems else f"{len(scripts)} script(s) rerun, charts identical")]


def analyst_charts_trace_to_clean_data(ctx: Ctx) -> list[Result]:
    """Quality: at least 80% of the plotted points exist in data/clean for their source_id (derived series are allowed, invented ones are not)."""
    import json

    total = matched = 0
    for path in sorted((ctx.study / "analysis" / "out").glob("*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        clean: dict[str, set] = {}
        for row in rows:
            sid = row.get("source_id", "")
            if sid not in clean:
                parquet = ctx.study / "data" / "clean" / f"{sid}.parquet"
                clean[sid] = {(str(d)[:10], round(float(v), 1)) for d, v in pd.read_parquet(parquet, columns=["date", "value"]).itertuples(index=False)} if parquet.exists() else set()
            total += 1
            matched += (str(row.get("date"))[:10], round(float(row.get("value", 0)), 1)) in clean[sid]
    share = matched / total if total else 0.0
    return [Result("charts_trace_to_clean_data", share >= 0.8, f"{matched}/{total} plotted points found in data/clean", "quality")]


# ---- verifier ----------------------------------------------------------------------------------------------------

def verifier_detects_faults(ctx: Ctx) -> list[Result]:
    """Fault injection: claims with a wrong excerpt, a dead URL or the wrong page must end `failed`; intact ones `confirmed`."""
    truth = ctx.params["faulty_ids"]
    claims = {c.id: c.verification_status for c in read_csv(ctx.study / "claims.csv", Claim)}
    faulty = [c for c in claims if c in truth]
    intact = [c for c in claims if c not in truth]
    caught = [c for c in faulty if claims[c] == "failed"]
    false_alarms = [c for c in intact if claims[c] == "failed"]
    undecided = [c for c in claims if claims[c] == "pending"]
    recall = len(caught) / len(faulty) if faulty else 1.0
    return [
        Result("fault_recall", recall == 1.0, f"caught {len(caught)}/{len(faulty)} injected faults (missed: {sorted(set(faulty) - set(caught))})"),
        Result("no_false_alarms", not false_alarms, f"intact claims wrongly failed: {false_alarms}" if false_alarms else f"{len(intact)} intact claims confirmed or left alone", "critical"),
        Result("none_left_pending", not undecided, f"still pending: {undecided}" if undecided else "", "quality"),
    ]


def verifier_does_not_touch_the_text(ctx: Ctx) -> list[Result]:
    """The verifier changes only verification_status in claims.csv; the report text and every other column are untouched."""
    changed = [p for p in ctx.changed() if p.endswith((".qmd",))]
    before_cols = ctx.params.get("claims_before")
    modified = []
    if before_cols is not None:
        now = pd.read_csv(ctx.study / "claims.csv", dtype=str, keep_default_na=False).drop(columns="verification_status")
        was = pd.DataFrame(before_cols).drop(columns="verification_status")
        modified = [c for c in was.columns if not now[c].equals(was[c])]
    return [Result("only_status_changes", not changed and not modified, f"reports changed: {changed}; columns changed: {modified}" if changed or modified else "")]


GRADERS = {
    "writes_only_own_files": writes_only_own_files,
    "not_published": not_published,
    "historian_links_valid": historian_links_valid,
    "historian_no_overclaiming": historian_no_overclaiming,
    "historian_window_and_far_events": historian_window_and_far_events,
    "historian_positive_control": historian_positive_control,
    "writer_numbers_traceable": writer_numbers_traceable,
    "writer_phase6_checks": writer_phase6_checks,
    "writer_urls_not_invented": writer_urls_not_invented,
    "writer_bilingual_parity": writer_bilingual_parity,
    "writer_causal_wording": writer_uses_causal_wording_correctly,
    "writer_covers_inputs": writer_covers_inputs,
    "writer_en_unit_discipline": writer_en_unit_discipline,
    "summary_short": summary_short,
    "planner_plan_valid": planner_plan_valid,
    "planner_axes_section": planner_axes_section,
    "planner_scope_and_decisions": planner_scope_and_decisions,
    "planner_questions_answerable": planner_questions_answerable,
    "researcher_registers_each_candidate_correctly": researcher_registers_each_candidate_correctly,
    "extractor_output_correct": extractor_output_correct,
    "analyst_phase4_passes": analyst_phase4_passes,
    "analyst_breaks_found": analyst_breaks_found,
    "analyst_scripts_reproduce_the_charts": analyst_scripts_reproduce_the_charts,
    "analyst_charts_trace_to_clean_data": analyst_charts_trace_to_clean_data,
    "verifier_detects_faults": verifier_detects_faults,
    "verifier_does_not_touch_the_text": verifier_does_not_touch_the_text,
}


def grade(names: list[str], ctx: Ctx) -> list[Result]:
    results: list[Result] = []
    for name in names:
        try:
            results += GRADERS[name](ctx)
        except Exception as exc:  # a grader crash is a failed grade (the output was unusable), not a crashed eval
            results.append(Result(name, False, f"grader error: {type(exc).__name__}: {exc}"))
    return results


__all__ = ["GRADERS", "Ctx", "Result", "date", "grade"]
