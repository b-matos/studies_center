"""Verification of `data` and `internal` claims by code, without any web page.

Why: statistical portals (Eurostat's databrowser, INE's bdd) are JavaScript applications, so the text
of their page cannot confirm a figure, and the `writer` has no internet to quote it. What *can* be
proved is the chain from the claim to the data actually used:

    claim -> sources.csv row (same id and URL, status tested)
          -> data/clean/<file>.parquet (its `source_id` column is that source, value recomputed by code)
          -> data/raw_manifest.csv entries (raw files present, SHA-256 unchanged)
          -> the API URL the raw files came from (the dataset code, or INE's own indicator title)

A `data` claim's `url` and `excerpt` are therefore **filled by code** (`normalize_data_claims`): the URL
is the source's, the excerpt is an identifier found in that chain (an INE indicator title taken verbatim
from the raw JSON, or the dataset code from the manifest URL). The writer only provides the value, the
clean file and the calculation, which `common.verify` recomputes.

`internal` claims describe the study's own process (an excluded source, a user decision). Their `url` is a
repository path and their excerpt must appear in that file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from common.csv_io import read_csv, write_csv
from common.download import ManifestEntry, read_manifest, verify_manifest
from common.schemas import Claim, DataSource

EXCERPT_MAX_WORDS = 14  # claims.csv rule: excerpts have fewer than 15 words


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _source(study_dir: Path, source_id: str) -> DataSource | None:
    path = study_dir / "sources.csv"
    if not path.exists():
        return None
    return next((s for s in read_csv(path, DataSource) if s.id == source_id), None)


def source_entries(study_dir: Path, source_id: str) -> list[ManifestEntry]:
    return [e for e in read_manifest(study_dir) if e.file == source_id or e.file.startswith(f"{source_id}_")]


def _words(text: str, limit: int = EXCERPT_MAX_WORDS) -> str:
    return " ".join(text.split()[:limit])


def _ine_title(raw_path: Path) -> str:
    """The indicator title INE puts in its JSON (`IndicadorDsg`), verbatim, or ''."""
    try:
        records = json.loads(raw_path.read_text(encoding="utf-8"))
        return str(records[0].get("IndicadorDsg", ""))
    except (OSError, ValueError, IndexError, AttributeError, TypeError):
        return ""


def _dataset_code(url: str) -> str:
    """Dataset code from an API URL (Eurostat `.../data/HLTH_SILC_08`, OECD, WHO...), or ''."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if "data" in parts and parts.index("data") + 1 < len(parts):
        return parts[parts.index("data") + 1]
    return parts[-1] if parts else ""


def canonical_excerpt(study_dir: Path, source_id: str) -> str:
    """An identifier of the dataset that exists in the provenance chain (<15 words), or ''."""
    for entry in source_entries(study_dir, source_id):
        raw = study_dir / "data" / "raw" / entry.file
        if raw.suffix == ".json" and raw.exists() and (title := _ine_title(raw)):
            return _words(title)
    for entry in source_entries(study_dir, source_id):
        if code := _dataset_code(entry.url):
            return code
    return ""


def _chain_text(study_dir: Path, source_id: str, source: DataSource | None) -> str:
    """Everything a data excerpt may legitimately quote: manifest URLs and files, INE titles, source name."""
    parts = [source.name, source.url] if source else []
    for entry in source_entries(study_dir, source_id):
        parts += [entry.url, entry.file]
        raw = study_dir / "data" / "raw" / entry.file
        if raw.suffix == ".json" and raw.exists():
            parts.append(_ine_title(raw))
    return _normalize(" | ".join(parts))


def data_chain_problems(study_dir: Path, claim: Claim) -> list[str]:
    """Empty list = the claim's data provenance is proven. (The value itself is recomputed in common.verify.)"""
    problems = []
    source = _source(study_dir, claim.source_id)
    if source is None:
        return [f"source_id '{claim.source_id}' is not in sources.csv"]
    if source.status != "tested":
        problems.append(f"source {source.id} is not 'tested' in sources.csv")
    if claim.url != source.url:
        problems.append(f"url differs from sources.csv for {source.id} (expected {source.url})")

    if not claim.clean_file:
        problems.append("clean_file is missing")
    else:
        clean = study_dir / "data" / "clean" / claim.clean_file
        if not clean.exists():
            problems.append(f"data/clean/{claim.clean_file} does not exist")
        else:
            ids = set(pd.read_parquet(clean, columns=["source_id"])["source_id"].astype(str))
            if ids != {claim.source_id}:
                problems.append(f"data/clean/{claim.clean_file} has source_id {sorted(ids)}, not '{claim.source_id}'")

    entries = source_entries(study_dir, claim.source_id)
    if not entries:
        problems.append(f"no raw_manifest.csv entry for source {claim.source_id}")
    else:
        mine = {e.file for e in entries}
        problems += [p for p in verify_manifest(study_dir) if any(f in p for f in mine)]

    expected = canonical_excerpt(study_dir, claim.source_id)
    if not claim.excerpt or _normalize(claim.excerpt) not in _chain_text(study_dir, claim.source_id, source):
        problems.append(f"excerpt '{claim.excerpt}' is not in the provenance chain; use '{expected}'")
    return problems


def internal_problems(study_dir: Path, claim: Claim) -> list[str]:
    """An `internal` claim cites a repository file and quotes it."""
    if re.match(r"^https?://", claim.url):
        return ["an internal claim's url must be a repository path, not a web URL"]
    root = study_dir.parent.parent
    path = (root / claim.url).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        return [f"repository file '{claim.url}' does not exist"]
    if _normalize(claim.excerpt) not in _normalize(path.read_text(encoding="utf-8", errors="replace")):
        return [f"excerpt '{claim.excerpt}' is not in {claim.url}"]
    return []


def normalize_data_claims(study_dir: Path) -> int:
    """Fill `url` and `excerpt` of every `data` claim from sources.csv and the provenance chain.

    Mechanical, deterministic and idempotent. Returns how many claims changed."""
    path = study_dir / "claims.csv"
    if not path.exists():
        return 0
    claims = read_csv(path, Claim)
    changed = 0
    for claim in claims:
        if claim.type != "data" or claim.source_nature == "internal":
            continue
        source = _source(study_dir, claim.source_id)
        if source is None:
            continue
        excerpt = canonical_excerpt(study_dir, claim.source_id)
        before = (claim.url, claim.excerpt)
        claim.url = source.url
        if excerpt:
            claim.excerpt = excerpt
        changed += before != (claim.url, claim.excerpt)
    if changed:
        write_csv(path, Claim, claims)
    return changed
