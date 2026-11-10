"""Local FastAPI server: serves the compiled Quarto site and exposes POST /api/studies.

Binds to 127.0.0.1 only (see run()). One /study run executes at a time; later requests
queue up (asyncio.Queue + a single worker task). Progress is pushed to the browser as
Server-Sent Events, keyed by run_id.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from server import runner
from server.validation import InvalidTopic, validate_topic

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site" / "_site"


class StudyRequest(BaseModel):
    topic: str


class RunState:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.subscribers: dict[str, list[asyncio.Queue[dict]]] = {}
        self.worker_task: asyncio.Task | None = None

    def new_run(self, topic: str) -> str:
        run_id = uuid.uuid4().hex[:12]
        self.subscribers[run_id] = []
        self.queue.put_nowait((run_id, topic))
        return run_id

    def subscribe(self, run_id: str) -> asyncio.Queue[dict]:
        subscriber_queue: asyncio.Queue[dict] = asyncio.Queue()
        self.subscribers.setdefault(run_id, []).append(subscriber_queue)
        return subscriber_queue

    async def publish(self, run_id: str, event: dict) -> None:
        for subscriber_queue in self.subscribers.get(run_id, []):
            await subscriber_queue.put(event)

    async def worker(self) -> None:
        while True:
            run_id, topic = await self.queue.get()

            async def on_event(event: dict, run_id: str = run_id) -> None:
                await self.publish(run_id, event)

            try:
                await runner.run_study(run_id, topic, on_event)
            except FileNotFoundError:
                await self.publish(run_id, {"type": "error", "text": "comando 'claude' não encontrado"})
                await self.publish(run_id, {"type": "end", "text": "falhou"})
            except Exception as exc:  # defensive: never let one bad run kill the worker loop
                await self.publish(run_id, {"type": "error", "text": str(exc)})
                await self.publish(run_id, {"type": "end", "text": "falhou"})
            finally:
                self.queue.task_done()


state = RunState()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    state.worker_task = asyncio.create_task(state.worker())
    yield
    if state.worker_task:
        state.worker_task.cancel()


app = FastAPI(lifespan=lifespan)


@app.post("/api/studies")
async def create_study(req: StudyRequest) -> dict:
    try:
        topic = validate_topic(req.topic)
    except InvalidTopic as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    run_id = state.new_run(topic)
    return {"run_id": run_id, "topic": topic, "queue_position": state.queue.qsize()}


@app.get("/api/runs")
async def list_runs() -> dict:
    return {"em_fila_ou_a_correr": list(state.subscribers.keys())}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str) -> EventSourceResponse:
    if run_id not in state.subscribers:
        raise HTTPException(status_code=404, detail="run_id desconhecido")
    subscriber_queue = state.subscribe(run_id)

    async def event_generator() -> AsyncIterator[dict]:
        while True:
            event = await subscriber_queue.get()
            yield {"data": json.dumps(event, ensure_ascii=False)}
            if event.get("type") == "end":
                break

    return EventSourceResponse(event_generator())


# Static site last: it mounts "/", so API routes above must be declared first.
if SITE_DIR.exists():
    app.mount("/", StaticFiles(directory=SITE_DIR, html=True), name="site")


def run() -> None:
    import uvicorn

    uvicorn.run("server.app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    run()
