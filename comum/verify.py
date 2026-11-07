"""Deterministic verification of afirmacoes.csv rows.

Principle 4 (verificação independente) requires that the checker, not the model that
wrote the claim, confirm each fact against its source. WebFetch summaries can hallucinate
excerpts, so this module does the real check: fetch the page/PDF, normalize its text,
and fuzzy-search for the recorded excerpt. For `dado` claims, it also recomputes the
value from dados/clean/ using the recorded `calculo` expression and compares it to
the recorded `valor`.

The verificador agent runs this as a CLI, then only investigates by hand the rows this
script could not confirm automatically (e.g. JS-rendered pages — see plan's open
decision on Playwright).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from pypdf import PdfReader
from rapidfuzz import fuzz

from comum.csv_io import read_csv
from comum.schemas import Afirmacao

FUZZY_MATCH_THRESHOLD = 85


@dataclass
class VerificationResult:
    claim_id: str
    excerpt_found: bool
    value_recomputed: float | None
    value_matches: bool | None
    detail: str


def _fetch_text(url: str, *, timeout: float = 30.0) -> str:
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            reader = PdfReader(stream=BytesIO(response.content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.get_text(separator=" ")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_excerpt(url: str, excerto: str) -> tuple[bool, str]:
    try:
        page_text = _normalize(_fetch_text(url))
    except Exception as exc:  # network error, 404, JS-only page, etc.
        return False, f"could not fetch or parse URL: {exc}"

    needle = _normalize(excerto)
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


def recompute_dado(study_dir: Path, afirmacao: Afirmacao) -> tuple[float | None, bool | None, str]:
    if afirmacao.tipo != "dado" or not afirmacao.calculo or not afirmacao.ficheiro_clean:
        return None, None, "not a dado claim or missing calculo/ficheiro_clean"
    clean_path = study_dir / "dados" / "clean" / afirmacao.ficheiro_clean
    if not clean_path.exists():
        return None, False, f"missing clean file: {clean_path}"
    df = pd.read_parquet(clean_path)
    try:
        # calculo is a pandas query/eval expression written by the analista, e.g.
        # "df.query('indicador == \"mortalidade_geral\" and data == \"2022-01-01\"').valor.sum()"
        computed = eval(afirmacao.calculo, {"df": df, "pd": pd})
    except Exception as exc:
        return None, False, f"calculo failed: {exc}"
    computed = float(computed)
    recorded = float(afirmacao.valor) if afirmacao.valor is not None else None
    matches = recorded is not None and abs(computed - recorded) < 1e-6
    return computed, matches, f"computed={computed}, recorded={recorded}"


def verify_study(study_dir: Path) -> list[VerificationResult]:
    afirmacoes = read_csv(study_dir / "afirmacoes.csv", Afirmacao)
    results = []
    for afirmacao in afirmacoes:
        excerpt_found, excerpt_detail = verify_excerpt(afirmacao.url, afirmacao.excerto)
        value, matches, value_detail = recompute_dado(study_dir, afirmacao)
        results.append(
            VerificationResult(
                claim_id=afirmacao.id,
                excerpt_found=excerpt_found,
                value_recomputed=value,
                value_matches=matches,
                detail=f"{excerpt_detail}; {value_detail}",
            )
        )
    return results


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: uv run python -m comum.verify <study_dir>", file=sys.stderr)
        raise SystemExit(2)
    study_dir = Path(sys.argv[1])
    results = verify_study(study_dir)
    failures = 0
    for r in results:
        value_ok = r.value_matches is None or r.value_matches
        status = "OK" if r.excerpt_found and value_ok else "FALHOU"
        if status == "FALHOU":
            failures += 1
        print(f"[{status}] {r.claim_id}: {r.detail}")
    print(f"\n{len(results)} afirmações, {failures} falhas")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
