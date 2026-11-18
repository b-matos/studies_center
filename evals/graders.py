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
