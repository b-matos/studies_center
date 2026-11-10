"""Helper for SNS Transparência (https://www.sns.gov.pt/transparencia/) exports.

SNS Transparência has no stable public API: it publishes dashboards with CSV/XLSX export
links that data-researcher must find and record per-indicator in sources.csv. This module
just wraps the generic download + tabular read, so extractor scripts share one code path.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_export(path: Path) -> pd.DataFrame:
    """Read a CSV or XLSX file previously downloaded from an SNS Transparência export link."""
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)
