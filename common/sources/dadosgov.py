"""Client for the Portuguese open data portal, dados.gov.pt (a udata instance, REST API v1).

The portal is a catalogue: each dataset belongs to an organisation (INE, DGS, SPMS, ACSS, municipalities...),
carries a licence chosen by the publisher, and lists resources (CSV, XLSX, JSON, links). Many bodies that
have no API of their own publish here, so it is where the data-researcher looks after INE and Eurostat.

    uv run python -m common.sources.dadosgov search "mortalidade" [--org SLUG] [--limit 10]
    uv run python -m common.sources.dadosgov show <dataset-slug-or-id>
    uv run python -m common.probe dadosgov:<dataset-slug-or-id>

Resources have a stable `latest` URL (https://dados.gov.pt/api/1/datasets/r/<id>) that follows the file when
the publisher replaces it; use that URL as `fetch.url` of an extract spec of kind "http" (see common.extract).

The licence is the publisher's declaration. `license_text` maps it to the wording `common.checks` understands:
only clearly open licences pass the publication gate, while "other", "unspecified" and "unknown" need a human
decision (read the dataset page, then record the licence in sources.csv yourself).
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import httpx

BASE_URL = "https://dados.gov.pt/api/1"
TABULAR_FORMATS = ("csv", "json", "xlsx", "xls")
RETRIES = 3

# udata licence id -> text for sources.csv. Only the first group passes `common.checks.license_problems`.
LICENSE_TEXT = {
    "cc-by": "CC BY 4.0 (dados.gov.pt)",
    "cc-zero": "CC0 (dados.gov.pt)",
    "odc-by": "ODC-BY: reutilização livre com atribuição (dados.gov.pt)",
    "odc-pddl": "Domínio público, ODC PDDL (dados.gov.pt)",
    "other-pd": "Domínio público (licença declarada no dados.gov.pt)",
    "cc-by-sa": "CC BY-SA, share-alike (dados.gov.pt)",
    "odc-odbl": "ODbL, share-alike SA (dados.gov.pt)",
    "cc-by-nc": "CC BY-NC, uso não comercial (dados.gov.pt)",
    "cc-by-nc-nd": "CC BY-NC-ND, uso não comercial e sem derivações (dados.gov.pt)",
    "other-open": "Outra licença aberta, termos a confirmar na fonte (dados.gov.pt)",
    "other-at": "Outra licença com atribuição, termos a confirmar na fonte (dados.gov.pt)",
    "notspecified": "Licença não especificada (dados.gov.pt)",
    "unknown": "Licença desconhecida (dados.gov.pt)",
}


class DadosGovUnavailable(Exception):
    """The portal did not answer (timeout, 5xx, 429) after retries. Says nothing about the dataset."""


@dataclass
class Resource:
    id: str
    title: str
    format: str
    url: str  # the publisher's link
    latest: str  # stable portal link that follows the current file
    filesize: int | None = None
    last_modified: str = ""


@dataclass
class Dataset:
    id: str
    slug: str
    title: str
    organization: str
    license_id: str
    page: str
    frequency: str = ""
    temporal_coverage: str = ""
    last_modified: str = ""
    resources: list[Resource] = field(default_factory=list)

    @property
    def license_text(self) -> str:
        return license_text(self.license_id)

    def tabular_resources(self) -> list[Resource]:
        return [r for r in self.resources if r.format.lower() in TABULAR_FORMATS]


def license_text(license_id: str | None) -> str:
    return LICENSE_TEXT.get(license_id or "", f"Licença '{license_id or 'sem indicação'}' (dados.gov.pt), a confirmar na fonte")


def _get(path: str, params: dict | None = None, *, timeout: float = 30.0) -> dict:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            response = httpx.get(f"{BASE_URL}{path}", params=params, timeout=timeout, follow_redirects=True)
            if response.status_code == 429 or response.status_code >= 500:
                raise DadosGovUnavailable(f"HTTP {response.status_code} from dados.gov.pt")
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.ConnectError, DadosGovUnavailable) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise DadosGovUnavailable(f"dados.gov.pt did not answer after {RETRIES} attempts: {last}") from last


def _parse_resource(raw: dict) -> Resource:
    return Resource(
        id=str(raw.get("id", "")), title=str(raw.get("title") or ""), format=str(raw.get("format") or ""),
        url=str(raw.get("url") or ""), latest=str(raw.get("latest") or raw.get("url") or ""),
        filesize=raw.get("filesize"), last_modified=str(raw.get("last_modified") or "")[:10],
    )


def _parse_dataset(raw: dict) -> Dataset:
    org = raw.get("organization") or {}
    coverage = raw.get("temporal_coverage") or {}
    span = f"{str(coverage.get('start') or '')[:10]}..{str(coverage.get('end') or '')[:10]}" if coverage else ""
    return Dataset(
        id=str(raw["id"]), slug=str(raw.get("slug") or raw["id"]), title=str(raw.get("title") or ""),
        organization=str(org.get("name") or org.get("slug") or ""), license_id=str(raw.get("license") or ""),
        page=str(raw.get("page") or ""), frequency=str(raw.get("frequency") or ""), temporal_coverage=span,
        last_modified=str(raw.get("last_modified") or "")[:10],
        resources=[_parse_resource(r) for r in raw.get("resources", [])],
    )


def organization_id(slug_or_id: str) -> str:
    """The search filter wants the organisation's id; accept its slug too (e.g. 'instituto-nacional-de-estatistica')."""
    return str(_get(f"/organizations/{slug_or_id}/")["id"])


