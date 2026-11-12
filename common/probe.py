"""Cheap, compact access test for a candidate data source (no LLM summarization involved).

A WebFetch of a data page or API response costs thousands of tokens and still returns a
model's paraphrase. This prints only what the data-researcher needs to fill a row of
sources.d/<axis>.csv: does it answer, what format, what columns, what time range.

    uv run python -m common.probe eurostat:DEMO_MLEXPEC [geo=PT+EU27_2020 sex=T ...]
    uv run python -m common.probe ine:0008459
    uv run python -m common.probe dadosgov:<dataset-slug-or-id>   (dados.gov.pt catalogue)
    uv run python -m common.probe https://example.org/file.csv
"""
from __future__ import annotations

import io
import sys

import httpx
import pandas as pd

PREVIEW_BYTES = 200_000
MAX_LISTED = 10


def _dims(df: pd.DataFrame, skip: set[str]) -> list[str]:
    lines = []
    for column in df.columns:
        if column in skip:
            continue
        values = sorted(map(str, df[column].dropna().unique()))
        extra = f" ... (+{len(values) - MAX_LISTED})" if len(values) > MAX_LISTED else ""
        lines.append(f"  {column} ({len(values)}): {', '.join(values[:MAX_LISTED])}{extra}")
    return lines


def is_transient(exc: Exception) -> bool:
    """Timeouts, connection errors, 429 and 5xx say nothing about whether a source exists."""
    from common.sources.dadosgov import DadosGovUnavailable
    from common.sources.ine import IneUnavailable

    if isinstance(exc, IneUnavailable | DadosGovUnavailable | httpx.TimeoutException | httpx.ConnectError):
        return True
    response = getattr(exc, "response", None)
    return response is not None and (response.status_code == 429 or response.status_code >= 500)


def probe_eurostat(code: str, key: dict[str, str]) -> str:
    """Light access test: only the first and the latest observation of each series, and Portugal
    only when the dataset has a `geo` dimension. A full download of a big dataset (weekly
    regional mortality, for one) takes minutes and proves nothing more than this does.
    A key given on the command line replaces the default `geo=PT` filter."""
    from common.sources.eurostat import fetch_dataset

    keys = [key] if key else [{"geo": "PT"}, None]
    latest = first = None
    for attempt in keys:
        try:
            latest = fetch_dataset(code, key=attempt, params={"lastNObservations": 1})
            first = fetch_dataset(code, key=attempt, params={"firstNObservations": 1})
            break
        except ValueError:
            raise
        except Exception:
            if attempt is keys[-1]:
                raise  # e.g. the dataset has no `geo` dimension: the unfiltered attempt decides
    period = "TIME_PERIOD" if "TIME_PERIOD" in latest.columns else None
    header = (
        f"OK eurostat:{code.upper()} (light probe: geo=PT, first/latest observation) "
        f"series-rows={len(latest)} columns={list(latest.columns)}"
    )
    lines = [header]
    if period:
        lines.append(f"time range: {first[period].min()} .. {latest[period].max()}")
    lines += _dims(latest, {period, "value"} - {None})
    return "\n".join(lines)


def probe_ine(varcd: str) -> str:
    from common.sources.ine import fetch_indicator

    payload = fetch_indicator(varcd)[0]
    periods = list(payload.get("Dados", {}))
    sample = next(iter(payload["Dados"].values()), [{}])[0] if periods else {}
    return "\n".join([
        f"OK ine:{varcd} '{payload.get('IndicadorDsg', '?')}'",
        f"last update: {payload.get('DataUltimoAtualizacao')} | latest period: {payload.get('UltimoPref')}",
        f"periods ({len(periods)}): {periods[:MAX_LISTED]}",
        f"row fields: {sorted(sample)}",
    ])


def probe_dadosgov(dataset: str) -> str:
    """Catalogue entry (publisher, licence, resources) plus an access test of the first tabular resource."""
    from common.sources import dadosgov

    ds = dadosgov.get_dataset(dataset)
    lines = [f"OK dadosgov:{ds.slug}", dadosgov.format_dataset(ds, detail=True)]
    tabular = ds.tabular_resources()
    if not tabular:
        lines.append("no csv/json/xlsx resource: not usable as a flat table; open the page by hand only if it is the sole source")
    else:
        lines.append(f"access test of the first tabular resource ({tabular[0].format}):")
        lines.append(probe_url(tabular[0].latest))
    return "\n".join(lines)


def probe_url(url: str) -> str:
    with httpx.Client(follow_redirects=True, timeout=30.0) as client, client.stream("GET", url) as response:
        content_type = response.headers.get("content-type", "?")
        size = response.headers.get("content-length", "?")
        head = next(response.iter_bytes(PREVIEW_BYTES), b"")
        status = response.status_code
        if status == 429 or status >= 500:  # the server's problem, not proof that the source is missing
            raise httpx.HTTPStatusError(f"HTTP {status}", request=response.request, response=response)
    lines = [f"{'OK' if status < 400 else 'FAIL'} {url} status={status} type={content_type} bytes={size}"]
    if status >= 400:
        return "\n".join(lines)
    if "csv" in content_type or url.lower().endswith(".csv"):
        frame = pd.read_csv(io.BytesIO(head), nrows=200)
        lines.append(f"columns: {list(frame.columns)}")
        lines.append(frame.head(3).to_string(index=False))
    elif "json" in content_type:
        lines.append(f"json preview: {head[:300].decode('utf-8', 'replace')}")
    else:
        lines.append("not tabular; open it by hand only if it is the sole source")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    target, extra = sys.argv[1], sys.argv[2:]
    try:
        if target.startswith("eurostat:"):
            print(probe_eurostat(target.split(":", 1)[1], dict(a.split("=", 1) for a in extra)))
        elif target.startswith("ine:"):
            print(probe_ine(target.split(":", 1)[1]))
        elif target.startswith("dadosgov:"):
            print(probe_dadosgov(target.split(":", 1)[1]))
        else:
            print(probe_url(target))
    except Exception as exc:
        if is_transient(exc):
            print(f"TRANSIENT {target}: {type(exc).__name__}. The source was NOT shown to be missing: "
                  "do not mark it excluded; leave this unit unfinished and report it so it is retried later.")
            return 3
        print(f"FAIL {target}: {type(exc).__name__}: {exc}"[:400])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
