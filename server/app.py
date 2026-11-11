"""Local FastAPI server: serves the compiled Quarto site and the study queue API.

Binds to 127.0.0.1 only (see run()). The queue is a persistent backlog (server/queue.py):
nothing runs until you press "run" on an item. One study runs at a time; the next flagged
one starts when it ends. Progress goes to every open page through one Server-Sent Events
stream (/api/events); a page that connects late gets the current state first.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from common import usage
from server import decisions, publish, runner
from server.queue import QueueError, StudyQueue
from server.validation import InvalidTopic, validate_topic

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site" / "_site"


def plan_from_status(raw: str) -> str | None:
    """Plan name from `claude auth status` JSON. Only the subscription type is kept: the same
    output has the account email and organisation id, which must never reach the page."""
    try:
        kind = json.loads(raw).get("subscriptionType")
    except (json.JSONDecodeError, AttributeError):
        return None
    return str(kind).capitalize() if kind else None


async def detect_plan() -> str | None:
    try:
        process = await asyncio.create_subprocess_exec(
            "claude", "auth", "status", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except (FileNotFoundError, TimeoutError):
        return None
    return plan_from_status(out.decode("utf-8", errors="replace"))


class TopicRequest(BaseModel):
    topic: str


class Hub:
    """Queue + fan-out of events to the open pages + the single running study."""

    def __init__(self) -> None:
        self.queue = StudyQueue()
        self.subscribers: list[asyncio.Queue[dict]] = []
        self.task: asyncio.Task | None = None
        self.last: dict[str, dict] = {}  # latest event of each kind, replayed to new subscribers
        self.plan: str | None = None

    def subscribe(self) -> asyncio.Queue[dict]:
        subscriber: asyncio.Queue[dict] = asyncio.Queue()
        for event in self.last.values():
            subscriber.put_nowait(event)
        self.subscribers.append(subscriber)
        return subscriber

    async def publish(self, event: dict) -> None:
        if event["type"] in {"progress", "plan_usage", "limit", "queue"}:
            self.last[event["type"]] = event
        for subscriber in self.subscribers:
            await subscriber.put(event)

    def items_view(self) -> list[dict]:
        """Queue items; those waiting for the user carry the question read from pending.md."""
        return [
            {**i, "question": decisions.read_question(i["slug"])} if i["status"] == "needs_you" else i
            for i in self.queue.items
        ]

    async def publish_queue(self) -> None:
        await self.publish({"type": "queue", "items": self.items_view()})

    def start(self, item_id: str) -> None:
        item = self.queue.mark_running(item_id)
        self.last.pop("progress", None)
        self.last.pop("limit", None)
        self.task = asyncio.create_task(self._run(item))

    async def _run(self, item: dict) -> None:
        await self.publish_queue()

        async def on_event(event: dict) -> None:
            await self.publish(event)

        status, result, note = "failed", None, ""
        try:
            result = await runner.run_study(item["id"], item["topic"], on_event)
            status = result.status
        except FileNotFoundError:
            note = "comando 'claude' não encontrado"
            await self.publish({"type": "error", "text": note})
        except Exception as exc:  # defensive: never let one bad run kill the server
            note = str(exc)
            await self.publish({"type": "error", "text": note})
        note = getattr(result, "note", "") or note
        slug = getattr(result, "slug", None)
        if status == "done" and slug:
            try:
                published = await publish.publish_study(slug)
            except Exception as exc:  # defensive: a git problem must not break the queue
                published = f"push falhou: {exc}"
            if published:
                note = f"{note} · {published}" if note else published
                await self.publish({"type": "activity", "text": published})
        self.queue.finish(
            item["id"], status=status, slug=slug,
            cost_usd=getattr(result, "cost_usd", 0.0), tokens=getattr(result, "tokens", 0),
            resets_at=getattr(result, "resets_at", None), note=note,
        )
        await self.publish({"type": "end", "item_id": item["id"], "status": status})
        await self.publish_queue()
        await self.publish({"type": "usage", "studies": usage.summarize_all()})
        following = self.queue.next_flagged()
        if following and status in {"done", "failed"}:  # after a limit cut or a decision for the user, wait
            self.start(following["id"])


hub: Hub | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global hub
    hub = Hub()
    hub.plan = await detect_plan()
    yield
    if hub.task:
        hub.task.cancel()


app = FastAPI(lifespan=lifespan)


def _hub() -> Hub:
    assert hub is not None
    return hub


@app.get("/api/queue")
async def get_queue() -> dict:
    return {"items": _hub().items_view()}


@app.post("/api/queue")
async def add_to_queue(req: TopicRequest) -> dict:
    try:
        topic = validate_topic(req.topic)
        item = _hub().queue.add(topic)
    except InvalidTopic as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QueueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _hub().publish_queue()
    return item


@app.delete("/api/queue/{item_id}")
async def remove_from_queue(item_id: str) -> dict:
    try:
        _hub().queue.remove(item_id)
    except QueueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _hub().publish_queue()
    return {"removed": item_id}


@app.post("/api/queue/{item_id}/run")
async def run_item(item_id: str) -> dict:
    try:
        _item, start_now = _hub().queue.request_run(item_id)
    except QueueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if start_now:
        _hub().start(item_id)
    await _hub().publish_queue()
    return {"id": item_id, "started": start_now}


class AnswerRequest(BaseModel):
    answer: str


@app.post("/api/queue/{item_id}/answer")
async def answer_decision(item_id: str, req: AnswerRequest) -> dict:
    """Record the user's answer to a pending decision and resume the study (or queue it next)."""
    try:
        item = _hub().queue.get(item_id)
        if item["status"] != "needs_you":
            raise QueueError("this item is not waiting for a decision")
        decisions.record_answer(item["slug"], req.answer)
        _item, start_now = _hub().queue.request_run(item_id)
    except decisions.DecisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QueueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if start_now:
        _hub().start(item_id)
    await _hub().publish_queue()
    return {"id": item_id, "started": start_now}


@app.get("/api/plan")
async def get_plan() -> dict:
    return {"plan": _hub().plan}


@app.get("/api/usage")
async def get_usage() -> dict:
    return {"studies": usage.summarize_all()}


@app.get("/api/events")
async def stream_events() -> EventSourceResponse:
    subscriber = _hub().subscribe()

    async def event_generator() -> AsyncIterator[dict]:
        try:
            while True:
                event = await subscriber.get()
                yield {"data": json.dumps(event, ensure_ascii=False)}
        finally:
            _hub().subscribers.remove(subscriber)

    return EventSourceResponse(event_generator())


# Static site last: it mounts "/", so API routes above must be declared first.
if SITE_DIR.exists():
    app.mount("/", StaticFiles(directory=SITE_DIR, html=True), name="site")


def run() -> None:
    import uvicorn

    uvicorn.run("server.app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    run()
