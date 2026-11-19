"""Build, snapshot and clean the throw-away directory an agent works in during an eval.

The sandbox is a copy of the *working tree* (so an edited prompt in `.claude/agents/` is what gets evaluated) with the
repository's own studies left out, plus the synthetic fixture study from `evals.fixtures`. Nothing here touches the real
`studies/`, `events/` or git history.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

import yaml

from common.csv_io import write_csv
from common.schemas import Claim
from evals import fixtures

REPO = Path(__file__).resolve().parent.parent
COPY_DIRS = (".claude", "common", "server", "site")
COPY_FILES = ("CLAUDE.md", "pyproject.toml", "uv.lock", ".python-version")
SKIP = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache", "_site", "_site_public", ".quarto", "studies", "node_modules", "*.pyc")
SNAPSHOT_ROOTS = ("studies", "events")

VERIFIER_PAGES = {
    "law.html": "<html><body><p>A Lei n.º 12/2012 criou a Rede Hospitalar Integrada e entrou em vigor a 1 de janeiro de 2012.</p></body></html>",
    "report.html": "<html><body><p>O relatório anual de 2019 registou 4 120 internamentos evitáveis no sistema público.</p></body></html>",
    "news.html": "<html><body><p>A ministra anunciou o novo programa de cuidados continuados em março de 2018.</p></body></html>",
}
# (id, page, excerpt, is_fault)
VERIFIER_CLAIMS = [
    ("c001", "law.html", "entrou em vigor a 1 de janeiro de 2012", False),
    ("c002", "report.html", "registou 4 120 internamentos evitáveis", False),
    ("c003", "news.html", "anunciou o novo programa de cuidados continuados", False),
    ("c004", "law.html", "entrou em vigor a 1 de janeiro de 2014", True),  # altered date
    ("c005", "missing.html", "a lei foi publicada em 2012", True),  # dead URL
    ("c006", "law.html", "registou 4 120 internamentos evitáveis", True),  # excerpt exists, on another page
    ("c007", "report.html", "registou 4 210 internamentos evitáveis", True),  # altered number
    ("c008", "law.html", "criou a Rede Hospitalar Integrada", False),
]


def snapshot(root: Path) -> dict[str, str]:
    """sha256 of every file under the snapshot roots (what an agent could have written)."""
    out = {}
    for name in SNAPSHOT_ROOTS:
        base = root / name
        for path in sorted(base.rglob("*")) if base.exists() else []:
            if path.is_file():
                out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def make_sandbox(case: dict, *, port: int | None = None, parent: Path | None = None) -> tuple[Path, dict]:
    """Create the sandbox for one case. Returns (path, params for the graders)."""
    root = Path(tempfile.mkdtemp(prefix="eval-", dir=parent))
    for name in COPY_DIRS:
        shutil.copytree(REPO / name, root / name, ignore=SKIP)
    for name in COPY_FILES:
        shutil.copy2(REPO / name, root / name)
    fixture = case.get("fixture", {})
    study = fixtures.build(root, fixture.get("upto_phase", 4), links=fixture.get("links", False))
    params: dict = {"port": port}
    if fixture.get("summaries"):  # what `common.state unit-start ... 6 pt` produces for the writer
        from common import summarize, trends

        trends.write_trends(study)
        summarize.write_summary(study)
    if fixture.get("pt_report"):  # what the `pt` unit leaves behind, so the `en` unit can be evaluated alone
        fixtures.add_pt_report(study)
    if fixture.get("verifier_claims"):
        params |= _verifier_claims(study, port or 0)
    for pattern in case.get("remove", []):  # paths or globs, relative to the sandbox; directories go with their contents
        for path in sorted(root.glob(pattern), reverse=True):
            shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
    for rel, content in case.get("files", {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(content.replace("{port}", str(port or "")), encoding="utf-8")
    return root, params


def _verifier_claims(study: Path, port: int) -> dict:
    claims = [
        Claim(id=cid, type="fact", text_pt=f"afirmação {cid}", text_en=f"claim {cid}", source_id="s1", url=f"http://127.0.0.1:{port}/{page}",
              access_date="2026-11-18", excerpt=excerpt, source_nature="primary", location="Q1")
        for cid, page, excerpt, _ in VERIFIER_CLAIMS
    ]
    write_csv(study / "claims.csv", Claim, claims)
    import pandas as pd

    return {"faulty_ids": {cid for cid, _, _, fault in VERIFIER_CLAIMS if fault},
            "claims_before": pd.read_csv(study / "claims.csv", dtype=str, keep_default_na=False).to_dict(orient="list")}


PAGE_SETS = {
    "verifier_pages": (VERIFIER_PAGES, {}),
    "researcher_pages": (fixtures.RESEARCHER_PAGES, fixtures.RESEARCHER_STATUS),
    "extractor_pages": ({"data.csv": fixtures.EXTRACTOR_CSV, "page.html": fixtures.EXTRACTOR_PAGE}, {}),
}


def write_pages(directory: Path, name: str = "verifier_pages") -> tuple[Path, dict[str, int]]:
    """Write a named set of fixture pages; returns (directory, paths that answer with a fixed HTTP status instead)."""
    pages, statuses = PAGE_SETS[name]
    directory.mkdir(parents=True, exist_ok=True)
    for filename, body in pages.items():
        (directory / filename).write_text(body, encoding="utf-8")
    return directory, statuses


def load_cases(path: Path) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("cases", [])
