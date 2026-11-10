"""UsageTracker: study/phase detection, token dedupe, cost reconciliation, persistence."""
from __future__ import annotations

from pathlib import Path

import pytest

from common import state, usage


def _assistant(msg_id: str, *blocks: dict, parent: str | None = None, model: str = "claude-sonnet-5-5", **tokens: int) -> dict:
    return {
        "type": "assistant", "parent_tool_use_id": parent,
        "message": {"id": msg_id, "model": model, "content": list(blocks), "usage": {
            "input_tokens": tokens.get("i", 0), "output_tokens": tokens.get("o", 0),
            "cache_read_input_tokens": tokens.get("r", 0), "cache_creation_input_tokens": tokens.get("c", 0)}},
    }


def _bash(command: str) -> dict:
    return {"type": "tool_use", "name": "Bash", "input": {"command": command}}


def test_detects_study_and_phase_and_attributes_tokens() -> None:
    t = usage.UsageTracker(run_id="r1")
    t.observe(_assistant("m1", _bash("uv run python -m common.state resume my-study"), i=10, o=5))
    t.observe(_assistant("m2", _bash("uv run python -m common.state start-phase my-study 3"), i=20, o=5))
    t.observe(_assistant("m3", {"type": "text", "text": "hi"}, i=30, o=5, parent="toolu_1"))
    assert t.slug == "my-study" and t.phase == "3"
    assert t.tokens[("prep", "claude-sonnet-5-5")]["input_tokens"] == 10
    assert t.tokens[("3", "claude-sonnet-5-5")]["input_tokens"] == 50  # m2 + the subagent message


def test_same_message_id_is_counted_once() -> None:
    t = usage.UsageTracker()
    event = _assistant("m1", {"type": "text", "text": "a"}, i=10, o=5)
    t.observe(event)
    t.observe(event)
    assert t.total_tokens() == 15


def test_subagent_commands_do_not_change_the_phase() -> None:
    t = usage.UsageTracker()
    t.observe(_assistant("m1", _bash("uv run python -m common.state start-phase s 2"), i=1))
    t.observe(_assistant("m2", _bash("uv run python -m common.state start-phase s 7"), i=1, parent="toolu_9"))
    assert t.phase == "2"


def test_activity_line_describes_the_tool() -> None:
    t = usage.UsageTracker()
    t.observe(_assistant("m1", {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "planner", "description": "Draft the plan"}}))
    assert t.activity == "planner: Draft the plan"
    t.observe(_assistant("m2", {"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b/plan.md"}}))
    assert t.activity == "Read plan.md"


def test_finish_matches_exact_model_totals_and_splits_cost_by_phase() -> None:
    t = usage.UsageTracker(run_id="r1")
    t.observe(_assistant("m1", _bash("uv run python -m common.state start-phase s 1"), i=100, o=100))
    t.observe(_assistant("m2", _bash("uv run python -m common.state start-phase s 2"), i=100, o=300))
    result = {"modelUsage": {"claude-sonnet-5-5": {
        "inputTokens": 200, "outputTokens": 400, "cacheReadInputTokens": 50, "cacheCreationInputTokens": 0, "costUSD": 1.0}}}
    rows = t.finish(result)
    by_phase = {r["phase"]: r for r in rows}
    assert by_phase["unattributed"]["cache_read_tokens"] == 50  # in modelUsage, not in the messages
    assert sum(r["cost_usd"] for r in rows) == pytest.approx(1.0, abs=1e-5)
    assert sum(r["input_tokens"] for r in rows) == 200 and sum(r["output_tokens"] for r in rows) == 400
    assert by_phase["2"]["cost_usd"] > by_phase["1"]["cost_usd"]  # phase 2 produced more output


def test_persist_and_summarize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(usage, "STUDIES_ROOT", tmp_path)
    rows = [
        {"run_id": "r1", "timestamp": "t", "phase": p, "model": "m", "input_tokens": 10, "cache_read_tokens": 0,
         "cache_creation_tokens": 0, "output_tokens": 5, "cost_usd": c}
        for p, c in (("1", 0.5), ("2", 0.25))
    ]
    usage.append_rows("s", rows)
    usage.append_rows("s", rows[:1])  # a resumed run appends
    summary = usage.summarize("s")
    assert summary["cost_usd"] == pytest.approx(1.25) and summary["input_tokens"] == 30
    assert [p["phase"] for p in summary["phases"]] == ["1", "2"]
    assert summary["phases"][0]["name"] == "plan"
    assert [s["slug"] for s in usage.summarize_all()] == ["s"]


def test_progress_snapshot_reports_units(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "STUDIES_ROOT", tmp_path)
    (tmp_path / "s").mkdir()
    state.init("s")
    s = state.load("s")
    s["completed_phases"] = [1, 2]
    state.save("s", s)
    state.start_phase("s", 3)
    state.plan_units("s", 3, ["f1", "f2"])
    snap = state.progress("s")
    by = {p["n"]: p for p in snap["phases"]}
    assert by[1]["status"] == "completed" and by[3]["status"] == "in_progress"
    assert (by[3]["done"], by[3]["total"]) == (0, 2) and by[4]["status"] == "pending"
