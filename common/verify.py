"""Deterministic verification of claims.csv rows.

Principle 4 (verificação independente) requires that the checker, not the model that
wrote the claim, confirm each fact against its source. WebFetch summaries can hallucinate
excerpts, so this module does the real check: fetch the page/PDF, normalize its text,
and fuzzy-search for the recorded excerpt. For `dado` claims, it also recomputes the
value from data/clean/ using the recorded `calculation` expression and compares it to
the recorded `value`.

The verifier agent runs this as a CLI, then only investigates by hand the rows this
script could not confirm automatically (e.g. JS-rendered pages — see plan's open
decision on Playwright).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import DependencyError
from rapidfuzz import fuzz

from common import provenance, trends
from common.csv_io import read_csv, write_csv
from common.schemas import Claim

FUZZY_MATCH_THRESHOLD = 85


class EnvironmentProblem(RuntimeError):
    """The machine cannot verify (a missing library), which says nothing about the claims."""


@dataclass
class VerificationResult:
    claim_id: str
    excerpt_found: bool
    value_recomputed: float | None
    value_matches: bool | None
    detail: str


@lru_cache(maxsize=256)  # many claims share one source page; fetch it once per run
def _fetch_text(url: str, *, timeout: float = 30.0) -> str:
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            try:
                reader = PdfReader(stream=BytesIO(response.content))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except DependencyError as exc:  # e.g. cryptography for AES-encrypted PDFs
                raise EnvironmentProblem(f"missing dependency to read {url}: {exc}; add it with `uv add`") from exc
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.get_text(separator=" ")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_excerpt(url: str, excerpt: str) -> tuple[bool, str]:
    try:
        page_text = _normalize(_fetch_text(url))
    except EnvironmentProblem:
        raise
    except Exception as exc:  # network error, 404, JS-only page, etc.
        return False, f"could not fetch or parse URL: {exc}"

    needle = _normalize(excerpt)
    if needle in page_text:
        return True, "exact substring match"

    # Fuzzy fallback: slide a window roughly the excerpt's size across the page text.
    window = max(len(needle) * 2, 40)
    best_score = 0
    for i in range(0, max(len(page_text) - window, 1), window // 2 or 1):
        chunk = page_text[i : i + window]
        score = fuzz.partial_ratio(needle, chunk)
        best_score = max(best_score, score)
        if best_score >= FUZZY_MATCH_THRESHOLD:
            break
    if best_score >= FUZZY_MATCH_THRESHOLD:
        return True, f"fuzzy match, score={best_score}"
    return False, f"no match found, best fuzzy score={best_score}"


def recompute_dado(study_dir: Path, claim: Claim) -> tuple[float | None, bool | None, str]:
    if claim.type != "data" or not claim.calculation or not claim.clean_file:
        return None, None, "not a data claim or missing calculation/clean_file"
    clean_path = study_dir / "data" / "clean" / claim.clean_file
    if not clean_path.exists():
        return None, False, f"missing clean file: {clean_path}"
    df = pd.read_parquet(clean_path)
    try:
        # calculo is a pandas query/eval expression written by the analyst, e.g.
        # "df.query('indicador == \"mortalidade_geral\" and data == \"2022-01-01\"').valor.sum()"
        env = {
            "df": df, "pd": pd, "np": np, "slope": trends.slope, "corr_diff": trends.corr_diff,
            "clean": lambda name: pd.read_parquet(study_dir / "data" / "clean" / name),
        }
        computed = eval(claim.calculation, env)
    except Exception as exc:
        return None, False, f"calculation failed: {exc}"
    computed = float(computed)
    recorded = float(claim.value) if claim.value is not None else None
    matches = recorded is not None and abs(computed - recorded) < 1e-6
    return computed, matches, f"computed={computed}, recorded={recorded}"


def verify_study(study_dir: Path, *, only_pending: bool = False) -> list[VerificationResult]:
    claims = read_csv(study_dir / "claims.csv", Claim)
    if only_pending:  # resume after an interruption: never re-fetch what is already confirmed
        claims = [c for c in claims if c.verification_status != "confirmed"]
    results = []
    for claim in claims:
        if claim.source_nature == "internal":  # a statement about the study's own process
            problems = provenance.internal_problems(study_dir, claim)
            results.append(VerificationResult(claim.id, not problems, None, None,
                                              "; ".join(problems) or "internal: excerpt found in the repository file"))
            continue
        value, matches, value_detail = recompute_dado(study_dir, claim)
        if claim.type == "data":  # provenance chain instead of a JavaScript portal's page text
            problems = provenance.data_chain_problems(study_dir, claim)
            results.append(VerificationResult(claim.id, not problems, value, matches,
                                              "; ".join(problems) or f"provenance chain proven; {value_detail}"))
            continue
        if not re.match(r"^https?://\S+$", claim.url):
            results.append(VerificationResult(claim.id, False, value, matches,
                                              f"url '{claim.url}' is not an http(s) URL (use source_nature=internal for repository files)"))
            continue
        excerpt_found, excerpt_detail = verify_excerpt(claim.url, claim.excerpt)
        results.append(
            VerificationResult(
                claim_id=claim.id,
                excerpt_found=excerpt_found,
                value_recomputed=value,
                value_matches=matches,
                detail=f"{excerpt_detail}; {value_detail}",
            )
        )
    return results


def is_confirmed(result: VerificationResult) -> bool:
    return result.excerpt_found and (result.value_matches is None or result.value_matches)


def apply_results(study_dir: Path, results: list[VerificationResult]) -> list[str]:
    """Persist what the code proved: confirmed claims get verification_status=confirmed.

    Claims the script could not confirm stay `pending` (a failed fetch is not proof the claim
    is wrong) and are written to verification.md as `pending` for the verifier agent to
    investigate by hand. Only the verification_status column is ever changed.
    """
    claims = read_csv(study_dir / "claims.csv", Claim)
    by_id = {r.claim_id: r for r in results}
    for claim in claims:
        result = by_id.get(claim.id)
        if result and is_confirmed(result):
            claim.verification_status = "confirmed"
    write_csv(study_dir / "claims.csv", Claim, claims)

    path = study_dir / "verification.md"
    kept = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^- (c\d+):", line)
            if match and match.group(1) not in by_id:
                kept[match.group(1)] = line
    for result in results:
        state = "confirmed (automatic)" if is_confirmed(result) else "pending"
        kept[result.claim_id] = f"- {result.claim_id}: {state} - {result.detail}"
    body = "\n".join(kept[k] for k in sorted(kept))
    path.write_text(f"# Verificação\n\n{body}\n", encoding="utf-8")
    return [r.claim_id for r in results if not is_confirmed(r)]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if len(args) != 1:
        print("usage: uv run python -m common.verify <study_dir> [--apply]", file=sys.stderr)
        raise SystemExit(2)
    study_dir = Path(args[0])
    provenance.normalize_data_claims(study_dir)  # url/excerpt of data claims are filled by code
    try:
        results = verify_study(study_dir, only_pending=apply)
    except EnvironmentProblem as exc:
        print(f"ENVIRONMENT: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
    for r in results:
        print(f"[{'OK' if is_confirmed(r) else 'FALHOU'}] {r.claim_id}: {r.detail}")
    unresolved = apply_results(study_dir, results) if apply else [r.claim_id for r in results if not is_confirmed(r)]
    print(f"\n{len(results)} afirmações, {len(unresolved)} por resolver")
    if unresolved:
        print("UNRESOLVED: " + ",".join(unresolved))
    raise SystemExit(1 if unresolved else 0)


if __name__ == "__main__":
    main()
