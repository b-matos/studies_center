"""Client for INE's public JSON API (Instituto Nacional de Estatística).

Docs: https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_api
Endpoint shape: https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd=<code>&Dim1=<period>&lang=PT

INE answers bursts of requests with connection timeouts for a while. Several subagents may
probe it at once (separate processes), so requests are spaced through a timestamp file in the
system temp dir, and transient failures (timeouts, 429, 5xx) are retried with a growing pause
before an error is raised. A persistent failure is raised as `IneUnavailable`, which callers
must treat as "try again later", never as "the source does not exist".
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import httpx

BASE_URL = "https://www.ine.pt/ine/json_indicador/pindica.jsp"
MIN_INTERVAL_S = 2.0
RETRY_PAUSES_S = (5.0, 20.0)  # waits before the 2nd and 3rd attempt
USER_AGENT = "studies-center/0.1 (local research tool; polite client)"
_LAST_REQUEST = Path(tempfile.gettempdir()) / "studies_center_ine_last_request"


class IneUnavailable(Exception):
    """INE did not answer after the retries: transient, not evidence that a source is missing."""


def _wait_turn() -> None:
    try:
        wait = MIN_INTERVAL_S - (time.time() - float(_LAST_REQUEST.read_text()))
    except (OSError, ValueError):
        wait = 0.0
    if wait > 0:
        time.sleep(wait)
    _LAST_REQUEST.write_text(str(time.time()))


def fetch_indicator(varcd: str, *, dim1: str | None = None, lang: str = "PT", timeout: float = 30.0) -> dict:
    """Fetch one INE indicator by its varcd code. dim1, when given, pins a period (e.g. 'S7A2022')."""
    params = {"op": "2", "varcd": varcd, "lang": lang}
    if dim1 is not None:
        params["Dim1"] = dim1
    last_error: Exception | None = None
    for attempt, pause in enumerate((0.0, *RETRY_PAUSES_S)):
        if pause:
            time.sleep(pause)
        _wait_turn()
        try:
            with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
                response = client.get(BASE_URL, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                last_error = httpx.HTTPStatusError(f"HTTP {response.status_code}", request=response.request, response=response)
                continue
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_error = exc
    raise IneUnavailable(f"{type(last_error).__name__} after {attempt + 1} attempts: {last_error}")
