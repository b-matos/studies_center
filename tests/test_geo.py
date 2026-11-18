"""common.geo: NUTS boundaries (committed), label to code mapping per NUTS version, and the map checks."""
from __future__ import annotations

import csv
import json

import pandas as pd
import pytest

from common import chartkinds, geo


def test_committed_boundaries_have_the_expected_units_and_attribution() -> None:
    expected = {("2021", 2): 7, ("2021", 3): 25, ("2024", 2): 9, ("2024", 3): 26}
    for (version, level), count in expected.items():
        collection = json.loads(geo.geo_path(version, level).read_text(encoding="utf-8"))
        assert len(collection["features"]) == count, (version, level)
        for feature in collection["features"]:
            props = feature["properties"]
            assert props["nuts_id"].startswith("PT") and props["version"] == version and props["level"] == level
            assert props["shifted"] == props["nuts_id"].startswith(("PT20", "PT30"))
    sources = list(csv.DictReader((geo.GEO_DIR / "SOURCES.csv").open(encoding="utf-8")))
    assert len(sources) == 4 and all("EuroGeographics" in r["attribution"] and r["source_sha256"] for r in sources)


def test_prepare_features_keeps_portugal_shifts_islands_and_rounds() -> None:
    def feature(nuts_id: str, country: str, lon: float, lat: float) -> dict:
        ring = [[lon, lat], [lon + 1, lat], [lon + 1, lat + 1], [lon, lat]]
        return {"type": "Feature", "properties": {"NUTS_ID": nuts_id, "CNTR_CODE": country, "NAME_LATN": nuts_id.lower()},
                "geometry": {"type": "Polygon", "coordinates": [ring]}}

    raw = {"features": [feature("PT11", "PT", -8.123456, 41.0), feature("PT200", "PT", -28.0, 38.5), feature("ES11", "ES", -7.0, 42.0)]}
    out = geo.prepare_features(raw, "2024", 3)
    ids = [f["properties"]["nuts_id"] for f in out["features"]]
    assert ids == ["PT11", "PT200"]  # Spain dropped, sorted
    mainland, azores = out["features"]
    assert mainland["geometry"]["coordinates"][0][0] == [-8.123, 41.0] and mainland["properties"]["shifted"] is False
    assert azores["geometry"]["coordinates"][0][0] == [-13.7, 40.0] and azores["properties"]["shifted"] is True


def test_the_same_label_maps_to_different_units_in_different_nuts_versions() -> None:
    assert geo.region_code("Centro", "2021", 2) == "PT16"
    assert geo.region_code("Centro", "2024", 2) == "PT19"
    assert geo.region_code("Grande Lisboa", "2021", 2) is None  # only exists from NUTS 2024
    assert geo.region_code("Grande Lisboa", "2024", 2) == "PT1A"
    assert geo.region_code("Área Metropolitana de Lisboa", "2021", 2) == "PT17"
    assert geo.region_code("região autónoma dos açores", "2024", 2) == "PT20"  # case and accents
    assert geo.region_code("PT1C", "2024", 2) == "PT1C"  # a code passes through
    assert geo.region_code("Oeste", "2024", 3) == "PT1D1" and geo.region_code("Oeste", "2024", 2) is None


def test_add_region_codes_and_detect_nuts() -> None:
    df = pd.DataFrame({"region": ["Norte", "Grande Lisboa", "Atlantis", "Norte"], "value": [1, 2, 3, 4]})
    coded = geo.add_region_codes(df, "2024", 2)
    assert list(coded["region_code"]) == ["PT11", "PT1A", "", "PT11"]
    best = geo.detect_nuts(["Norte", "Grande Lisboa", "Península de Setúbal", "Oeste e Vale do Tejo"])[0]
    assert best[:2] == ("2024", 2) and best[2] == 1.0


def test_unknown_boundaries_raise_a_useful_error() -> None:
    with pytest.raises(ValueError, match="common.geo build"):
        geo.units("1999", 2)


def _frame(n_regions: int, unit: str = "%", n_dates: int = 2, region_version: str = "2024", level: int = 2) -> pd.DataFrame:
    codes = list(geo.units(region_version, level))[:n_regions]
    rows = [{"date": f"{2020 + i}-01-01", "region": c, "region_code": c, "sex": "T", "age": "", "indicator": "x", "value": 1.0 + j, "unit": unit}
            for i in range(n_dates) for j, c in enumerate(codes)]
    return pd.DataFrame(rows)


def test_a_map_needs_coded_regions_a_rate_and_comparable_coverage() -> None:
    assert "map" in chartkinds.allowed_kinds(chartkinds.shape_of(_frame(7)))
    assert "map" not in chartkinds.allowed_kinds(chartkinds.shape_of(_frame(4))), "too few regions"
    for count_unit in ("N", "NR", "Nº", "hab", "persons"):
        assert "map" not in chartkinds.allowed_kinds(chartkinds.shape_of(_frame(7, unit=count_unit))), count_unit
    for rate_unit in ("%", "P_HTHAB", "N_1000", "years"):
        assert "map" in chartkinds.allowed_kinds(chartkinds.shape_of(_frame(7, unit=rate_unit))), rate_unit
    sparse = _frame(7)
    latest = sparse["date"].max()
    sparse = sparse[~((sparse["date"] == latest) & sparse["region_code"].isin(list(geo.units("2024", 2))[:3]))]  # 4 of 7 at the latest date
    assert "map" not in chartkinds.allowed_kinds(chartkinds.shape_of(sparse)), "regions missing at the latest date"
    assert "map" not in chartkinds.allowed_kinds(chartkinds.shape_of(_frame(7).drop(columns="region_code")))


def test_map_entries_name_their_boundaries_and_use_their_codes() -> None:
    df = _frame(7)
    ok = {"kind": "map", "why": "taxa por região NUTS II no último ano", "geo": "nuts2024_2"}
    assert chartkinds.kind_problems("c", ok, df) == []
    assert "precisa de `geo`" in chartkinds.kind_problems("c", {**ok, "geo": None}, df)[0]
    assert "precisa de `geo`" in chartkinds.kind_problems("c", {**ok, "geo": "nuts1999_2"}, df)[0]
    wrong_version = chartkinds.kind_problems("c", {**ok, "geo": "nuts2021_2"}, df)
    assert "não são unidades de NUTS 2021" in wrong_version[0]
    counts = chartkinds.kind_problems("c", ok, _frame(7, unit="N"))
    assert "não serve" in counts[0] and "taxa" in counts[0]
