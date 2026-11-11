"""Tests for common.state: resumable, atomically written pipeline state."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from common import checks, state
from common.csv_io import write_csv
from common.download import ManifestEntry, write_manifest
from common.normalize import CANONICAL_COLUMNS
from common.schemas import Claim, DataSource

SLUG = "demo"


@pytest.fixture(autouse=True)
def studies_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "studies"
    (root / SLUG).mkdir(parents=True)
    monkeypatch.setattr(state, "STUDIES_ROOT", root)
    monkeypatch.setattr(checks, "STUDIES_ROOT", root)
    return root


def _complete_through(n: int) -> None:
    """Mark phases 1..n as completed (as complete-phase would have done)."""
    s = state.load(SLUG)
    s["completed_phases"] = list(range(1, n + 1))
    state.save(SLUG, s)


def _make_source_file(root: Path, axis: str, source_id: str) -> None:
    write_csv(
        root / SLUG / "sources.d" / f"{axis}.csv",
        DataSource,
        [DataSource(
            id=source_id, axis=axis, name="n", organisation="INE", url="https://x", format="csv",
            license="CC-BY", temporal_coverage="2000-2020", geographic_coverage="PT", status="tested",
        )],
    )


def _make_extraction(root: Path, source_id: str) -> None:
    clean = root / SLUG / "data" / "clean"
    clean.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({c: ["x"] for c in CANONICAL_COLUMNS}).to_parquet(clean / f"{source_id}.parquet", index=False)
    raw = root / SLUG / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"{source_id}_file.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    import hashlib
    digest = hashlib.sha256((raw / f"{source_id}_file.csv").read_bytes()).hexdigest()
    existing = state.read_manifest(root / SLUG)
    write_manifest(root / SLUG, [*existing, ManifestEntry("https://x", f"{source_id}_file.csv", "2026-01-01", digest, 8)])


def test_init_creates_v2_state_and_is_idempotent() -> None:
    first = state.init(SLUG)
    state.start_phase(SLUG, 1)
    again = state.init(SLUG)
    assert first["schema_version"] == 2
    assert again["current_phase"] == 1 and again["phases"]["1"]["status"] == "in_progress"


def test_save_is_atomic_and_leaves_no_temp_files(studies_root: Path) -> None:
    state.init(SLUG)
    state.start_phase(SLUG, 1)
    leftovers = [p.name for p in (studies_root / SLUG).iterdir() if p.name.startswith(".state-")]
    assert leftovers == []
    assert json.loads((studies_root / SLUG / "state.json").read_text())["current_phase"] == 1


def test_failed_save_keeps_previous_state(studies_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state.init(SLUG)
    before = (studies_root / SLUG / "state.json").read_text()

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(state.os, "replace", boom)
    with pytest.raises(OSError):
        state.start_phase(SLUG, 1)
    assert (studies_root / SLUG / "state.json").read_text() == before
    assert not [p for p in (studies_root / SLUG).iterdir() if p.name.startswith(".state-")]


def test_resume_redoes_in_flight_units_and_lists_what_is_left(studies_root: Path) -> None:
    state.init(SLUG)
    _complete_through(2)
    state.start_phase(SLUG, 3)
    state.plan_units(SLUG, 3, ["s01", "s02", "s03"])
    _make_extraction(studies_root, "s01")
    state.unit_start(SLUG, 3, "s01")
    state.unit_done(SLUG, 3, "s01")
    state.unit_start(SLUG, 3, "s02")  # session dies here (token limit)

    report = state.resume(SLUG)
    assert "next phase: 3" in report
    assert "units done: ['s01']" in report
    assert "units to do: ['s02', 's03']" in report
    assert "interrupted, redo from scratch: ['s02']" in report
    assert state.load(SLUG)["phases"]["3"]["units"]["s02"] == "pending"


def test_unit_done_is_refused_without_real_output(studies_root: Path) -> None:
    state.init(SLUG)
    _complete_through(2)
    state.start_phase(SLUG, 3)
    state.plan_units(SLUG, 3, ["s01"])
    with pytest.raises(state.StateError, match="does not exist"):
        state.unit_done(SLUG, 3, "s01")


def test_unit_done_rejects_non_canonical_parquet(studies_root: Path) -> None:
    state.init(SLUG)
    _complete_through(2)
    state.start_phase(SLUG, 3)
    state.plan_units(SLUG, 3, ["s01"])
    clean = studies_root / SLUG / "data" / "clean"
    clean.mkdir(parents=True)
    pd.DataFrame({"a": [1]}).to_parquet(clean / "s01.parquet", index=False)
    with pytest.raises(state.StateError, match="canonical"):
        state.unit_done(SLUG, 3, "s01")


def test_attempts_persist_across_loads_and_block_after_three() -> None:
    state.init(SLUG)
    _complete_through(3)
    state.start_phase(SLUG, 4)
    for _ in range(3):
        state.fail_attempt(SLUG, 4, ["charts.yml missing"])
    reloaded = state.load(SLUG)
    assert reloaded["phases"]["4"]["attempts"] == 3
    assert reloaded["phases"]["4"]["status"] == "blocked"
    with pytest.raises(state.StateError, match="blocked"):
        state.start_phase(SLUG, 4)
    assert "BLOCKED" in state.resume(SLUG)


def test_phase_2_merges_per_axis_files_and_runs_the_check(studies_root: Path) -> None:
    state.init(SLUG)
    _complete_through(1)
    state.start_phase(SLUG, 2)
    state.plan_units(SLUG, 2, ["mortality", "births"])
    _make_source_file(studies_root, "mortality", "f01")
    _make_source_file(studies_root, "births", "f02")
    state.unit_done(SLUG, 2, "mortality")
    state.unit_done(SLUG, 2, "births")
    ok, problems = state.complete_phase(SLUG, 2)
    assert ok, problems
    assert (studies_root / SLUG / "sources.csv").read_text().count("\n") == 3  # header + 2 rows
    assert state.load(SLUG)["completed_phases"] == [1, 2]


def test_complete_phase_refuses_while_units_remain() -> None:
    state.init(SLUG)
    _complete_through(1)
    state.start_phase(SLUG, 2)
    state.plan_units(SLUG, 2, ["mortality"])
    ok, problems = state.complete_phase(SLUG, 2)
    assert not ok and "units not done" in problems[0]
    assert state.load(SLUG)["phases"]["2"]["attempts"] == 1


def test_phase_7_unit_follows_claim_verification_status(studies_root: Path) -> None:
    claim = Claim(
        id="c001", type="data", text_pt="a", text_en="a", source_id="f01", url="https://x",
        access_date="2026-01-01", excerpt="e", source_nature="primary", location="Q1",
    )
    write_csv(studies_root / SLUG / "claims.csv", Claim, [claim])
    state.init(SLUG)
    _complete_through(6)
    state.start_phase(SLUG, 7)
    state.plan_units(SLUG, 7, ["c001"])
    with pytest.raises(state.StateError, match="pending"):
        state.unit_done(SLUG, 7, "c001")
    write_csv(studies_root / SLUG / "claims.csv", Claim, [claim.model_copy(update={"verification_status": "confirmed"})])
    state.unit_done(SLUG, 7, "c001")
    assert state.load(SLUG)["phases"]["7"]["units"]["c001"] == "done"


def test_plan_units_keeps_existing_unit_state() -> None:
    state.init(SLUG)
    _complete_through(2)
    state.start_phase(SLUG, 3)
    state.plan_units(SLUG, 3, ["s01"])
    state.unit_start(SLUG, 3, "s01")
    state.plan_units(SLUG, 3, ["s01", "s02"])
    assert state.load(SLUG)["phases"]["3"]["units"] == {"s01": "in_progress", "s02": "pending"}


def test_cli_resume_and_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    assert state.main(["resume", SLUG]) == 0
    assert "no state" in capsys.readouterr().out
    state.init(SLUG)
    assert state.main(["unit-done", SLUG, "3", "nope"]) == 1
    assert "refused" in capsys.readouterr().err


def test_phases_cannot_be_skipped() -> None:
    state.init(SLUG)
    with pytest.raises(state.StateError, match=r"not completed"):
        state.start_phase(SLUG, 3)


def test_init_creates_the_study_folder_and_yml_once(studies_root: Path) -> None:
    import yaml

    assert state.main(["init", "new-study", "--title-pt", "Saúde", "--title-en", "Health"]) == 0
    meta = yaml.safe_load((studies_root / "new-study" / "study.yml").read_text(encoding="utf-8"))
    assert (meta["title_pt"], meta["title_en"], meta["status"]) == ("Saúde", "Health", "in_progress")
    assert "current_phase" not in meta  # the phase lives in state.json only
    assert (studies_root / "new-study" / "state.json").exists()
    state.main(["init", "new-study", "--title-pt", "Other"])  # idempotent: nothing is overwritten
    assert yaml.safe_load((studies_root / "new-study" / "study.yml").read_text(encoding="utf-8"))["title_pt"] == "Saúde"


def test_unit_start_reopens_a_done_unit_that_is_being_redone() -> None:
    state.init(SLUG)
    _complete_through(1)
    state.start_phase(SLUG, 2)
    state.plan_units(SLUG, 2, ["mortality"])
    s = state.load(SLUG)
    s["phases"]["2"]["units"]["mortality"] = "done"
    state.save(SLUG, s)
    state.unit_start(SLUG, 2, "mortality")  # the check failed and the orchestrator relaunches it
    assert state.load(SLUG)["phases"]["2"]["units"]["mortality"] == "in_progress"


def test_unit_start_of_the_pt_report_writes_the_chart_summary(studies_root: Path) -> None:
    import yaml

    state.init(SLUG)
    study = studies_root / SLUG
    (study / "analysis" / "out").mkdir(parents=True)
    (study / "data" / "clean").mkdir(parents=True)
    (study / "analysis" / "out" / "c.json").write_text(
        json.dumps([{"date": "2020-01-01", "region": "Portugal", "value": 1.0}]), encoding="utf-8"
    )
    (study / "analysis" / "charts.yml").write_text(yaml.safe_dump({"c": {"data_file": "c.json"}}), encoding="utf-8")
    _complete_through(5)
    state.start_phase(SLUG, 6)
    state.plan_units(SLUG, 6, ["pt", "en"])

    state.unit_start(SLUG, 6, "en")
    assert not (study / "analysis" / "summary.md").exists()  # only the pt unit needs it
    state.unit_start(SLUG, 6, "pt")
    assert "## c" in (study / "analysis" / "summary.md").read_text(encoding="utf-8")
    assert (study / "analysis" / "series.csv").exists()
