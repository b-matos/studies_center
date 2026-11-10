"""Launch Claude Code headlessly for one /study run and report what it is doing.

Uses asyncio.create_subprocess_exec with an argument list — never a shell string — so the
(already-validated) topic can never be interpreted by a shell. Every stream-json line goes to
a per-run log file and to a `UsageTracker`, which turns it into three kinds of UI events:

- `activity`: one short line with what Claude is doing right now;
- `progress`: the per-phase picture read from studies/<slug>/state.json;
- `plan_usage`: the plan's 5-hour / 7-day utilisation from rate_limit_event.

When the run ends, tokens and cost are saved to studies/<slug>/usage.csv and logs/runs.csv.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from common import state
from common.usage import UsageTracker, append_rows

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"

# The orchestrator only dispatches subagents and runs commands, so the cheaper model is enough.
ORCHESTRATOR_MODEL = "sonnet"

ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "Agent",
    "Skill",
    "Bash(uv run *)",
    "Bash(git add *)",
    "Bash(git commit *)",
    "Bash(quarto render *)",
]

OnEvent = Callable[[dict], Awaitable[None]]

# `claude -p` stops waiting for background subagents 10 minutes after the orchestrator's last
# turn and kills them. Data-gathering phases routinely take longer, so wait up to one hour.
BG_WAIT_CEILING_MS = "3600000"
BG_WAIT_MESSAGE = "Background tasks still running"

LIMIT_PATTERN = re.compile(r"usage limit|limit reached|rate.?limit|429|overloaded|quota", re.IGNORECASE)
RUNS_HEADER = "timestamp,topic,slug,status,input_tokens,output_tokens,cost_usd"
LIMIT_MESSAGE = (
    "Limite do plano atingido. O progresso está guardado em studies/<slug>/state.json: "
    "quando o limite renovar, volta a executar este estudo na fila e continua de onde parou."
)


@dataclass
class RunResult:
    """status: done (all 8 phases completed) | interrupted (plan limit) | needs_you | failed."""

    returncode: int
    status: str
    note: str
    slug: str | None
    resets_at: int | None
    cost_usd: float
    tokens: int


def _denials(result_event: dict) -> str:
    denied = result_event.get("permission_denials") or []
    if not denied:
        return ""
    command = str((denied[0].get("tool_input") or {}).get("command", ""))[:80]
    return f"{len(denied)} pedido(s) recusado(s) em modo headless (ex.: {denied[0].get('tool_name')}: {command})"


def _outcome(returncode: int, interrupted: bool, result_event: dict, slug: str | None, stderr: str) -> tuple[str, str]:
    """Success is judged on the study (all 8 phases completed in state.json), not on the exit code.

    The note names the real cause first; refused commands are only a footnote, because a
    subagent trying `curl` is harmless while the run itself may have died for another reason.
    """
    if interrupted:
        return "interrupted", ""
    denial = _denials(result_event)
    if returncode != 0:
        return "failed", f"claude terminou com código {returncode}. {stderr.strip()[-200:]} {denial}".strip()
    if not slug:
        return "failed", f"O Claude não chegou a iniciar nenhum estudo. {denial}".strip()
    if state.is_complete(slug):
        return "done", ""
    if state.needs_user(slug):
        return "needs_you", "O pipeline parou numa decisão tua: ver studies/<slug>/pending.md."
    if BG_WAIT_MESSAGE in stderr:
        reason = "Os subagentes demoraram mais do que o Claude Code espera e foram parados."
    else:
        reason = "Terminou sem concluir as 8 fases."
    return "failed", f"{reason} Volta a executar para retomar. {denial}".strip()


def _claude_command(topic: str) -> list[str]:
    return [
        "claude",
        "-p",
        f"/study {topic}",
        "--output-format",
        "stream-json",
        "--verbose",  # required by claude -p for stream-json
        "--model",
        ORCHESTRATOR_MODEL,
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--allowedTools",
        ",".join(ALLOWED_TOOLS),
    ]


def _assistant_text(event: dict) -> str:
    blocks = (event.get("message") or {}).get("content") or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def _plan_usage(event: dict) -> dict | None:
    info = event.get("rate_limit_info") or {}
    windows = info.get("unifiedWindows") or {}
    if not windows:
        return None
    return {
        "type": "plan_usage",
        "five_hour": (windows.get("five_hour") or {}).get("utilization"),
        "seven_day": (windows.get("seven_day") or {}).get("utilization"),
        "status": info.get("status"),
        "resets_at": info.get("resetsAt"),
    }


def _snapshot(tracker: UsageTracker) -> dict | None:
    """Per-phase progress from state.json, plus tokens so far; None until the study has a state."""
    if not tracker.slug or not state.state_path(tracker.slug).exists():
        return None
    try:
        return {**state.progress(tracker.slug), "tokens": tracker.total_tokens()}
    except Exception:  # a half-written or foreign state file must never stop the run
        return None


async def run_study(run_id: str, topic: str, on_event: OnEvent) -> RunResult:
    """Run `/study <topic>` headlessly and return what happened."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOGS_DIR / f"{timestamp}_{run_id}.jsonl"
    tracker = UsageTracker(run_id=f"{run_id}-{timestamp}")  # unique per run: a resumed item has several

    process = await asyncio.create_subprocess_exec(
        *_claude_command(topic),
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": BG_WAIT_CEILING_MS},
    )
    if sys.platform == "darwin":  # keep the Mac awake for as long as the run lasts
        await asyncio.create_subprocess_exec("caffeinate", "-i", "-w", str(process.pid))

    result_event: dict = {}
    last_plan: dict | None = None
    last_snapshot: dict | None = None
    with log_path.open("w", encoding="utf-8") as log_file:
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            log_file.write(line + "\n")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "result":
                result_event = event
            elif kind == "rate_limit_event" and (plan := _plan_usage(event)):
                last_plan = plan
                await on_event(plan)
            elif tracker.observe(event):
                await on_event({"type": "activity", "text": tracker.activity})
                snapshot = _snapshot(tracker)
                if snapshot and snapshot != last_snapshot:
                    last_snapshot = snapshot
                    await on_event({"type": "progress", **snapshot})
                if text := _assistant_text(event):
                    await on_event({"type": "log", "text": text[:500]})

    stderr = (await process.stderr.read()).decode("utf-8", errors="replace") if process.stderr else ""
    returncode = await process.wait()
    if stderr:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"STDERR: {stderr}\n")

    rows = tracker.finish(result_event)
    if tracker.slug and state.state_path(tracker.slug).parent.exists():  # never create a study folder
        append_rows(tracker.slug, rows)
    cost = round(sum(r["cost_usd"] for r in rows), 4)
    tokens = sum(r[f] for r in rows for f in ("input_tokens", "cache_read_tokens", "cache_creation_tokens", "output_tokens"))
    interrupted = returncode != 0 and bool(
        LIMIT_PATTERN.search(f"{result_event.get('result', '')} {stderr}")
        or (last_plan and last_plan.get("status") == "rejected")
    )
    status, note = _outcome(returncode, interrupted, result_event, tracker.slug, stderr)
    _append_run_record(topic, tracker.slug, timestamp, status, rows)
    if interrupted:
        await on_event({"type": "limit", "text": LIMIT_MESSAGE, "resets_at": (last_plan or {}).get("resets_at")})
    elif note:
        await on_event({"type": "error", "text": note})
    return RunResult(
        returncode=returncode, status=status, note=note, slug=tracker.slug,
        resets_at=(last_plan or {}).get("resets_at") if interrupted else None, cost_usd=cost, tokens=tokens,
    )


def _append_run_record(topic: str, slug: str | None, timestamp: str, status: str, rows: list[dict]) -> None:
    runs_csv = LOGS_DIR / "runs.csv"
    if runs_csv.exists() and runs_csv.read_text(encoding="utf-8").split("\n", 1)[0] != RUNS_HEADER:
        runs_csv.rename(LOGS_DIR / "runs.old.csv")  # header from before the outcome rules changed
    is_new = not runs_csv.exists()
    input_tokens = sum(r["input_tokens"] + r["cache_read_tokens"] + r["cache_creation_tokens"] for r in rows)
    output_tokens = sum(r["output_tokens"] for r in rows)
    cost = round(sum(r["cost_usd"] for r in rows), 4)
    with runs_csv.open("a", encoding="utf-8") as f:
        if is_new:
            f.write(RUNS_HEADER + "\n")
        f.write(f"{timestamp},{topic!r},{slug or ''},{status},{input_tokens},{output_tokens},{cost}\n")
