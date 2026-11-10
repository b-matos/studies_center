"""Decisions that stop a study for the user: read pending.md, record the answer, resume.

When the pipeline reaches a decision that is the user's (an axis with no data, a change of
scope), the orchestrator cannot ask in a headless run. It writes studies/<slug>/pending.md
and stops; the queue shows the item as "needs you" with that text and its numbered options.
Answering appends to studies/<slug>/decisions.md, archives pending.md and resumes the run;
the study skill reads decisions.md first and never asks again about what is decided there.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from common.checks import STUDIES_ROOT

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
OPTION = re.compile(r"^\s*(\d+)[.)]\s+(.+)$", re.MULTILINE)
MAX_ANSWER = 2000


class DecisionError(Exception):
    pass


def _study(slug: str | None) -> Path:
    if not slug or not SLUG.fullmatch(slug):
        raise DecisionError("invalid study slug")
    return STUDIES_ROOT / slug


def read_question(slug: str | None) -> dict | None:
    """The pending decision of a study: its text and the numbered options found in it."""
    try:
        path = _study(slug) / "pending.md"
    except DecisionError:
        return None
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")[:4000]
    options = [{"n": int(n), "text": re.sub(r"[*`]", "", t)[:160]} for n, t in OPTION.findall(text)]
    return {"text": text, "options": options}


def record_answer(slug: str | None, answer: str) -> None:
    """Append the answer to decisions.md and archive pending.md so the study can resume."""
    study_dir = _study(slug)
    answer = answer.strip()
    if not answer:
        raise DecisionError("empty answer")
    if len(answer) > MAX_ANSWER:
        raise DecisionError(f"answer longer than {MAX_ANSWER} characters")
    pending = study_dir / "pending.md"
    if not pending.exists():
        raise DecisionError("this study has no pending decision")
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    decisions = study_dir / "decisions.md"
    header = "" if decisions.exists() else "# Decisões do utilizador\n"
    with decisions.open("a", encoding="utf-8") as f:
        f.write(f"{header}\n## {stamp}\n\nPergunta (resumo): {pending.read_text(encoding='utf-8').splitlines()[0][:200]}\n\n"
                f"Resposta do utilizador: {answer}\n")
    pending.rename(study_dir / f"pending.resolved-{stamp.replace(':', '')}.md")
    study_yml = study_dir / "study.yml"
    if study_yml.exists():
        meta = yaml.safe_load(study_yml.read_text(encoding="utf-8")) or {}
        if meta.get("status") == "pending_decision":
            meta["status"] = "in_progress"
            study_yml.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
