"""Compare eval batches: did a prompt or model change help?

    uv run python -m evals.report                 # the last two batches of every agent
    uv run python -m evals.report --agent writer

Rows are grouped by (agent, case, grader); the table shows the pass rate of the earlier and the latest batch, the change,
and the cost per run. A drop in a `critical` grader is a regression; read it before reading anything else.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

RUNS_CSV = Path(__file__).resolve().parent / "results" / "runs.csv"


def load(path: Path = RUNS_CSV) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def batches(rows: list[dict], agent: str) -> list[str]:
    return sorted({r["batch"] for r in rows if r["agent"] == agent and not r["batch"].endswith("-dry")})


def invalid_runs(rows: list[dict]) -> set[tuple[str, str, str, str]]:
    """Runs that never completed (the `claude` process crashed or timed out): infrastructure, not evidence about the agent."""
    return {(r["batch"], r["agent"], r["case"], r["run"]) for r in rows if r["grader"] == "run_completed" and not int(r["passed"])}


def pass_rates(rows: list[dict], agent: str, batch: str) -> dict[tuple[str, str], tuple[float, int, str]]:
    """(case, grader) -> (pass rate, valid runs, severity) for one batch; crashed runs are left out."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    bad = invalid_runs(rows)
    for r in rows:
        if r["agent"] == agent and r["batch"] == batch and (r["batch"], r["agent"], r["case"], r["run"]) not in bad and r["grader"] != "run_completed":
            groups[(r["case"], r["grader"])].append(r)
    return {k: (sum(int(x["passed"]) for x in v) / len(v), len(v), v[0]["severity"]) for k, v in groups.items()}


def run_cost(rows: list[dict], agent: str, batch: str) -> float:
    per_run: dict[tuple[str, str], float] = {}
    bad = invalid_runs(rows)
    for r in rows:
        if r["agent"] == agent and r["batch"] == batch and (r["batch"], r["agent"], r["case"], r["run"]) not in bad:
            per_run[(r["case"], r["run"])] = float(r["cost_usd"])
    return sum(per_run.values()) / len(per_run) if per_run else 0.0


def compare(rows: list[dict], agent: str) -> list[str]:
    found = batches(rows, agent)
    if not found:
        return [f"{agent}: no runs yet"]
    latest, earlier = found[-1], (found[-2] if len(found) > 1 else None)
    new = pass_rates(rows, agent, latest)
    old = pass_rates(rows, agent, earlier) if earlier else {}
    lines = [f"{agent}: latest batch {latest}" + (f" vs {earlier}" if earlier else " (no earlier batch to compare)"),
             f"  cost per run: ${run_cost(rows, agent, latest):.2f}" + (f" (was ${run_cost(rows, agent, earlier):.2f})" if earlier else "")]
    for (case, grader), (rate, n, severity) in sorted(new.items()):
        was = old.get((case, grader))
        delta = "" if was is None else (f"  {'REGRESSION' if rate < was[0] else 'improved' if rate > was[0] else 'same'} (was {was[0]:.0%})")
        lines.append(f"  {case:<22} {grader:<34} {rate:>4.0%} of {n}  [{severity}]{delta}")
    return lines


def compare_models(rows: list[dict], agent: str) -> list[str]:
    """Latest batch of each model side by side: did a cheaper model lose quality?"""
    latest: dict[str, str] = {}
    for r in sorted((r for r in rows if r["agent"] == agent and not r["batch"].endswith("-dry")), key=lambda r: r["batch"]):
        latest[r["model"]] = r["batch"]
    if len(latest) < 2:
        return [f"{agent}: need runs with at least two models to compare (have: {', '.join(latest) or 'none'})"]
    tables = {m: pass_rates(rows, agent, b) for m, b in latest.items()}
    models = sorted(latest)
    crashed = {m: sum(1 for k in invalid_runs(rows) if k[0] == b and k[1] == agent) for m, b in latest.items()}
    lines = [f"{agent}: latest batch per model" + "".join(f" · {m}: {n} crashed run(s) left out" for m, n in crashed.items() if n), "  cost per run: " + " | ".join(f"{m} ${run_cost(rows, agent, latest[m]):.2f}" for m in models),
             f"  {'case':<18}{'grader':<34}" + "".join(f"{m:>14}" for m in models)]
    for key in sorted(set().union(*tables.values())):
        cells = "".join(f"{(f'{t[key][0]:.0%} of {t[key][1]}' if key in t else '-'):>14}" for t in (tables[m] for m in models))
        severity = next(t[key][2] for t in tables.values() if key in t)
        lines.append(f"  {key[0]:<18}{key[1]:<34}{cells}  [{severity}]")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent")
    parser.add_argument("--models", action="store_true", help="compare the latest batch of each model instead of the last two batches")
    args = parser.parse_args(argv)
    rows = load()
    agents = [args.agent] if args.agent else sorted({r["agent"] for r in rows})
    if not agents:
        print("no results yet: run `uv run python -m evals.run <agent>`")
        return 0
    for agent in agents:
        print("\n".join(compare_models(rows, agent) if args.models else compare(rows, agent)), end="\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
