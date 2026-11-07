import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport

from servidor import app as app_module
from servidor import runner


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    # Fresh queue/subscriber state per test, since app_module.state is a module-level singleton.
    monkeypatch.setattr(app_module, "state", app_module.RunState())
    app_module.app.router.lifespan_context = app_module.lifespan
    transport = ASGITransport(app=app_module.app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_rejects_invalid_tema(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.post("/api/estudos", json={"tema": "ab"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_accepts_valid_tema_and_streams_events(monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient) -> None:
    async def fake_run_estudo(run_id, tema, on_event):
        await on_event({"tipo": "assistant", "texto": "a trabalhar"})
        await on_event({"tipo": "fim", "texto": "terminado com código 0"})
        return 0

    monkeypatch.setattr(runner, "run_estudo", fake_run_estudo)

    async with app_module.app.router.lifespan_context(app_module.app), client as c:
        resp = await c.post("/api/estudos", json={"tema": "saude-portugal"})
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        events = []
        async with c.stream("GET", f"/api/runs/{run_id}/stream") as stream:
            async for line in stream.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
                if events and events[-1].get("tipo") == "fim":
                    break

    assert events[0]["tipo"] == "assistant"
    assert events[-1]["tipo"] == "fim"


@pytest.mark.asyncio
async def test_unknown_run_id_returns_404(client: httpx.AsyncClient) -> None:
    async with client as c:
        resp = await c.get("/api/runs/does-not-exist/stream")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_second_run_queues_behind_first(monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient) -> None:
    gate = asyncio.Event()

    async def slow_run_estudo(run_id, tema, on_event):
        await gate.wait()
        await on_event({"tipo": "fim", "texto": "terminado"})
        return 0

    monkeypatch.setattr(runner, "run_estudo", slow_run_estudo)

    async with app_module.app.router.lifespan_context(app_module.app), client as c:
        await c.post("/api/estudos", json={"tema": "primeiro tema"})
        await asyncio.sleep(0.05)  # let the worker pick up the first run
        second = await c.post("/api/estudos", json={"tema": "segundo tema"})

        assert second.json()["posicao_na_fila"] >= 1
        gate.set()
        await asyncio.sleep(0.05)
