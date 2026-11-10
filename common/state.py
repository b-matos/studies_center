"""Resumable pipeline state for one study (studies/<slug>/state.json, schema v2).

The orchestrating session is the single writer of state.json (subagents are blocked from
it by .claude/hooks/guard_writes.py). Every write is atomic (temp file + os.replace), so a
session killed by the token limit can never leave a half-written file behind.

State is tracked per phase and, inside a phase, per unit of work (an axis, a source, a
language, a claim), so an interrupted run loses at most the unit that was in flight.

CLI (all commands print a short result; exit 1 when the command refuses):

    uv run python -m common.state init <slug>
    uv run python -m common.state resume <slug>
    uv run python -m common.state start-phase <slug> <phase>
    uv run python -m common.state plan-units <slug> <phase> <unit> [<unit> ...]
    uv run python -m common.state unit-start <slug> <phase> <unit>
    uv run python -m common.state unit-done <slug> <phase> <unit>
    uv run python -m common.state complete-phase <slug> <phase>   # merges + runs the phase check
    uv run python -m common.state fail-attempt <slug> <phase> <problems-file>
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from common.checks import CHECKS, STUDIES_ROOT
from common.csv_io import read_csv, write_csv
from common.download import read_manifest, verify_manifest
from common.normalize import CANONICAL_COLUMNS
from common.schemas import Claim, DataSource

SCHEMA_VERSION = 2
MAX_ATTEMPTS = 3
PHASE_NAMES = {
    1: "plan", 2: "sources", 3: "extraction", 4: "analysis",
    5: "events", 6: "writing", 7: "verification", 8: "publication",
}
UNIT_STATES = ("pending", "in_progress", "done")


class StateError(Exception):
    """A state command was refused (bad phase, unit not really done, attempts exhausted...)."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def state_path(slug: str) -> Path:
    return STUDIES_ROOT / slug / "state.json"


def _empty_state() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "current_phase": 1,
        "completed_phases": [],
        "phases": {},
        "updated_at": _now(),
    }


def load(slug: str) -> dict:
    path = state_path(slug)
    if not path.exists():
        return _empty_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != SCHEMA_VERSION:
        raise StateError(f"{path} is not schema v{SCHEMA_VERSION}; run scripts/migrate_v1_names.py")
    return state


def save(slug: str, state: dict) -> None:
    """Atomic write: a crash mid-write leaves the previous state.json intact."""
    path = state_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _phase(state: dict, phase: int) -> dict:
    if phase not in PHASE_NAMES:
        raise StateError(f"invalid phase {phase} (must be 1-8)")
    return state["phases"].setdefault(
        str(phase), {"status": "pending", "attempts": 0, "units": {}, "last_problems": []}
    )


def init(slug: str) -> dict:
    if state_path(slug).exists():
        return load(slug)
    state = _empty_state()
    save(slug, state)
    return state


def start_phase(slug: str, phase: int) -> dict:
    state = load(slug)
    p = _phase(state, phase)
    if p["status"] == "blocked":
        raise StateError(f"phase {phase} is blocked after {p['attempts']} attempts; see pending.md")
    if phase in state["completed_phases"]:
        raise StateError(f"phase {phase} is already completed")
    p["status"] = "in_progress"
    p.setdefault("started_at", _now())
    state["current_phase"] = phase
    save(slug, state)
    return state


def plan_units(slug: str, phase: int, units: list[str]) -> dict:
    """Register the units of a phase. Already-known units keep their state (resume-safe)."""
    state = load(slug)
    p = _phase(state, phase)
    for u in units:
        p["units"].setdefault(u, "pending")
    save(slug, state)
    return state


def unit_start(slug: str, phase: int, unit: str) -> dict:
    state = load(slug)
    p = _phase(state, phase)
    if unit not in p["units"]:
        raise StateError(f"unit '{unit}' is not planned for phase {phase}")
    if p["units"][unit] != "done":
        p["units"][unit] = "in_progress"
    save(slug, state)
    return state


def _validate_unit(slug: str, phase: int, unit: str) -> list[str]:
    """Code-level proof that a unit is really done; never the agent's own claim."""
    study_dir = STUDIES_ROOT / slug
    if phase == 2:
        path = study_dir / "sources.d" / f"{unit}.csv"
        if not path.exists():
            return [f"sources.d/{unit}.csv does not exist"]
        try:
            if not read_csv(path, DataSource):
                return [f"sources.d/{unit}.csv has no rows"]
        except Exception as exc:
            return [f"sources.d/{unit}.csv is invalid: {exc}"]
    elif phase == 3:
        parquet = study_dir / "data" / "clean" / f"{unit}.parquet"
        if not parquet.exists():
            return [f"data/clean/{unit}.parquet does not exist"]
        columns = list(pd.read_parquet(parquet).columns)
        if columns != CANONICAL_COLUMNS:
            return [f"data/clean/{unit}.parquet columns {columns} != canonical {CANONICAL_COLUMNS}"]
        entries = [e for e in read_manifest(study_dir) if e.file == unit or e.file.startswith(f"{unit}_")]
        if not entries:
            return [f"no raw_manifest.csv entry for source {unit}"]
        mine = {e.file for e in entries}
        return [p for p in verify_manifest(study_dir) if any(f in p for f in mine)]
    elif phase == 6:
        report = study_dir / f"report.{unit}.qmd"
        if not report.exists() or len(report.read_text(encoding="utf-8").strip()) < 200:
            return [f"report.{unit}.qmd is missing or nearly empty"]
    elif phase == 7:
        claims = {c.id: c for c in read_csv(study_dir / "claims.csv", Claim)}
        if unit not in claims or claims[unit].verification_status == "pending":
            return [f"claim {unit} still has verification_status=pending"]
    return []


