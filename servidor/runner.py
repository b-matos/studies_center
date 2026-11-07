"""Launch Claude Code headlessly for one /estudo run, streaming progress events.

Uses asyncio.create_subprocess_exec with an argument list — never a shell string — so the
(already-validated) tema can never be interpreted by a shell. Parses --output-format
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


def _claude_command(tema: str) -> list[str]:
    return [
        "claude",
        "-p",
        f"/estudo {tema}",
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
    """Reduce one stream-json line to {tipo, texto} for the browser's progress log."""
    event_type = event.get("type", "desconhecido")
    texto = ""
    if event_type == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text":
                texto += block.get("text", "")
            elif block.get("type") == "tool_use":
                texto += f"[ferramenta: {block.get('name')}]"
    elif event_type == "result":
        texto = str(event.get("result", ""))
    elif event_type == "system":
        texto = str(event.get("subtype", ""))
    return {"tipo": event_type, "texto": texto}


async def run_estudo(run_id: str, tema: str, on_event: OnEvent) -> int:
    """Run `/estudo <tema>` headlessly. Returns the subprocess exit code."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOGS_DIR / f"{timestamp}_{run_id}.jsonl"

    command = _claude_command(tema)
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
                await on_event({"tipo": "raw", "texto": line})
                continue
            await on_event(_simplify(event))

    stderr = (await process.stderr.read()).decode("utf-8", errors="replace") if process.stderr else ""
    returncode = await process.wait()
    if stderr:
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"STDERR: {stderr}\n")

    _append_run_record(tema, timestamp, returncode)
    await on_event({"tipo": "fim", "texto": f"terminado com código {returncode}"})
    return returncode


def _append_run_record(tema: str, timestamp: str, returncode: int) -> None:
    runs_csv = LOGS_DIR / "runs.csv"
    is_new = not runs_csv.exists()
    with runs_csv.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("timestamp,tema,resultado\n")
        resultado = "sucesso" if returncode == 0 else f"falhou({returncode})"
        f.write(f"{timestamp},{tema!r},{resultado}\n")
