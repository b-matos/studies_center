"""Client for Eurostat's SDMX data API, via the sdmx1 library."""
from __future__ import annotations

import pandas as pd
import sdmx

_CLIENT = sdmx.Client("ESTAT")


def fetch_dataset(dataset_code: str, key: dict[str, str] | None = None, params: dict[str, str] | None = None) -> pd.DataFrame:
    """Fetch an Eurostat dataset (e.g. 'DEMO_MLEXPEC') and return it as a long DataFrame.

    Eurostat's own catalogue lists codes in lowercase, but the sdmx1 client only resolves
    them in uppercase (a lowercase code raises a confusing KeyError) — normalized here so
    callers don't need to know that.
    """
    message = _CLIENT.data(dataset_code.upper(), key=key or {}, params=params or {})
    data = sdmx.to_pandas(message)
    return data.reset_index(name="value")
