from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_eurostat_multi", Path(__file__).with_name("_eurostat_multi.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def build(study_dir):
    return _mod.build_multi(study_dir, "eac03", "hlth_silc_08b", "unmet_needs_by_poverty",
                            ["reason", "rskpovth"], "eac03_eurostat_hlth_silc_08b.csv")
