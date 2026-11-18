"""Run agent evals: build a sandbox from a synthetic fixture, run one agent headlessly, grade the result by code.

    uv run python -m evals.run historian                    # every case of an agent, once
    uv run python -m evals.run writer --case write_pt_en --n 3
    uv run python -m evals.run historian --dry-run          # build the sandbox and grade it untouched: a smoke test, no tokens
    uv run python -m evals.report                           # compare the last two batches

Each run appends one row per grader to `evals/results/runs.csv` (commit it: it is the history that tells you whether a prompt
or model change helped), and keeps the raw stream in `evals/results/logs/` (git-ignored). Each case is repeated `--n` times
because agents vary; read the pass rate and the worst case, not one run.
"""
from __future__ import annotations

import argparse
import csv
import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from evals import graders, sandbox

REPO = Path(__file__).resolve().parent.parent
CASES_DIR = REPO / "evals" / "cases"
RESULTS = REPO / "evals" / "results"
RUNS_CSV = RESULTS / "runs.csv"
LOGS = RESULTS / "logs"
COLUMNS = ["batch", "timestamp", "git_sha", "agent", "case", "run", "model", "grader", "passed", "severity", "detail", "cost_usd", "tokens", "duration_s"]


def agent_command(agent: str, case: dict, prompt: str, model: str | None) -> list[str]:
    """The headless `claude` invocation for one run. The agent is the session's agent, so its own prompt and tools apply."""
    cmd = ["claude", "-p", prompt, "--agent", agent, "--output-format", "stream-json", "--verbose",
           "--permission-mode", "dontAsk", "--permission-prompts", "none"]
    if model:
        cmd += ["--model", model]
    allowed = [*case.get("tools", []), *(["Bash(uv run *)"] if case.get("bash", True) else [])]
    cmd += ["--allowedTools", ",".join(allowed)]
    if case.get("deny"):
        cmd += ["--disallowedTools", ",".join(case["deny"])]
    return cmd


def parse_stream(text: str) -> dict:
    """cost, tokens and the final message from a stream-json log."""
    out = {"cost_usd": 0.0, "tokens": 0, "output": "", "turns": 0}
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            usage = event.get("usage", {})
            out.update(cost_usd=float(event.get("total_cost_usd") or 0), output=str(event.get("result") or ""), turns=int(event.get("num_turns") or 0),
                       tokens=sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")))
    return out


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def append_rows(rows: list[dict]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    new = not RUNS_CSV.exists()
    with RUNS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            writer.writeheader()
        writer.writerows(rows)


class LocalSite:
    """Serve a directory of fixture pages on a free local port for the duration of a case."""

    def __init__(self, directory: Path) -> None:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


def run_case(agent: str, case: dict, *, run_index: int, batch: str, model: str | None, dry_run: bool, keep: bool) -> list[dict]:
    site = LocalSite(sandbox.write_pages(Path(sandbox.tempfile.mkdtemp(prefix="eval-pages-")))) if case.get("serve") else None
    port = site.port if site else None
    root, params = sandbox.make_sandbox(case, port=port)
    before = sandbox.snapshot(root)
    prompt = case["prompt"].replace("{port}", str(port or ""))
    cmd = agent_command(agent, case, prompt, model)
    cost = tokens = 0
    output, started = "", time.time()
    note = ""
    try:
        if dry_run:
            print(f"  [dry-run] {' '.join(cmd[:4])} ... --agent {agent} (sandbox {root})")
        else:
            LOGS.mkdir(parents=True, exist_ok=True)
            log = LOGS / f"{batch}_{agent}_{case['id']}_{run_index}.jsonl"
            env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(REPO / ".venv")}
            try:
                for attempt in (1, 2):  # a `claude` process that dies before it answers is retried once (infrastructure, not the agent)
                    done = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=case.get("timeout", 900))
                    log.write_text(done.stdout, encoding="utf-8")
                    parsed = parse_stream(done.stdout)
                    if done.returncode == 0 or parsed["output"]:
                        break
                    shutil.rmtree(root, ignore_errors=True)  # start the retry from a clean sandbox
                    root, params = sandbox.make_sandbox(case, port=port)
                    before = sandbox.snapshot(root)
                cost, tokens, output = parsed["cost_usd"], parsed["tokens"], parsed["output"]
                if done.returncode != 0:
                    note = f"claude exited with {done.returncode}: {done.stderr.strip()[-200:]}"
            except subprocess.TimeoutExpired:
                note = f"timeout after {case.get('timeout', 900)}s"
        ctx = graders.Ctx(sandbox=root, agent=agent, before=before, after=sandbox.snapshot(root), output=output, params=params)
        results = graders.grade(case["graders"], ctx)
        if note:
            results.append(graders.Result("run_completed", False, note))
    finally:
        if site:
            site.close()
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    stamp, sha = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), git_sha()
    return [{"batch": batch, "timestamp": stamp, "git_sha": sha, "agent": agent, "case": case["id"], "run": run_index, "model": model or "default",
             "grader": r.name, "passed": int(r.passed), "severity": r.severity, "detail": r.detail, "cost_usd": round(cost, 4), "tokens": tokens,
             "duration_s": round(time.time() - started)} for r in results]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("agent", choices=sorted(p.stem for p in CASES_DIR.glob("*.yaml")))
    parser.add_argument("--case", help="only this case id")
    parser.add_argument("--n", type=int, default=1, help="repeat each case n times")
    parser.add_argument("--model", help="override the agent's model (for example sonnet or opus)")
    parser.add_argument("--dry-run", action="store_true", help="build and grade the sandbox without running the agent")
    parser.add_argument("--keep", action="store_true", help="keep the sandboxes for inspection")
    args = parser.parse_args(argv)

    cases = [c for c in sandbox.load_cases(CASES_DIR / f"{args.agent}.yaml") if not args.case or c["id"] == args.case]
    if not cases:
        print(f"no case '{args.case}' for {args.agent}", file=sys.stderr)
        return 2
    batch = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ("-dry" if args.dry_run else "")
    rows: list[dict] = []
    for case in cases:
        for i in range(1, args.n + 1):
            print(f"{args.agent}/{case['id']} run {i}/{args.n}")
            rows += (new := run_case(args.agent, case, run_index=i, batch=batch, model=args.model, dry_run=args.dry_run, keep=args.keep))
            for r in new:
                print(f"  {'PASS' if r['passed'] else 'FAIL'} [{r['severity']}] {r['grader']}: {r['detail'][:110]}")
            print(f"  cost ${new[0]['cost_usd']} · {new[0]['tokens']:,} tokens · {new[0]['duration_s']}s")
    if not args.dry_run:
        append_rows(rows)
        print(f"\nappended {len(rows)} rows to {RUNS_CSV.relative_to(REPO)} (batch {batch})")
    critical = [r for r in rows if not r["passed"] and r["severity"] == "critical"]
    return 1 if critical and not args.dry_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
