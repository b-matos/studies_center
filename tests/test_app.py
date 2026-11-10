import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport

from server import app as app_module
from server import runner


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    # Fresh queue/subscriber state per test, since app_module.state is a module-level singleton.
    monkeypatch.setattr(app_module, "state", app_module.RunState())
    app_module.app.router.lifespan_context = app_module.lifespan
    transport = ASGITransport(app=app_module.app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_rejects_invalid_topic(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.post("/api/studies", json={"topic": "ab"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_accepts_valid_topic_and_streams_events(monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient) -> None:
    async def fake_run_study(run_id, topic, on_event):
        await on_event({"type": "assistant", "text": "a trabalhar"})
        await on_event({"type": "end", "text": "terminado com código 0"})
        return 0

    monkeypatch.setattr(runner, "run_study", fake_run_study)

    async with app_module.app.router.lifespan_context(app_module.app), client as c:
        resp = await c.post("/api/studies", json={"topic": "saude-portugal"})
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        events = []
        async with c.stream("GET", f"/api/runs/{run_id}/stream") as stream:
            async for line in stream.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
                if events and events[-1].get("type") == "end":
                    break

    assert events[0]["type"] == "assistant"
    assert events[-1]["type"] == "end"


@pytest.mark.asyncio
async def test_unknown_run_id_returns_404(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/runs/does-not-exist/stream")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_second_run_queues_behind_first(monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient) -> None:
    gate = asyncio.Event()

    async def slow_run_study(run_id, topic, on_event):
        await gate.wait()
        await on_event({"type": "end", "text": "terminado"})
        return 0

    monkeypatch.setattr(runner, "run_study", slow_run_study)

    async with app_module.app.router.lifespan_context(app_module.app), client as c:
        await c.post("/api/studies", json={"topic": "primeiro tema"})
        await asyncio.sleep(0.05)  # let the worker pick up the first run
        second = await c.post("/api/studies", json={"topic": "segundo tema"})

        assert second.json()["queue_position"] >= 1
        gate.set()
        await asyncio.sleep(0.05)


def test_runner_detects_usage_limit_and_sums_tokens() -> None:
    assert runner.LIMIT_PATTERN.search("Claude AI usage limit reached|1731000000")
    assert not runner.LIMIT_PATTERN.search("tudo bem")
    assert runner._tokens({"usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 3}}) == (15, 3)
    assert runner._tokens({}) == (0, 0)
