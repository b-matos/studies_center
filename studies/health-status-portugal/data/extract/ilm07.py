from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_eurostat_units", Path(__file__).with_name("_eurostat_units.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def build(study_dir):
    return _mod.build_units(study_dir, "ilm07", "demo_minfind", "infant_mortality",
                            [], "ilm07_eurostat_demo_minfind.csv")
