"""The review endpoints of the local server: list, approve with the full checklist, ask for changes."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from common import checks, review, state
from common.csv_io import write_csv
from common.schemas import Claim
from server import app as app_module
from server import queue as queue_module

SLUG = "demo-study"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    root = tmp_path / "studies"
    for module in (state, checks, review):
        monkeypatch.setattr(module, "STUDIES_ROOT", root)
    monkeypatch.setattr(queue_module, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(app_module, "hub", app_module.Hub())
    monkeypatch.delenv("STUDIES_AUTO_PUSH", raising=False)
    state.init(SLUG, {"title_pt": "Saúde", "title_en": "Health"})
    d = root / SLUG
    (d / "report.pt.qmd").write_text("# R\n\n## Limitações\n\nx\n", encoding="utf-8")
    (d / "report.en.qmd").write_text("# R\n\n## Limitations\n\nx\n", encoding="utf-8")
    write_csv(d / "claims.csv", Claim, [])
    s = state.load(SLUG)
    s["completed_phases"] = list(range(1, 9))
    state.save(SLUG, s)
    review.mark_ready(d)
    return httpx.AsyncClient(transport=ASGITransport(app=app_module.app), base_url="http://testserver")


async def test_pending_reviews_are_listed_with_their_checklist(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/reviews")).json()
    assert [r["slug"] for r in body["reviews"]] == [SLUG]
    assert {c["id"] for c in body["reviews"][0]["checklist"]} == set(review.CHECKS)


async def test_approving_needs_the_whole_checklist_and_a_name(client: httpx.AsyncClient) -> None:
    partial = await client.post(f"/api/reviews/{SLUG}/approve", json={"by": "ana", "checked": ["report_pt"]})
    assert partial.status_code == 422 and "checklist not complete" in partial.json()["detail"]
    nameless = await client.post(f"/api/reviews/{SLUG}/approve", json={"by": "", "checked": list(review.CHECKS)})
    assert nameless.status_code == 422

    ok = await client.post(f"/api/reviews/{SLUG}/approve", json={"by": "ana", "checked": list(review.CHECKS)})
    assert ok.status_code == 200 and "STUDIES_AUTO_PUSH" in ok.json()["message"]  # approved; the push stays manual
    assert review.read_meta(state.STUDIES_ROOT / SLUG)["status"] == "published"
    assert (await client.get("/api/reviews")).json()["reviews"] == []
    again = await client.post(f"/api/reviews/{SLUG}/approve", json={"by": "ana", "checked": list(review.CHECKS)})
    assert again.status_code == 422, "a study that is not waiting cannot be approved twice"


async def test_asking_for_changes_reopens_the_study_and_the_queue_item(client: httpx.AsyncClient) -> None:
    hub = app_module._hub()
    item = hub.queue.add("Saúde")
    hub.queue.finish(item["id"], status="done", slug=SLUG, cost_usd=0.0, tokens=0)

    empty = await client.post(f"/api/reviews/{SLUG}/changes", json={"comment": " "})
    assert empty.status_code == 422
    out = await client.post(f"/api/reviews/{SLUG}/changes", json={"comment": "Suavizar a conclusão sobre as urgências."})
    assert out.status_code == 200 and out.json()["queued"] is True
    assert hub.queue.get(item["id"])["status"] == "interrupted" and "alterações" in hub.queue.get(item["id"])["note"]
    assert state.load(SLUG)["current_phase"] == 6 and 8 not in state.load(SLUG)["completed_phases"]
    assert "urgências" in (state.STUDIES_ROOT / SLUG / "decisions.md").read_text(encoding="utf-8")
    assert (await client.get("/api/reviews")).json()["reviews"] == []


async def test_unknown_study_is_a_422(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/reviews/nope/approve", json={"by": "ana", "checked": list(review.CHECKS)})
    assert r.status_code == 422