def search(query: str, *, organization: str | None = None, limit: int = 10, page: int = 1) -> tuple[list[Dataset], int]:
    """Datasets matching a text query, and the total number of matches."""
    params: dict = {"q": query, "page_size": limit, "page": page}
    if organization:
        params["organization"] = organization_id(organization)
    payload = _get("/datasets/", params)
    return [_parse_dataset(d) for d in payload.get("data", [])], int(payload.get("total", 0))


def get_dataset(slug_or_id: str) -> Dataset:
    return _parse_dataset(_get(f"/datasets/{slug_or_id}/"))


def format_dataset(ds: Dataset, *, detail: bool = False) -> str:
    head = f"{ds.slug} | {ds.organization} | {ds.title[:90]} | {ds.license_id} | updated {ds.last_modified or '?'}"
    if not detail:
        return f"{head} | {len(ds.tabular_resources())} tabular resource(s)"
    lines = [head, f"page: {ds.page}", f"licence for sources.csv: {ds.license_text}",
             f"frequency: {ds.frequency or '?'} | temporal coverage: {ds.temporal_coverage or '?'}"]
    for r in ds.resources:
        size = f" {r.filesize // 1024} KB" if r.filesize else ""
        lines.append(f"  - [{r.format or '?'}] {r.title[:70]}{size} | updated {r.last_modified or '?'}\n    latest: {r.latest}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if args[:1] == ["search"] and len(args) >= 2:
            org = args[args.index("--org") + 1] if "--org" in args else None
            limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10
            datasets, total = search(args[1], organization=org, limit=limit)
            print(f"{total} dataset(s) for '{args[1]}'" + (f" in {org}" if org else "") + f"; showing {len(datasets)}")
            for ds in datasets:
                print(format_dataset(ds))
            return 0
        if args[:1] == ["show"] and len(args) == 2:
            print(format_dataset(get_dataset(args[1]), detail=True))
            return 0
    except DadosGovUnavailable as exc:
        print(f"TRANSIENT dados.gov.pt: {exc}. The dataset was NOT shown to be missing; retry later.")
        return 3
    except httpx.HTTPStatusError as exc:
        print(f"FAIL dados.gov.pt: HTTP {exc.response.status_code} for {exc.request.url}")
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
