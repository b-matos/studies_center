from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_eurostat_units", Path(__file__).with_name("_eurostat_units.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# PT, NUTS 1/2 regions (NUTS 2013, 2021 and 2024 codes) and EU27
GEO_KEY = "PT+PT11+PT15+PT16+PT17+PT18+PT20+PT30"


def build(study_dir):
    return _mod.build_units(study_dir, "eac08", "hlth_rs_bdsrg", "hospital_beds_region",
                            [], "eac08_eurostat_hlth_rs_bdsrg.csv", geo_key=GEO_KEY)
