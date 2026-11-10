"""verify --apply: confirmed claims are persisted, unresolved ones stay pending (resumable)."""
from __future__ import annotations

from pathlib import Path

import pytest

from common import verify
from common.csv_io import read_csv, write_csv
from common.schemas import Claim


def _claim(claim_id: str, status: str = "pending") -> Claim:
    return Claim(
        id=claim_id, type="fact", text_pt="a", text_en="a", source_id="f1", url=f"https://x/{claim_id}",
        access_date="2026-01-01", excerpt="excerpt", source_nature="primary", location="Q1",
        verification_status=status,
    )


@pytest.fixture
def study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_csv(tmp_path / "claims.csv", Claim, [_claim("c001"), _claim("c002"), _claim("c003", "confirmed")])
    pages = {"https://x/c001": (True, "exact"), "https://x/c002": (False, "not found")}
    monkeypatch.setattr(verify, "verify_excerpt", lambda url, _e: pages.get(url, (True, "exact")))
    return tmp_path


def test_apply_confirms_only_what_code_proved(study: Path) -> None:
    results = verify.verify_study(study, only_pending=True)
    assert [r.claim_id for r in results] == ["c001", "c002"]  # c003 already confirmed: not re-fetched
    unresolved = verify.apply_results(study, results)
    status = {c.id: c.verification_status for c in read_csv(study / "claims.csv", Claim)}
    assert status == {"c001": "confirmed", "c002": "pending", "c003": "confirmed"}
    assert unresolved == ["c002"]
    text = (study / "verification.md").read_text(encoding="utf-8")
    assert "- c001: confirmed (automatic)" in text and "- c002: pending" in text


def test_rerun_keeps_earlier_lines_and_updates_resolved_ones(study: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verify.apply_results(study, verify.verify_study(study, only_pending=True))
    monkeypatch.setattr(verify, "verify_excerpt", lambda _u, _e: (True, "exact"))
    verify.apply_results(study, verify.verify_study(study, only_pending=True))
    text = (study / "verification.md").read_text(encoding="utf-8")
    assert "- c001: confirmed (automatic)" in text and "- c002: confirmed (automatic)" in text
    assert "pending" not in text
