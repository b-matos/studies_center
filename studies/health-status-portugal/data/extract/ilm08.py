from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_eurostat_units", Path(__file__).with_name("_eurostat_units.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# PT, EU27 and Portuguese NUTS 2 (2016/2021 and 2024 codes, plus legacy NUTS 2013 PT200/PT300)
GEO_KEY = "PT+EU27_2020+PT11+PT15+PT16+PT17+PT18+PT19+PT20+PT30"


def build(study_dir):
    return _mod.build_units(study_dir, "ilm08", "hlth_cd_asdr2", "standardised_death_rate",
                            [], "ilm08_eurostat_hlth_cd_asdr2.csv", geo_key=GEO_KEY)
