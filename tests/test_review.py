"""The human review gate: nothing is published without the author's approval of this exact content."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from common import checks, review, state
from common.csv_io import write_csv
from common.schemas import Claim, DataSource, EventLink

SLUG = "demo"


@pytest.fixture
def studies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "studies"
    monkeypatch.setattr(state, "STUDIES_ROOT", root)
    monkeypatch.setattr(checks, "STUDIES_ROOT", root)
    monkeypatch.setattr(review, "STUDIES_ROOT", root)
    state.init(SLUG, {"title_pt": "Saúde", "title_en": "Health"})
    d = root / SLUG
    (d / "report.pt.qmd").write_text("# Relatório\n\n## Limitações\n\nTexto.\n", encoding="utf-8")
    (d / "report.en.qmd").write_text("# Report\n\n## Limitations\n\nText.\n", encoding="utf-8")
    claim = Claim(id="c001", type="fact", text_pt="t", text_en="t", source_id="s", url="https://x.example/a", access_date="2026-11-18",
                  excerpt="e", source_nature="primary", location="Q1", verification_status="confirmed")
    write_csv(d / "claims.csv", Claim, [claim])
    write_csv(d / "sources.csv", DataSource, [DataSource(id="s1", axis="a", name="n", organisation="INE", url="https://x", format="csv", license="CC BY 4.0",
                                                         temporal_coverage="2000", geographic_coverage="PT", status="tested")])
    write_csv(d / "event_links.csv", EventLink, [
        EventLink(id="l1", break_id="q1", event_id="e1", status="linked", grade="A", justification_window="w", justification_pt="p", justification_en="e"),
        EventLink(id="l2", break_id="q2", event_id="e2", status="linked", grade="C", justification_window="w", justification_pt="p", justification_en="e"),
    ])
    (d / "verification.md").write_text("# Verificação\n\n- c001: confirmed\n- c002: failed - sem fonte\n- c003: failed - 404\n", encoding="utf-8")
    return d


def _approve(d: Path) -> dict:
    return review.approve(d, by="ana", checked=list(review.CHECKS))


def test_the_packet_is_computed_from_the_files(studies: Path) -> None:
    p = review.packet(studies)
    items = {c["id"]: c for c in p["checklist"]}
    assert set(items) == set(review.CHECKS) and p["status"] == "in_progress" and not p["approved"]
    assert "removida(s): c002, c003" in items["removed_claims"]["detail"] and items["removed_claims"]["warning"]
    assert items["strong_links"]["detail"].startswith("1 de 2 ligações") and "e1" in items["strong_links"]["detail"]
    assert items["licences"]["detail"] == "1× CC BY 4.0" and not items["limitations"]["warning"]
    (studies / "report.en.qmd").write_text("# Report\n\nNo limits here.\n", encoding="utf-8")
    assert review.packet(studies)["checklist"][2]["warning"], "a report without a limitations section is flagged"


def test_phase_8_leaves_a_study_ready_for_review_never_published(studies: Path) -> None:
    assert review.mark_ready(studies) == "ready_for_review"
    assert review.read_meta(studies)["status"] == "ready_for_review"
    assert [p["slug"] for p in review.pending_reviews(studies.parent)] == [SLUG]
    meta = review.read_meta(studies) | {"status": "published"}  # an agent publishes by itself
    (studies / "study.yml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    assert review.mark_ready(studies) == "ready_for_review", "self-published without approval goes back to review"
    (studies / "study.yml").write_text(yaml.safe_dump(meta | {"status": "test"}), encoding="utf-8")
    assert review.mark_ready(studies) == "test"


def test_approval_needs_every_item_and_a_name(studies: Path) -> None:
    with pytest.raises(review.ReviewError, match="checklist not complete: editorial"):
        review.approve(studies, by="ana", checked=[c for c in review.CHECKS if c != "editorial"])
    with pytest.raises(review.ReviewError, match="who approves"):
        review.approve(studies, by=" ", checked=list(review.CHECKS))
    record = _approve(studies)
    assert record["approved_by"] == "ana" and review.read_meta(studies)["status"] == "published" and review.is_approved(studies)
    assert json.loads((studies / "review.json").read_text())["digest"] == review.content_digest(studies)


def test_editing_after_approval_removes_the_approval(studies: Path) -> None:
    _approve(studies)
    (studies / "report.pt.qmd").write_text("# Relatório\n\nmudou depois de aprovado\n", encoding="utf-8")
    assert not review.is_approved(studies)
    assert review.packet(studies)["stale_approval"] is True
    assert review.mark_ready(studies) == "ready_for_review"


def test_a_legacy_approval_says_so(studies: Path) -> None:
    record = review.approve_legacy(studies, by="ana")
    assert record["legacy"] is True and record["checked"] == [] and "before the review gate" in record["note"]
    assert review.is_approved(studies)


def test_requesting_changes_reopens_the_study_with_the_comment(studies: Path) -> None:
    s = state.load(SLUG)
    s["completed_phases"] = list(range(1, 9))
    state.save(SLUG, s)
    review.mark_ready(studies)

    review.request_changes(SLUG, "A conclusão sobre as listas de espera é forte demais.", phase=6, root=studies.parent)
    s = state.load(SLUG)
    assert s["completed_phases"] == [1, 2, 3, 4, 5] and s["current_phase"] == 6
    assert s["phases"]["6"]["status"] == "pending" and s["phases"]["8"]["attempts"] == 0
    assert review.read_meta(studies)["status"] == "in_progress"
    assert "listas de espera" in (studies / "decisions.md").read_text(encoding="utf-8")
    with pytest.raises(review.ReviewError, match="say what to change"):
        review.request_changes(SLUG, "  ", root=studies.parent)


def test_complete_phase_8_marks_the_study_ready(studies: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(state.CHECKS, 8, lambda slug: (True, []))
    s = state.load(SLUG)
    s["completed_phases"] = list(range(1, 8))
    state.save(SLUG, s)
    state.start_phase(SLUG, 8)
    assert state.complete_phase(SLUG, 8) == (True, [])
    assert review.read_meta(studies)["status"] == "ready_for_review"


def test_cli_show_and_approve_needs_confirmation(studies: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    assert review.main(["show", SLUG]) == 0
    assert "removed_claims" in capsys.readouterr().out
    assert review.main(["approve", SLUG, "--by", "ana"]) == 2  # no --confirm-all
    assert review.main(["approve", SLUG, "--by", "ana", "--confirm-all"]) == 0
    assert review.is_approved(studies)


def test_cli_legacy_is_recorded_by_the_author_and_needs_a_name(studies: Path, capsys: pytest.CaptureFixture) -> None:
    assert review.main(["legacy", SLUG]) == 2
    assert review.main(["legacy", SLUG, "--by", "ana"]) == 0
    assert "not reviewed with the checklist" in capsys.readouterr().out
    assert json.loads((studies / "review.json").read_text())["legacy"] is True


def test_tags_do_not_change_the_approved_digest(tmp_path) -> None:
    import yaml

    from common import review as rv

    d = tmp_path / "s"
    d.mkdir()
    meta = {"title_pt": "a", "title_en": "b", "summary_pt": "c", "summary_en": "d"}
    (d / "study.yml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    plain = rv.content_digest(d)
    (d / "study.yml").write_text(yaml.safe_dump({**meta, "tags": ["pilot"]}), encoding="utf-8")
    assert rv.content_digest(d) == plain, "a label is not content: tagging must not void an approval"
    (d / "study.yml").write_text(yaml.safe_dump({**meta, "title_pt": "changed"}), encoding="utf-8")
    assert rv.content_digest(d) != plain
