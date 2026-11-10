"""Persistent local study queue (queue.json at the repo root, gitignored).

The queue is a backlog: adding a topic does not run it. The user picks what runs next
(`run`) from the page. Only one study runs at a time; picking another while one is running
marks it `run_next`, and the server starts it when the current one ends.

Item status: queued | running | done | failed | interrupted. An item that was running when
the server stopped (or was cut by the plan's usage limit) is `interrupted` and can be run
again: `/study` resumes from state.json.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

QUEUE_PATH = Path(__file__).resolve().parent.parent / "queue.json"
RUNNABLE = {"queued", "interrupted", "failed"}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class QueueError(Exception):
    pass


class StudyQueue:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or QUEUE_PATH
        self.items: list[dict] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        self.items = json.loads(self.path.read_text(encoding="utf-8")).get("items", [])
        for item in self.items:
            if item["status"] == "running":  # the server died mid-run
                item["status"] = "interrupted"
                item["run_next"] = False
        self.save()

    def save(self) -> None:
        """Atomic write, so a crash never leaves a half-written queue."""
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".queue-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"items": self.items}, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, item_id: str) -> dict:
        for item in self.items:
            if item["id"] == item_id:
                return item
        raise QueueError("unknown queue item")

    def running(self) -> dict | None:
        return next((i for i in self.items if i["status"] == "running"), None)

    def add(self, topic: str) -> dict:
        if any(i["topic"].casefold() == topic.casefold() and i["status"] != "done" for i in self.items):
            raise QueueError("this topic is already in the queue")
        item = {
            "id": uuid.uuid4().hex[:10], "topic": topic, "status": "queued", "run_next": False,
            "slug": None, "created_at": _now(), "started_at": None, "finished_at": None,
            "resets_at": None, "cost_usd": 0.0, "tokens": 0,
        }
        self.items.append(item)
        self.save()
        return item

    def remove(self, item_id: str) -> None:
        item = self.get(item_id)
        if item["status"] == "running":
            raise QueueError("cannot remove the study that is running")
        self.items.remove(item)
        self.save()

    def request_run(self, item_id: str) -> tuple[dict, bool]:
        """Returns (item, start_now). If another study is running the item is flagged run_next."""
        item = self.get(item_id)
        if item["status"] not in RUNNABLE:
            raise QueueError(f"cannot run an item that is {item['status']}")
        if self.running():
            item["run_next"] = True
            self.save()
            return item, False
        return item, True

    def mark_running(self, item_id: str) -> dict:
        item = self.get(item_id)
        item.update(status="running", run_next=False, started_at=_now(), finished_at=None, resets_at=None)
        self.save()
        return item

    def finish(self, item_id: str, *, status: str, slug: str | None, cost_usd: float, tokens: int,
               resets_at: int | None = None) -> dict:
        item = self.get(item_id)
        item.update(status=status, slug=slug or item["slug"], finished_at=_now(), resets_at=resets_at)
        item["cost_usd"] = round(item["cost_usd"] + cost_usd, 4)  # a resumed study adds to its total
        item["tokens"] += tokens
        self.save()
        return item

    def next_flagged(self) -> dict | None:
        return next((i for i in self.items if i["run_next"] and i["status"] in RUNNABLE), None)
