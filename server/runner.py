"""Launch Claude Code headlessly for one /study run, streaming progress events.

Uses asyncio.create_subprocess_exec with an argument list — never a shell string — so the
(already-validated) topic can never be interpreted by a shell. Parses --output-format
stream-json's newline-delimited JSON and forwards a simplified event per line to the
caller-supplied `on_event` callback, while also writing the raw line to a per-run log file.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"

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


def _claude_command(topic: str) -> list[str]:
    return [
        "claude",
        "-p",
        f"/study {topic}",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--allowedTools",
        ",".join(ALLOWED_TOOLS),
    ]


def _simplify(event: dict) -> dict:
    """Reduce one stream-json line to {type, text} for the browser's progress log."""
    event_type = event.get("type", "desconhecido")
    text = ""
    if event_type == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                text += f"[ferramenta: {block.get('name')}]"
    elif event_type == "result":
        text = str(event.get("result", ""))
    elif event_type == "system":
        text = str(event.get("subtype", ""))
    return {"type": event_type, "text": text}


async def run_study(run_id: str, topic: str, on_event: OnEvent) -> int:
    """Run `/study <topic>` headlessly. Returns the subprocess exit code."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOGS_DIR / f"{timestamp}_{run_id}.jsonl"

    command = _claude_command(topic)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

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
                await on_event({"type": "raw", "text": line})
                continue
            await on_event(_simplify(event))

    stderr = (await process.stderr.read()).decode("utf-8", errors="replace") if process.stderr else ""
    returncode = await process.wait()
    if stderr:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"STDERR: {stderr}\n")

    _append_run_record(topic, timestamp, returncode)
    await on_event({"type": "end", "text": f"terminado com código {returncode}"})
    return returncode


def _append_run_record(topic: str, timestamp: str, returncode: int) -> None:
    runs_csv = LOGS_DIR / "runs.csv"
    is_new = not runs_csv.exists()
    with runs_csv.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("timestamp,topic,result\n")
        result = "sucesso" if returncode == 0 else f"falhou({returncode})"
        f.write(f"{timestamp},{topic!r},{result}\n")
