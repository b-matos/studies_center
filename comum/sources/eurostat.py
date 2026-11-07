"""Client for Eurostat's SDMX data API, via the sdmx1 library."""
from __future__ import annotations

import pandas as pd
import sdmx

_CLIENT = sdmx.Client("ESTAT")


def fetch_dataset(dataset_code: str, key: dict[str, str] | None = None, params: dict[str, str] | None = None) -> pd.DataFrame:
    """Fetch an Eurostat dataset (e.g. 'hlth_cd_asdr2') and return it as a long DataFrame."""
    message = _CLIENT.data(dataset_code, key=key or {}, params=params or {})
    data = sdmx.to_pandas(message)
    return data.reset_index(name="valor")
