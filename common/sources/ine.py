"""Client for INE's public JSON API (Instituto Nacional de Estatística).

Docs: https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_api
Endpoint shape: https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd=<code>&Dim1=<period>&lang=PT
"""
from __future__ import annotations

import httpx

BASE_URL = "https://www.ine.pt/ine/json_indicador/pindica.jsp"


def fetch_indicator(varcd: str, *, dim1: str | None = None, lang: str = "PT", timeout: float = 30.0) -> dict:
    """Fetch one INE indicator by its varcd code. dim1, when given, pins a period (e.g. 'S7A2022')."""
    params = {"op": "2", "varcd": varcd, "lang": lang}
    if dim1 is not None:
        params["Dim1"] = dim1
    with httpx.Client(timeout=timeout) as client:
        response = client.get(BASE_URL, params=params)
        response.raise_for_status()
        return response.json()
