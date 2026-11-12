"""common.sources.dadosgov: dados.gov.pt catalogue client (mocked HTTP, no network)."""
from __future__ import annotations

import httpx
import pytest

from common import checks, probe
from common.sources import dadosgov

DATASET = {
    "id": "abc123", "slug": "obitos-por-causa", "title": "Óbitos por causa", "license": "cc-by", "page": "https://dados.gov.pt/datasets/obitos-por-causa",
    "organization": {"name": "Direção-Geral da Saúde", "slug": "direcao-geral-da-saude"}, "frequency": "annual",
    "temporal_coverage": {"start": "2010-01-01", "end": "2024-12-31"}, "last_modified": "2025-03-01T10:00:00+00:00",
    "resources": [
        {"id": "r1", "title": "Dados", "format": "csv", "url": "https://dgs.example/obitos.csv",
         "latest": "https://dados.gov.pt/api/1/datasets/r/r1", "filesize": 2048, "last_modified": "2025-03-01T10:00:00+00:00"},
        {"id": "r2", "title": "Relatório", "format": "pdf", "url": "https://dgs.example/r.pdf", "latest": "https://dados.gov.pt/api/1/datasets/r/r2"},
    ],
}


@pytest.fixture
def portal(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_get(url, params=None, timeout=None, follow_redirects=None):
        calls.append((url, params))
        path = url.removeprefix(dadosgov.BASE_URL)
        if path == "/datasets/":
            return httpx.Response(200, json={"data": [DATASET], "total": 1}, request=httpx.Request("GET", url))
        if path == "/datasets/obitos-por-causa/":
            return httpx.Response(200, json=DATASET, request=httpx.Request("GET", url))
        if path == "/organizations/direcao-geral-da-saude/":
            return httpx.Response(200, json={"id": "org42"}, request=httpx.Request("GET", url))
        return httpx.Response(404, json={}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(dadosgov.time, "sleep", lambda s: None)
    return calls


def test_search_parses_datasets_and_resolves_the_organisation_slug(portal) -> None:
    datasets, total = dadosgov.search("óbitos", organization="direcao-geral-da-saude", limit=5)
    assert total == 1 and datasets[0].slug == "obitos-por-causa"
    assert datasets[0].organization == "Direção-Geral da Saúde" and datasets[0].temporal_coverage == "2010-01-01..2024-12-31"
    assert portal[-1][1]["organization"] == "org42"  # the filter takes the id, not the slug


def test_tabular_resources_and_stable_latest_url(portal) -> None:
    ds = dadosgov.get_dataset("obitos-por-causa")
    assert [r.format for r in ds.tabular_resources()] == ["csv"]
    assert ds.tabular_resources()[0].latest == "https://dados.gov.pt/api/1/datasets/r/r1"
    assert "latest: https://dados.gov.pt/api/1/datasets/r/r1" in dadosgov.format_dataset(ds, detail=True)


@pytest.mark.parametrize(("license_id", "passes"), [
    ("cc-by", True), ("cc-zero", True), ("odc-by", True), ("odc-pddl", True), ("other-pd", True),
    ("cc-by-sa", False), ("odc-odbl", False), ("cc-by-nc", False), ("cc-by-nc-nd", False),
    ("other-open", False), ("other-at", False), ("notspecified", False), ("unknown", False), ("something-new", False),
])
def test_license_text_passes_the_publication_gate_only_when_clearly_open(license_id: str, passes: bool) -> None:
    text = dadosgov.license_text(license_id)
    allowed = bool(checks.ALLOWED_LICENSE.search(text)) and not checks.BLOCKED_LICENSE.search(text)
    assert allowed is passes, text


def test_outage_is_reported_as_transient_not_as_a_missing_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", down)
    monkeypatch.setattr(dadosgov.time, "sleep", lambda s: None)
    with pytest.raises(dadosgov.DadosGovUnavailable) as info:
        dadosgov.get_dataset("x")
    assert probe.is_transient(info.value)
    assert dadosgov.main(["show", "x"]) == 3


def test_probe_dadosgov_lists_the_dataset_and_tests_the_first_tabular_resource(portal, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    monkeypatch.setattr(probe, "probe_url", lambda url: seen.append(url) or f"OK {url}")
    out = probe.probe_dadosgov("obitos-por-causa")
    assert "licence for sources.csv: CC BY 4.0 (dados.gov.pt)" in out
    assert seen == ["https://dados.gov.pt/api/1/datasets/r/r1"]
