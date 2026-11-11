"""Events are confirmed by code as soon as the historian records them; the writer only cites verified ones."""
from __future__ import annotations

from pathlib import Path

import pytest

from common import checks, verify
from common.csv_io import read_csv, write_csv
from common.schemas import Break, Event, EventLink


def _event(eid: str, excerpt: str | None, url: str = "https://example.org/law", verified: str = "yes") -> Event:
    return Event(id=eid, start_date="2011-05-17", scope="PT", type="x", title_pt="t", title_en="t", description_pt="d",
                 description_en="d", primary_source_url=url, access_date="2026-11-11", topics="a", verified=verified,
                 source_excerpt=excerpt)


def test_verify_events_sets_verified_from_the_page_not_from_the_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {"https://example.org/law": "A Lei n.º 56/79 criou o Serviço Nacional de Saúde em 1979."}
    monkeypatch.setattr(verify, "_fetch_text", lambda url, **k: pages[url])
    csv = tmp_path / "events.csv"
    write_csv(csv, Event, [
        _event("ok", "criou o Serviço Nacional de Saúde", verified="no"),   # found -> yes, even if the agent said no
        _event("wrong", "texto que não existe nesta página de forma nenhuma"),  # not found -> no, even if the agent said yes
        _event("noexcerpt", None),                                           # nothing to check -> no
    ])
    confirmed, unconfirmed = verify.verify_events(csv)
    assert (confirmed, unconfirmed) == (1, ["wrong", "noexcerpt"])
    assert {e.id: e.verified for e in read_csv(csv, Event)} == {"ok": "yes", "wrong": "no", "noexcerpt": "no"}


def test_phase_5_requires_an_excerpt_for_every_linked_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    studies = tmp_path / "studies"
    (studies / "t").mkdir(parents=True)
    monkeypatch.setattr(checks, "STUDIES_ROOT", studies)
    events_csv = tmp_path / "events.csv"
    monkeypatch.setattr(checks, "EVENTS_CSV", events_csv)
    write_csv(studies / "t" / "breaks.csv", Break, [Break(id="q1", series="s", axis="x", date="2012-01-01", type="level", magnitude=1.0, method="m")])
    write_csv(studies / "t" / "event_links.csv", EventLink, [EventLink(
        id="l1", break_id="q1", event_id="e1", status="linked", grade="C", justification_window="w", justification_pt="p", justification_en="e")])

    write_csv(events_csv, Event, [_event("e1", None)])
    ok, problems = checks.check_phase_5("t")
    assert not ok and "source_excerpt" in problems[0]

    write_csv(events_csv, Event, [_event("e1", "criou o Serviço Nacional de Saúde")])
    assert checks.check_phase_5("t") == (True, [])


def test_phase_6_rows_cannot_cite_an_unverified_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from common.schemas import Claim

    events_csv = tmp_path / "events.csv"
    monkeypatch.setattr(checks, "EVENTS_CSV", events_csv)
    write_csv(events_csv, Event, [_event("e1", "criou o SNS", url="https://example.org/a", verified="no"),
                                  _event("e2", "criou o SNS", url="https://example.org/b", verified="yes")])

    def claim(cid: str, url: str) -> Claim:
        return Claim(id=cid, type="event", text_pt="t", text_en="t", source_id="e", url=url, access_date="2026-11-11",
                     excerpt="criou o SNS", source_nature="primary", location="Q1")

    problems = checks.claim_row_problems(tmp_path, [claim("c001", "https://example.org/a"), claim("c002", "https://example.org/b")])
    assert len(problems) == 1 and "c001" in problems[0]
