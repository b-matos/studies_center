"""Tests for the local server: persistent queue API, one-at-a-time runs, run_next chaining."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from server import app as app_module
from server import queue as queue_module
from server import runner


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    monkeypatch.setattr(queue_module, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(app_module, "hub", app_module.Hub())  # lifespan is not run by ASGITransport
    return httpx.AsyncClient(transport=ASGITransport(app=app_module.app), base_url="http://testserver")


def _fake_run(gate: asyncio.Event | None = None, *, status: str = "done", note: str = ""):
    async def fake(run_id, topic, on_event):
        await on_event({"type": "activity", "text": f"working on {topic}"})
        if gate:
            await gate.wait()
        resets = 1794338400 if status == "interrupted" else None
        return runner.RunResult(0 if status == "done" else 1, status, note, "demo-study", resets, 1.25, 1000)
    return fake


async def _wait_for(predicate, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_rejects_invalid_and_duplicate_topics(client: httpx.AsyncClient) -> None:
    async with client as c:
        assert (await c.post("/api/queue", json={"topic": "ab"})).status_code == 422
        assert (await c.post("/api/queue", json={"topic": "saude em Portugal"})).status_code == 200
        assert (await c.post("/api/queue", json={"topic": "Saude em portugal"})).status_code == 409


@pytest.mark.asyncio
async def test_queue_survives_a_restart_and_running_becomes_interrupted(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    async with client as c:
        item = (await c.post("/api/queue", json={"topic": "habitacao"})).json()
    store = queue_module.StudyQueue(tmp_path / "queue.json")
    store.mark_running(item["id"])  # the server dies while it runs
    reloaded = queue_module.StudyQueue(tmp_path / "queue.json")
    assert reloaded.get(item["id"])["status"] == "interrupted"


@pytest.mark.asyncio
async def test_nothing_runs_until_asked_then_result_is_stored(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    monkeypatch.setattr(runner, "run_study", _fake_run())
    async with client as c:
        item = (await c.post("/api/queue", json={"topic": "saude em Portugal"})).json()
        await asyncio.sleep(0.05)
        assert (await c.get("/api/queue")).json()["items"][0]["status"] == "queued"

        assert (await c.post(f"/api/queue/{item['id']}/run")).json()["started"] is True
        await _wait_for(lambda: app_module.hub.queue.get(item["id"])["status"] == "done")
        done = app_module.hub.queue.get(item["id"])
        assert (done["slug"], done["cost_usd"], done["tokens"]) == ("demo-study", 1.25, 1000)


@pytest.mark.asyncio
async def test_second_item_waits_and_starts_after_the_first(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    gate = asyncio.Event()
    monkeypatch.setattr(runner, "run_study", _fake_run(gate))
    async with client as c:
        first = (await c.post("/api/queue", json={"topic": "primeiro tema"})).json()
        second = (await c.post("/api/queue", json={"topic": "segundo tema"})).json()
        await c.post(f"/api/queue/{first['id']}/run")
        started = (await c.post(f"/api/queue/{second['id']}/run")).json()
        assert started["started"] is False  # flagged as "run next", not started in parallel
        assert (await c.delete(f"/api/queue/{first['id']}")).status_code == 409  # running: not removable

        gate.set()
        await _wait_for(lambda: app_module.hub.queue.get(second["id"])["status"] == "done")
        assert app_module.hub.queue.get(first["id"])["status"] == "done"


@pytest.mark.asyncio
async def test_plan_limit_interrupts_and_does_not_start_the_next(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    monkeypatch.setattr(runner, "run_study", _fake_run(status="interrupted"))
    async with client as c:
        a = (await c.post("/api/queue", json={"topic": "tema um"})).json()
        b = (await c.post("/api/queue", json={"topic": "tema dois"})).json()
        app_module.hub.queue.get(b["id"])["run_next"] = True
        await c.post(f"/api/queue/{a['id']}/run")
        await _wait_for(lambda: app_module.hub.queue.get(a["id"])["status"] == "interrupted")
        await asyncio.sleep(0.05)
        assert app_module.hub.queue.get(a["id"])["resets_at"] == 1794338400
        assert app_module.hub.queue.get(b["id"])["status"] == "queued"  # waits for the user


@pytest.mark.asyncio
async def test_new_subscribers_get_the_latest_state_first(client: httpx.AsyncClient) -> None:
    hub = app_module.hub
    await hub.publish({"type": "progress", "slug": "x", "phases": []})
    await hub.publish({"type": "activity", "text": "not replayed"})
    subscriber = hub.subscribe()
    assert subscriber.get_nowait()["type"] == "progress"
    assert subscriber.empty()


def test_runner_command_is_valid_for_headless_stream_json() -> None:
    command = runner._claude_command("saude")
    assert "--verbose" in command and command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--model") + 1] == "sonnet"
    assert command[2] == "/study saude"


def test_runner_detects_usage_limit_text() -> None:
    assert runner.LIMIT_PATTERN.search("Claude AI usage limit reached|1731000000")
    assert not runner.LIMIT_PATTERN.search("tudo bem")


@pytest.mark.asyncio
async def test_failed_run_keeps_its_reason_and_can_be_run_again(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    monkeypatch.setattr(runner, "run_study", _fake_run(status="failed", note="Permissão recusada"))
    async with client as c:
        item = (await c.post("/api/queue", json={"topic": "habitacao"})).json()
        await c.post(f"/api/queue/{item['id']}/run")
        await _wait_for(lambda: app_module.hub.queue.get(item["id"])["status"] == "failed")
        assert app_module.hub.queue.get(item["id"])["note"] == "Permissão recusada"
        assert (await c.post(f"/api/queue/{item['id']}/run")).json()["started"] is True  # retry allowed


def test_outcome_is_judged_on_the_study_not_on_the_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from common import state

    monkeypatch.setattr(state, "STUDIES_ROOT", tmp_path)
    denied = {"permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "mkdir x && cat > y"}}]}
    status, note = runner._outcome(0, False, denied, None, "")
    assert status == "failed" and "recusado" in note and "mkdir x" in note  # exit code 0, still a failure

    assert runner._outcome(0, False, {}, None, "")[0] == "failed"  # never started a study
    assert runner._outcome(1, True, {}, "s", "")[0] == "interrupted"

    state.init("s")
    assert runner._outcome(0, False, {}, "s", "")[0] == "failed"  # exited cleanly with phases missing
    (tmp_path / "s" / "pending.md").write_text("decision", encoding="utf-8")
    assert runner._outcome(0, False, {}, "s", "")[0] == "needs_you"
    s = state.load("s")
    s["completed_phases"] = list(range(1, 9))
    state.save("s", s)
    (tmp_path / "s" / "pending.md").unlink()
    assert runner._outcome(0, False, {}, "s", "")[0] == "done"


def test_background_wait_timeout_is_named_as_the_cause_not_a_denied_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from common import state

    monkeypatch.setattr(state, "STUDIES_ROOT", tmp_path)
    state.init("s")
    denied = {"permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "curl x"}}]}
    stderr = "Background tasks still running 10m after the last turn (subagent a); stopping them."
    status, note = runner._outcome(0, False, denied, "s", stderr)
    assert status == "failed"
    assert note.startswith("Os subagentes demoraram") and "retomar" in note and "curl x" in note


def test_runner_environment_extends_the_background_wait() -> None:
    assert int(runner.BG_WAIT_CEILING_MS) >= 3_600_000


def test_plan_name_keeps_only_the_subscription_type() -> None:
    raw = '{"subscriptionType": "pro", "email": "someone@example.com", "orgId": "secret", "planTier": "pro"}'
    assert app_module.plan_from_status(raw) == "Pro"
    assert "example.com" not in str(app_module.plan_from_status(raw))
    assert app_module.plan_from_status("not json") is None
    assert app_module.plan_from_status('{"loggedIn": false}') is None


@pytest.mark.asyncio
async def test_plan_endpoint_returns_only_the_plan(client: httpx.AsyncClient) -> None:
    app_module.hub.plan = "Pro"
    async with client as c:
        assert (await c.get("/api/plan")).json() == {"plan": "Pro"}
