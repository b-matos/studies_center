"""Client for the WHO Global Health Observatory (GHO) OData API.

Docs: https://www.who.int/data/gho/info/gho-odata-api
Endpoint shape: https://ghoapi.azureedge.net/api/<IndicatorCode>
"""
from __future__ import annotations

import httpx
import pandas as pd

BASE_URL = "https://ghoapi.azureedge.net/api"


def fetch_indicator(indicator_code: str, *, timeout: float = 30.0) -> pd.DataFrame:
    """Fetch a WHO GHO indicator (e.g. 'WHOSIS_000001') and return it as a DataFrame."""
    with httpx.Client(timeout=timeout) as client:
        response = client.get(f"{BASE_URL}/{indicator_code}")
        response.raise_for_status()
        payload = response.json()
    return pd.DataFrame(payload.get("value", []))
