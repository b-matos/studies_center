"""Data and internal claims are proven by code (provenance chain), not by a portal's page text."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from common import checks, provenance, verify
from common.csv_io import read_csv, write_csv
from common.download import record_file
from common.schemas import Claim, DataSource

INE_URL = "https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd=0008459&lang=PT"
EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/DEMO_MLEXPEC"
INE_PAGE = "https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_indicadores&indOcorrCod=0008459"
EUROSTAT_PAGE = "https://ec.europa.eu/eurostat/databrowser/view/demo_mlexpec/default/table"
TITLE = "Esperança de vida à nascença (Metodologia 2007 - Anos) por Local de residência"


def _source(sid: str, url: str, name: str) -> DataSource:
    return DataSource(id=sid, axis="x", name=name, organisation="o", url=url, format="csv", license="CC BY 4.0",
                      temporal_coverage="2000-2010", geographic_coverage="PT", status="tested")


def _claim(cid: str, sid: str, **kw) -> Claim:
    base = {"id": cid, "type": "data", "text_pt": "t", "text_en": "t", "value": "70.0", "unit": "anos", "source_id": sid,
            "url": "", "access_date": "2026-11-11", "excerpt": "", "source_nature": "primary", "location": "Q1",
            "clean_file": f"{sid}.parquet",
            "calculation": "df.query(\"region=='Portugal' and date=='2000-01-01'\").value.iloc[0]"}
    return Claim(**{**base, **kw})


@pytest.fixture
def study(tmp_path: Path) -> Path:
    root = tmp_path / "studies" / "demo"
    (root / "data" / "clean").mkdir(parents=True)
    write_csv(root / "sources.csv", DataSource, [_source("ine1", INE_PAGE, "INE x"), _source("eu1", EUROSTAT_PAGE, "Eurostat y")])
    record_file(root, INE_URL, "ine1_ine_0008459.json", json.dumps([{"IndicadorDsg": TITLE + " (NUTS 2013); Anual - INE"}]).encode())
    record_file(root, EUROSTAT_URL, "eu1_eurostat_demo_mlexpec.csv", b"freq,geo,TIME_PERIOD,value\nA,PT,2000,70.0\n")
    for sid in ("ine1", "eu1"):
        pd.DataFrame({"date": ["2000-01-01"], "region": ["Portugal"], "sex": ["T"], "age": [""], "indicator": ["le"],
                      "value": [70.0], "unit": ["YR"], "source_id": [sid]}).to_parquet(root / "data" / "clean" / f"{sid}.parquet")
    return root


def test_canonical_excerpt_is_an_ine_title_or_a_dataset_code(study: Path) -> None:
    assert provenance.canonical_excerpt(study, "eu1") == "DEMO_MLEXPEC"
    ine = provenance.canonical_excerpt(study, "ine1")
    assert ine.startswith("Esperança de vida à nascença") and len(ine.split()) < 15


def test_normalize_fills_url_and_excerpt_of_data_claims_only(study: Path) -> None:
    fact = _claim("c003", "eu1", type="fact", url="https://y.example/p", excerpt="kept")
    write_csv(study / "claims.csv", Claim, [_claim("c001", "eu1"), _claim("c002", "ine1", excerpt="invented"), fact])
    assert provenance.normalize_data_claims(study) == 2
    c1, c2, c3 = read_csv(study / "claims.csv", Claim)
    assert (c1.url, c1.excerpt) == (EUROSTAT_PAGE, "DEMO_MLEXPEC")
    assert c2.url == INE_PAGE and c2.excerpt.startswith("Esperança de vida")
    assert (c3.url, c3.excerpt) == ("https://y.example/p", "kept")
    assert provenance.normalize_data_claims(study) == 0  # idempotent
    assert all(provenance.data_chain_problems(study, c) == [] for c in (c1, c2))


def test_chain_detects_each_break(study: Path) -> None:
    write_csv(study / "claims.csv", Claim, [_claim("c001", "eu1")])
    provenance.normalize_data_claims(study)
    claim = read_csv(study / "claims.csv", Claim)[0]
    assert provenance.data_chain_problems(study, claim) == []

    assert any("not in the provenance chain" in p for p in provenance.data_chain_problems(study, claim.model_copy(update={"excerpt": "invented"})))
    assert any("url differs" in p for p in provenance.data_chain_problems(study, claim.model_copy(update={"url": "https://other"})))
    assert any("source_id" in p for p in provenance.data_chain_problems(study, claim.model_copy(update={"clean_file": "ine1.parquet"})))
    (study / "data" / "raw" / "eu1_eurostat_demo_mlexpec.csv").write_bytes(b"tampered")
    assert provenance.data_chain_problems(study, claim), "a changed raw file must break the chain"


def test_verify_study_confirms_data_claims_without_any_web_request(study: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*args, **kwargs):
        raise AssertionError("a data claim must not fetch a web page")

    monkeypatch.setattr(verify, "_fetch_text", no_network)
    write_csv(study / "claims.csv", Claim, [_claim("c001", "eu1"), _claim("c002", "ine1")])
    provenance.normalize_data_claims(study)
    results = verify.verify_study(study)
    assert all(verify.is_confirmed(r) for r in results), [r.detail for r in results]


def test_internal_claim_quotes_a_repository_file(study: Path) -> None:
    (study / "decisions.md").write_text("O eixo de mortalidade semanal foi excluído por falta de dados.", encoding="utf-8")
    ok = _claim("c001", "eu1", type="fact", source_nature="internal", url="studies/demo/decisions.md",
                excerpt="mortalidade semanal foi excluído", value=None, clean_file=None, calculation=None)
    assert provenance.internal_problems(study, ok) == []
    assert provenance.internal_problems(study, ok.model_copy(update={"excerpt": "inventado"}))
    assert provenance.internal_problems(study, ok.model_copy(update={"url": "studies/demo/nao_existe.md"}))
    assert provenance.internal_problems(study, ok.model_copy(update={"url": "https://x.org"}))
    assert provenance.internal_problems(study, ok.model_copy(update={"url": "../../etc/passwd"}))


def test_claim_rows_reject_non_http_urls_unless_internal_and_unrecomputable_data(study: Path) -> None:
    bad_url = _claim("c001", "eu1", type="event", url="studies/demo/event_links.csv", excerpt="x")
    no_calc = _claim("c002", "eu1", calculation=None)
    problems = checks.claim_row_problems(study, [bad_url, no_calc])
    assert any("c001" in p and "internal" in p for p in problems)
    assert any("c002" in p and "recalculável" in p for p in problems)
