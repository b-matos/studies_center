"""runner.run_study must survive stream-json lines far above asyncio's default 64 KiB limit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from server import runner


async def test_run_study_handles_very_long_stream_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    big = json.dumps({"type": "user", "message": {"content": "x" * 400_000}})
    script = f"import json; print({big!r}); print(json.dumps({{'type': 'result', 'result': 'ok'}}))"
    monkeypatch.setattr(runner, "_claude_command", lambda topic: [sys.executable, "-c", script])
    monkeypatch.setattr(runner, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(runner, "_append_run_record", lambda *a, **k: None)

    async def on_event(event: dict) -> None:
        pass

    await runner.run_study("t1", "tema", on_event)  # must not raise LimitOverrunError

    log = next((tmp_path / "logs").glob("*.jsonl"))
    assert log.stat().st_size > 400_000
