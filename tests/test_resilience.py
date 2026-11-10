"""INE retries/throttling, transient failures in probe, and the stricter phase-2 check."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from common import checks, probe
from common.csv_io import write_csv
from common.schemas import DataSource
from common.sources import ine


class _Response:
    def __init__(self, status: int, payload=None) -> None:
        self.status_code, self._payload = status, payload
        self.request = httpx.Request("GET", ine.BASE_URL)

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=self.request, response=self)  # type: ignore[arg-type]


def _client_factory(outcomes: list):
    calls = {"n": 0}

    class Client:
        def __init__(self, **_kwargs) -> None: ...
        def __enter__(self): return self
        def __exit__(self, *_a): return False

        def get(self, *_a, **_k):
            outcome = outcomes[min(calls["n"], len(outcomes) - 1)]
            calls["n"] += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    return Client, calls


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ine.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ine, "_LAST_REQUEST", tmp_path / "last")


def test_ine_retries_transient_failures_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client_factory([httpx.ConnectTimeout("t"), _Response(429), _Response(200, [{"ok": 1}])])
    monkeypatch.setattr(ine.httpx, "Client", client)
    assert ine.fetch_indicator("0008459") == [{"ok": 1}]
    assert calls["n"] == 3


def test_ine_gives_up_with_a_transient_error_not_a_missing_source(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _client_factory([httpx.ConnectTimeout("t")])
    monkeypatch.setattr(ine.httpx, "Client", client)
    with pytest.raises(ine.IneUnavailable, match="ConnectTimeout after 3 attempts"):
        ine.fetch_indicator("0008459")
    assert calls["n"] == 3
    assert probe.is_transient(ine.IneUnavailable("x"))


def test_a_real_404_is_not_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client_factory([_Response(404)])
    monkeypatch.setattr(ine.httpx, "Client", client)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        ine.fetch_indicator("nope")
    assert not probe.is_transient(exc_info.value)


def test_probe_cli_tells_the_agent_not_to_exclude_on_transient_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_varcd: str) -> str:
        raise ine.IneUnavailable("ConnectTimeout after 3 attempts")

    monkeypatch.setattr(probe, "probe_ine", boom)
    monkeypatch.setattr("sys.argv", ["probe", "ine:0008459"])
    assert probe.main() == 3
    assert "NOT shown to be missing" in capsys.readouterr().out


def _source(source_id: str, axis: str, status: str, reason: str | None = None) -> DataSource:
    return DataSource(
        id=source_id, axis=axis, name="n", organisation="INE", url="https://x", format="csv", license="CC-BY",
        temporal_coverage="2000-2020", geographic_coverage="PT", status=status, exclusion_reason=reason,
    )


@pytest.fixture
def study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(checks, "STUDIES_ROOT", tmp_path)
    study_dir = tmp_path / "s"
    study_dir.mkdir()
    (study_dir / "plan.md").write_text(
        "## Perguntas\n1. x\n\n## Eixos\n\n- `mortality` — INE\n- `access` — Eurostat\n", encoding="utf-8")
    return study_dir


def test_phase_2_rejects_timeouts_as_exclusion_reason_and_axes_without_tested_source(study: Path) -> None:
    write_csv(study / "sources.csv", DataSource, [
        _source("f1", "mortality", "excluded", "ConnectTimeout em todas as tentativas"),
        _source("f2", "access", "tested"),
    ])
    ok, problems = checks.check_phase_2("s")
    assert not ok
    assert any("falha possivelmente temporária" in p for p in problems)
    assert any("eixo 'mortality'" in p and "nenhuma fonte testada" in p for p in problems)
    assert not any("'access'" in p for p in problems)


def test_phase_2_accepts_a_definitive_exclusion_when_every_axis_has_a_tested_source(study: Path) -> None:
    write_csv(study / "sources.csv", DataSource, [
        _source("f1", "mortality", "tested"),
        _source("f2", "mortality", "excluded", "HTTP 404: dataset removed"),
        _source("f3", "access", "tested"),
    ])
    assert checks.check_phase_2("s") == (True, [])


def test_phase_2_tolerates_a_timeout_exclusion_when_the_axis_has_another_tested_source(study: Path) -> None:
    write_csv(study / "sources.csv", DataSource, [
        _source("f1", "mortality", "tested"),
        _source("f2", "mortality", "excluded", "Probe excedeu 120 s (timeout)"),  # huge dataset, axis still covered
        _source("f3", "access", "tested"),
    ])
    assert checks.check_phase_2("s") == (True, [])


def test_light_eurostat_probe_asks_for_one_observation_and_falls_back_without_geo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pandas as pd

    calls = []

    def fake_fetch(code, key=None, params=None):
        calls.append((key, params))
        if key == {"geo": "PT"}:
            raise KeyError("no geo dimension")
        return pd.DataFrame({"TIME_PERIOD": ["2020"], "value": [1.0], "sex": ["T"]})

    monkeypatch.setattr("common.sources.eurostat.fetch_dataset", fake_fetch)
    text = probe.probe_eurostat("demo_x", {})
    assert text.startswith("OK eurostat:DEMO_X (light probe")
    assert calls[0] == ({"geo": "PT"}, {"lastNObservations": 1})
    assert (None, {"firstNObservations": 1}) in calls