def unit_done(slug: str, phase: int, unit: str) -> dict:
    state = load(slug)
    p = _phase(state, phase)
    if unit not in p["units"]:
        raise StateError(f"unit '{unit}' is not planned for phase {phase}")
    problems = _validate_unit(slug, phase, unit)
    if problems:
        raise StateError(f"unit '{unit}' is not done: " + "; ".join(problems))
    p["units"][unit] = "done"
    save(slug, state)
    return state


def fail_attempt(slug: str, phase: int, problems: list[str]) -> dict:
    state = load(slug)
    p = _phase(state, phase)
    p["attempts"] += 1
    p["last_problems"] = problems[:20]
    if p["attempts"] >= MAX_ATTEMPTS:
        p["status"] = "blocked"
    save(slug, state)
    return state


def merge_sources(slug: str) -> int:
    """Phase 2: merge sources.d/<axis>.csv (one per data-researcher) into sources.csv."""
    study_dir = STUDIES_ROOT / slug
    rows: list[DataSource] = []
    seen: set[str] = set()
    for path in sorted((study_dir / "sources.d").glob("*.csv")):
        for row in read_csv(path, DataSource):
            if row.id in seen:
                raise StateError(f"duplicate source id {row.id} in {path.name}")
            seen.add(row.id)
            rows.append(row)
    write_csv(study_dir / "sources.csv", DataSource, rows)
    return len(rows)


def complete_phase(slug: str, phase: int) -> tuple[bool, list[str]]:
    """Run the phase's code check; mark it completed or spend one attempt."""
    state = load(slug)
    p = _phase(state, phase)
    pending = [u for u, s in p["units"].items() if s != "done"]
    if pending:
        problems = [f"units not done: {', '.join(pending)}"]
        fail_attempt(slug, phase, problems)
        return False, problems
    if phase == 2:
        merge_sources(slug)
    ok, problems = CHECKS[phase](slug)
    state = load(slug)
    if not ok:
        fail_attempt(slug, phase, problems)
        return False, problems
    p = _phase(state, phase)
    p["status"] = "completed"
    p["last_problems"] = []
    p["completed_at"] = _now()
    if phase not in state["completed_phases"]:
        state["completed_phases"] = sorted([*state["completed_phases"], phase])
    state["current_phase"] = min(phase + 1, 8)
    save(slug, state)
    return True, []


def resume(slug: str) -> str:
    """Short report of where to continue. Interrupted units are reset to 'pending'."""
    if not state_path(slug).exists():
        return f"no state for '{slug}': run `uv run python -m common.state init {slug}` (new study)"
    state = load(slug)
    done = state["completed_phases"]
    if len(done) == 8:
        return f"study '{slug}': all 8 phases completed; nothing to resume"
    phase = next(n for n in range(1, 9) if n not in done)
    p = _phase(state, phase)
    redo = [u for u, s in p["units"].items() if s == "in_progress"]
    for u in redo:
        p["units"][u] = "pending"  # partial output of an interrupted unit is discarded and redone
    if redo:
        save(slug, state)
    todo = [u for u, s in p["units"].items() if s != "done"]
    lines = [
        f"study: {slug} | next phase: {phase} ({PHASE_NAMES[phase]}) | status: {p['status']}",
        f"completed phases: {done or 'none'} | attempts used in phase {phase}: {p['attempts']}/{MAX_ATTEMPTS}",
    ]
    if p["status"] == "blocked":
        lines.append("BLOCKED: attempts exhausted; read pending.md, do not retry without the user")
    if p["units"]:
        lines.append(f"units done: {[u for u, s in p['units'].items() if s == 'done'] or 'none'}")
        lines.append(f"units to do: {todo or 'none (run complete-phase)'}")
        if redo:
            lines.append(f"interrupted, redo from scratch: {redo}")
    else:
        lines.append("units: not planned yet")
    for problem in p["last_problems"][:5]:
        lines.append(f"last problem: {problem}")
    return "\n".join(lines[:10])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, slug, rest = args[0], args[1], args[2:]
    try:
        if cmd == "init":
            init(slug)
            print(f"state ready for '{slug}'")
        elif cmd == "resume":
            print(resume(slug))
        elif cmd == "start-phase":
            start_phase(slug, int(rest[0]))
            print(f"phase {rest[0]} started")
        elif cmd == "plan-units":
            plan_units(slug, int(rest[0]), rest[1:])
            print(f"planned {len(rest) - 1} unit(s) for phase {rest[0]}")
        elif cmd == "unit-start":
            unit_start(slug, int(rest[0]), rest[1])
            print(f"unit {rest[1]} started")
        elif cmd == "unit-done":
            unit_done(slug, int(rest[0]), rest[1])
            print(f"unit {rest[1]} done")
        elif cmd == "fail-attempt":
            problems = Path(rest[1]).read_text(encoding="utf-8").splitlines()
            state = fail_attempt(slug, int(rest[0]), [x for x in problems if x.strip()])
            print(f"attempt recorded: {state['phases'][rest[0]]['attempts']}/{MAX_ATTEMPTS}")
        elif cmd == "complete-phase":
            ok, problems = complete_phase(slug, int(rest[0]))
            if not ok:
                print(f"[FAILED] phase {rest[0]} of '{slug}':")
                for p in problems:
                    print(f"  - {p}")
                return 1
            print(f"[OK] phase {rest[0]} of '{slug}' completed")
        else:
            print(f"unknown command: {cmd}", file=sys.stderr)
            return 2
    except StateError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    except (IndexError, ValueError):
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
